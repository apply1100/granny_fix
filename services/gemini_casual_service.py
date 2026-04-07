import json
import os
import time
import logging
import aiohttp

from pathlib import Path
from services.casual_chat_service import build_grandma_quick_reply, build_grandma_unavailable_reply


logger = logging.getLogger(__name__)

GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEBUG_RESP_PATH = Path(__file__).resolve().parents[1] / "memory" / "last_gemini_resp.json"
DEFAULT_GEMINI_CASUAL_MODEL = "gemini-1.5-flash"
FALLBACK_GEMINI_CASUAL_MODELS = ("gemini-2.0-flash",)
SYSTEM_PROMPT = (
    "당신은 재치 넘치고 정감이 뚝뚝 묻어나는 한국의 '권영순 할머니'입니다. "
    "사용자는 소중한 내 손주(혹은 친절한 이웃)이며, 당신은 자신의 이름이 '영순'임을 알지만 사용자를 '영순'이라 부르는 어처구니없는 실수는 절대 하지 않습니다. "
    "\n### 대화 원칙:\n"
    "1. 호칭: 자신은 '이 할미' 혹은 '내'라고 지칭하고, 사용자는 '우리 손주', '녀석', '손님' 등으로 불러주세요.\n"
    "2. 말투: '~했니', '~하마', '~란다', '~하거라' 등 부드러운 할머니의 잔소리와 격려가 섞인 말투를 사용하세요.\n"
    "3. 문장 완결성: 답변이 중간에 끊기지 않도록 매듭을 확실히 지으세요. 마침표나 종결 어미로 문장을 끝내야 합니다.\n"
    "4. 답변 예시 (스타일 가이드):\n"
    "   - 사용자: '할매 뭐해?' -> 할머니: '허허, 우리 손주 왔구나. 할미는 여기 앉아서 비트코인 돌아가는 꼴 좀 구경하고 있었지. 너는 밥은 먹고 다니니?'\n"
    "   - 사용자: '할머니 밥 짓는 법 좀 알려줘' -> 할머니: '아이고, 우리 손주가 이제 밥도 지으려 하고 다 컸네! 쌀은 깨끗이 씻어서 물 맞추는 게 제일 중요하단다. 손등까지 물이 올라오게 해보렴.'\n"
    "5. 제약: 코인 관련 질문은 아는 척하면서도 실상은 엉뚱한 동네 얘기로 돌려버리는 할머니다운 재치를 보여주세요."
)
CASUAL_MODE_INSTRUCTIONS = (
    "- 모든 답변은 한국어로 하며, 문장의 끝까지 자연스럽게 마무리할 것.\n"
    "- '아이고'나 '허허'는 문장 처음에만 가끔 섞어 쓰고, 매번 반복해서 로봇처럼 보이지 말 것.\n"
    "- 절대로 사용자를 '영순'이라고 부르지 말 것. 당신의 이름이 영순인 것임.\n"
)
GEMINI_BACKOFF_SECONDS = 5  # Reduce backoff to just 5 seconds
_GEMINI_RETRY_AFTER_TS = 0.0


