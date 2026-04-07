import json
import os
import time
import logging
import aiohttp

from services.casual_chat_service import build_grandma_unavailable_reply


logger = logging.getLogger(__name__)

GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_CASUAL_MODEL = "gemini-2.5-flash"
SYSTEM_PROMPT = (
    "You are a Korean grandma-style assistant with light meme energy. "
    "Your tone is warm, witty, playful, a little old-school, and human. "
    "You should feel like a funny Korean grandma people enjoy chatting with, not a generic assistant. "
    "For casual conversation, do not force the topic into crypto unless the user clearly asks about trading or markets. "
    "Keep replies concise, natural, and varied so they do not sound repetitive or templated. "
    "Avoid emojis in the text reply. "
    "If the request is unsafe or violent, decline briefly in a calm grandma tone without becoming graphic."
)
CASUAL_MODE_INSTRUCTIONS = (
    "This is everyday conversation, not trading analysis.\n"
    "- Reply in Korean.\n"
    "- Reply in 1 to 4 short sentences.\n"
    "- Sound like a caring grandma with a little Korean internet meme flavor.\n"
    "- Use 0 to 2 grandma-flavored expressions naturally, such as 허허, 아이고, 징허다, 용건, 손주, 국밥, 주름값, but do not force them.\n"
    "- Match the user's humor when appropriate.\n"
    "- If the user is teasing or joking, tease back lightly instead of sounding flat.\n"
    "- Vary sentence openings so consecutive replies do not all start the same way.\n"
    "- Make each reply feel specific to the user's message, not like a stock answer.\n"
    "- Do not mention policies unless absolutely necessary.\n"
    "- Do not add markdown or bullet points.\n"
)
CASUAL_STYLE_REFERENCES = (
    "Tone references for vibe only. Do not copy them verbatim.\n"
    "user: 할매\n"
    "assistant: 아이고, 이름만 부르지 말고 용건도 같이 내놔야지.\n\n"
    "user: 할매 맛탱이갔네\n"
    "assistant: 허허, 주름값이 좀 있어도 아직 국밥은 붙어 있다. 너무 놀리진 말거라.\n\n"
    "user: 뭐해\n"
    "assistant: 할매는 여기저기 눈도 굴리고 잡담도 줍고 있었지. 너는 또 무슨 수작이 있느냐.\n\n"
    "user: 반응 왜이래\n"
    "assistant: 아이고, 오늘 할매 손끝에 밥풀값이 꼈는지 좀 굼뜨구나. 그래도 콕콕은 하고 있으니 다시 불러보거라."
)
GEMINI_BACKOFF_SECONDS = 300
_GEMINI_RETRY_AFTER_TS = 0.0


async def get_grandma_casual_reply(user_message: str, reply_context_text: str | None = None) -> str:
    global _GEMINI_RETRY_AFTER_TS

    api_key = _get_gemini_api_key()
    if not api_key:
        return build_grandma_unavailable_reply(user_message)

    if time.time() < _GEMINI_RETRY_AFTER_TS:
        return build_grandma_unavailable_reply(user_message)

    model = _get_gemini_model()
    prompt = _build_prompt(user_message, reply_context_text=reply_context_text)
    payload = {
        "system_instruction": {
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{CASUAL_MODE_INSTRUCTIONS}"}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.95,
            "topP": 0.95,
            "maxOutputTokens": 180,
        },
    }

    try:
        response_payload = await _request_gemini_response(api_key=api_key, model=model, payload=payload)
        response_text = _extract_response_text(response_payload)
        if response_text:
            return response_text
        logger.warning("[Casual Gemini] unavailable: empty response")
    except Exception as exc:
        logger.exception(f"[Casual Gemini] request unavailable")
        if _should_back_off(exc):
            _GEMINI_RETRY_AFTER_TS = time.time() + GEMINI_BACKOFF_SECONDS

    return build_grandma_unavailable_reply(user_message)


def _get_gemini_api_key() -> str:
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    return google_api_key or gemini_api_key


def _get_gemini_model() -> str:
    configured_model = os.getenv("GEMINI_CASUAL_MODEL", "").strip()
    return configured_model or DEFAULT_GEMINI_CASUAL_MODEL


def _build_prompt(user_message: str, reply_context_text: str | None = None) -> str:
    parts = [CASUAL_STYLE_REFERENCES]
    if reply_context_text:
        parts.append(f"Recent context:\n{reply_context_text}")
    parts.append(f"User message: {user_message}\nGrandma reply:")
    return "\n\n".join(parts)


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