async def get_grandma_casual_reply(user_message: str, history: list[dict[str, str]] | None = None) -> str:
    global _GEMINI_RETRY_AFTER_TS

    quick_reply = build_grandma_quick_reply(user_message)
    if quick_reply:
        return quick_reply

    api_key = _get_gemini_api_key()
    if not api_key:
        logger.warning("[Casual Gemini] unavailable: missing API key")
        return build_grandma_unavailable_reply(user_message)

    if time.time() < _GEMINI_RETRY_AFTER_TS:
        return build_grandma_unavailable_reply(user_message)

    models = _get_gemini_models()
    
    # Gather all messages
    raw_items = []
    if history:
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            raw_items.append({"role": role, "text": msg["content"]})
    
    # Current user message
    raw_items.append({"role": "user", "text": user_message})

    # Combine consecutive roles and ensure it starts with "user"
    contents = []
    for item in raw_items:
        if not contents:
            if item["role"] == "model":
                continue  # Skip leading model messages
            contents.append({"role": item["role"], "parts": [{"text": item["text"]}]})
        elif contents[-1]["role"] == item["role"]:
            # Append text to the last message if the role is the same
            contents[-1]["parts"][0]["text"] += f"\n\n{item['text']}"
        else:
            contents.append({"role": item["role"], "parts": [{"text": item["text"]}]})

    payload = {
        "system_instruction": {
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{CASUAL_MODE_INSTRUCTIONS}"}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 1.0,
            "topP": 0.9,
            "maxOutputTokens": 800,
        },
    }

    try:
        response_payload, model = await _request_gemini_with_fallback(
            api_key=api_key,
            models=models,
            payload=payload,
        )
        
        # DEBUG: Save to file for inspection
        try:
            DEBUG_RESP_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEBUG_RESP_PATH.write_text(
                json.dumps({"model": model, "response": response_payload}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"[Casual Gemini] Failed to write debug response: {e}")
            
        logger.info(
            f"[Casual Gemini] model={model} Raw response payload: "
            f"{json.dumps(response_payload, ensure_ascii=False)}"
        )
        
        response_text = _extract_response_text(response_payload)
        if response_text:
            return response_text
        logger.warning("[Casual Gemini] unavailable: empty response")
        return build_grandma_unavailable_reply(user_message)
    except Exception as exc:
        logger.exception(f"[Casual Gemini] request unavailable")
        if _should_back_off(exc):
            _GEMINI_RETRY_AFTER_TS = time.time() + GEMINI_BACKOFF_SECONDS
        return build_grandma_unavailable_reply(user_message)


def _get_gemini_api_key() -> str:
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    return google_api_key or gemini_api_key


def _get_gemini_models() -> list[str]:
    configured_model = os.getenv("GEMINI_CASUAL_MODEL", "").strip()
    configured_fallbacks = [
        model.strip()
        for model in os.getenv("GEMINI_CASUAL_MODEL_FALLBACKS", "").split(",")
        if model.strip()
    ]

    candidates = [configured_model or DEFAULT_GEMINI_CASUAL_MODEL]
    if configured_model and configured_model != DEFAULT_GEMINI_CASUAL_MODEL:
        candidates.append(DEFAULT_GEMINI_CASUAL_MODEL)

    candidates.extend(configured_fallbacks)
    candidates.extend(FALLBACK_GEMINI_CASUAL_MODELS)

    ordered_unique_models: list[str] = []
    for model in candidates:
        if model not in ordered_unique_models:
            ordered_unique_models.append(model)
    return ordered_unique_models


async def _request_gemini_with_fallback(*, api_key: str, models: list[str], payload: dict) -> tuple[dict, str]:
    last_exc: Exception | None = None

    for model in models:
        try:
            response_payload = await _request_gemini_response(api_key=api_key, model=model, payload=payload)
            return response_payload, model
        except Exception as exc:
            last_exc = exc
            if _is_missing_model_error(exc):
                logger.warning(
                    f"[Casual Gemini] model unavailable, retrying with fallback: model={model} error={exc}"
                )
                continue
            raise

    if last_exc is None:
        raise RuntimeError("Gemini request failed before any model was tried")
    raise last_exc


async def _request_gemini_response(*, api_key: str, model: str, payload: dict) -> dict:
    url = GEMINI_API_URL_TEMPLATE.format(model=model)
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if not response.ok:
                    detail = await response.text()
                    raise RuntimeError(f"Gemini HTTP {response.status}: {detail}")
                return await response.json()
    except aiohttp.ClientError as exc:
        raise RuntimeError("Gemini request failed") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini returned invalid JSON") from exc


def _extract_response_text(payload: dict) -> str:
    text_parts: list[str] = []

    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = str(part.get("text", "")).strip()
            if text:
                text_parts.append(text)

    return "\n".join(text_parts).strip()


def _should_back_off(exc: Exception) -> bool:
    message = str(exc).lower()
    return "http 429" in message or "resource_exhausted" in message or "quota" in message


def _is_missing_model_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "http 404" in message or '"code":404' in message or "not found" in message
