import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

from pathlib import Path


logger = logging.getLogger(__name__)

DEFAULT_LOCAL_QWEN_BACKEND = "ollama"
DEFAULT_LOCAL_QWEN_MODEL_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
DEFAULT_LOCAL_QWEN_MODEL_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_LOCAL_QWEN_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_LOCAL_QWEN_OLLAMA_MODEL = "gemma4:e4b"
DEFAULT_LOCAL_QWEN_HISTORY_LIMIT = 4
DEFAULT_LOCAL_QWEN_CTX = 2048
DEFAULT_LOCAL_QWEN_MAX_TOKENS = 160
DEFAULT_LOCAL_QWEN_REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_LOCAL_QWEN_TEMPERATURE = 0.9
DEFAULT_LOCAL_QWEN_TOP_P = 0.9
DEFAULT_LOCAL_QWEN_N_BATCH = 128
LOCAL_QWEN_FAILURE_BACKOFF_SECONDS = 20
COMPACT_LOCAL_QWEN_HISTORY_LIMIT = 2
COMPACT_LOCAL_QWEN_MAX_TOKENS = 96
LOCAL_QWEN_META_LEAK_MARKERS = (
    "interactions",
    "system prompt",
    "developer instructions",
    "project setup",
    "assistant",
    "role",
    "\uc0ac\uc6a9\uc790\ub294",
    "\uaddc\uce59",
    "\uc9c0\uce68",
    "\ud504\ub86c\ud504\ud2b8",
    "\uc2dc\uc2a4\ud15c",
    "\uc5ed\ud560",
)
LOCAL_QWEN_PERSONA_DRIFT_MARKERS = (
    "\uc5c4\ub9c8\ud55c\ud14c",
    "\uc5c4\ub9c8\uac00",
    "\uc5c4\ub9c8\uac00 \ub2e4",
    "\uc5c4\ub9c8\uac00 \uc54c\uc544\uc11c",
    "\uc5c4\ub9c8\uac00 \ud574\uc904\uac8c",
    "\uc5c4\ub9c8\uc5d0\uac8c",
    "\ub124 \uc5c4\ub9c8",
    "\ub2c8 \uc5c4\ub9c8",
    "\ub0b4\uac00 \ub124 \uc5c4\ub9c8",
)

_LOCAL_QWEN = None
_LOCAL_QWEN_LOCK = threading.Lock()
_LOCAL_QWEN_RETRY_AFTER_TS = 0.0
_LOCAL_QWEN_LAST_ERROR_MESSAGE: str | None = None


class LocalQwenMetaLeakError(RuntimeError):
    pass


class LocalQwenPersonaDriftError(RuntimeError):
    pass


def local_qwen_is_enabled() -> bool:
    value = os.getenv("LOCAL_QWEN_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


async def get_local_qwen_casual_reply(
    *,
    user_message: str,
    history: list[dict[str, str]] | None,
    system_prompt: str,
    mode_instructions: str,
) -> str | None:
    global _LOCAL_QWEN_LAST_ERROR_MESSAGE, _LOCAL_QWEN_RETRY_AFTER_TS

    if not local_qwen_is_enabled():
        return None

    if time.time() < _LOCAL_QWEN_RETRY_AFTER_TS:
        return None

    try:
        reply = await asyncio.to_thread(
            _generate_local_qwen_reply,
            user_message,
            history,
            system_prompt,
            mode_instructions,
        )
        if reply:
            _LOCAL_QWEN_LAST_ERROR_MESSAGE = None
            return reply

        _LOCAL_QWEN_LAST_ERROR_MESSAGE = "모델이 비어 있는 답변을 돌려줬습니다."
        return None
    except Exception as exc:
        if isinstance(exc, LocalQwenPersonaDriftError):
            logger.warning("[Local Qwen] persona drift blocked: %s", exc)
            _LOCAL_QWEN_LAST_ERROR_MESSAGE = None
            _LOCAL_QWEN_RETRY_AFTER_TS = 0.0
            return "아이고, 방금 할매가 말이 헛나왔구나. 나는 엄마가 아니라 할머니지. 무슨 일인지 차근차근 말해보거라."

        logger.exception("[Local Qwen] unavailable")
        _LOCAL_QWEN_LAST_ERROR_MESSAGE = _summarize_local_qwen_error(exc)
        _LOCAL_QWEN_RETRY_AFTER_TS = (
            time.time() + LOCAL_QWEN_FAILURE_BACKOFF_SECONDS
            if _should_back_off_local_qwen_error(exc)
            else 0.0
        )
        return None


def build_local_qwen_error_reply() -> str:
    if not local_qwen_is_enabled():
        return "아이고, 지금은 할매가 긴 대답은 잠깐 쉬는 중이구나. 짧게 다시 말해주면 받아볼게."

    if time.time() < _LOCAL_QWEN_RETRY_AFTER_TS:
        return "아이고, 방금 말이 좀 꼬였구나. 숨 한 번 고르고 다시 들어볼 테니 조금 있다 다시 말해보거라."

    if _LOCAL_QWEN_LAST_ERROR_MESSAGE:
        return "아이고, 할매가 방금 대답을 제대로 못 만들었구나. 핵심만 짧게 다시 던져주면 더 낫겠다."

    return "아이고, 할매가 지금 답을 못 만들고 있구나. 잠깐 뒤에 다시 말해보거라."


def _generate_local_qwen_reply(
    user_message: str,
    history: list[dict[str, str]] | None,
    system_prompt: str,
    mode_instructions: str,
) -> str | None:
    messages = _build_messages(
        history=history,
        user_message=user_message,
        system_prompt=system_prompt,
        mode_instructions=mode_instructions,
    )
    llm = None if _get_local_qwen_backend() == "ollama" else _get_local_qwen()

    try:
        response = _create_local_qwen_completion(
            llm=llm,
            messages=messages,
            max_tokens=_get_local_qwen_max_tokens(),
        )
    except ValueError as exc:
        if not _is_context_window_error(exc):
            raise

        logger.warning("[Local Qwen] context overflow, retrying with compact prompt")
        compact_messages = _build_messages(
            history=(history or [])[-COMPACT_LOCAL_QWEN_HISTORY_LIMIT:],
            user_message=user_message,
            system_prompt=system_prompt,
            mode_instructions=mode_instructions,
        )
        response = _create_local_qwen_completion(
            llm=llm,
            messages=compact_messages,
            max_tokens=min(COMPACT_LOCAL_QWEN_MAX_TOKENS, _get_local_qwen_max_tokens()),
        )

    reply_text = _extract_response_text(response)
    if reply_text and _looks_like_meta_leakage(reply_text):
        raise LocalQwenMetaLeakError("Local Qwen produced a meta/system-style reply")
    if reply_text and _looks_like_persona_drift(reply_text):
        raise LocalQwenPersonaDriftError("Local Qwen drifted into a mother/guardian persona")
    return reply_text


def _create_local_qwen_completion(*, llm, messages: list[dict[str, str]], max_tokens: int) -> dict:
    if _get_local_qwen_backend() == "ollama":
        return _create_ollama_chat_completion(messages=messages, max_tokens=max_tokens)
    return llm.create_chat_completion(
        messages=messages,
        temperature=_get_local_qwen_temperature(),
        top_p=_get_local_qwen_top_p(),
        max_tokens=max_tokens,
    )


def _create_ollama_chat_completion(*, messages: list[dict[str, str]], max_tokens: int) -> dict:
    payload = {
        "model": _get_local_qwen_ollama_model(),
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": _get_local_qwen_temperature(),
            "top_p": _get_local_qwen_top_p(),
            "num_predict": max_tokens,
            "num_ctx": _get_local_qwen_ctx(),
        },
    }
    request = urllib.request.Request(
        _get_local_qwen_ollama_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_get_local_qwen_request_timeout_seconds()) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"Ollama request failed with HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Ollama server is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON") from exc

    message = response_payload.get("message") or {}
    content = str(message.get("content", ""))
    return {"choices": [{"message": {"content": content}}]}


def _get_local_qwen():
    global _LOCAL_QWEN

    if _LOCAL_QWEN is not None:
        return _LOCAL_QWEN

    with _LOCAL_QWEN_LOCK:
        if _LOCAL_QWEN is not None:
            return _LOCAL_QWEN

        try:
            from huggingface_hub import hf_hub_download
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError("Local Qwen dependencies are not installed") from exc

        cache_dir = _get_local_qwen_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        model_repo = os.getenv("LOCAL_QWEN_MODEL_REPO", DEFAULT_LOCAL_QWEN_MODEL_REPO).strip()
        model_file = os.getenv("LOCAL_QWEN_MODEL_FILE", DEFAULT_LOCAL_QWEN_MODEL_FILE).strip()

        model_path = hf_hub_download(
            repo_id=model_repo,
            filename=model_file,
            cache_dir=str(cache_dir),
        )
        logger.info(
            "[Local Qwen] loading model repo=%s file=%s path=%s",
            model_repo,
            model_file,
            model_path,
        )

        _LOCAL_QWEN = Llama(
            model_path=model_path,
            chat_format="chatml",
            n_ctx=_get_local_qwen_ctx(),
            n_threads=_get_local_qwen_threads(),
            n_batch=_get_local_qwen_n_batch(),
            n_gpu_layers=0,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
        )
        return _LOCAL_QWEN


def _build_messages(
    *,
    history: list[dict[str, str]] | None,
    user_message: str,
    system_prompt: str,
    mode_instructions: str,
) -> list[dict[str, str]]:
    system_message = f"{system_prompt}\n\n{mode_instructions}".strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_message}]

    if history:
        trimmed_history = history[-_get_local_qwen_history_limit() :]
        for item in trimmed_history:
            role = "assistant" if item.get("role") == "assistant" else "user"
            content = str(item.get("content", "")).strip()
            if content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})
    return messages


def _extract_response_text(payload: dict) -> str | None:
    choices = payload.get("choices") or []
    if not choices:
        return None

    message = choices[0].get("message") or {}
    content = str(message.get("content", "")).strip()
    return content or None


def _looks_like_meta_leakage(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(marker in normalized for marker in LOCAL_QWEN_META_LEAK_MARKERS)


def _looks_like_persona_drift(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(marker in normalized for marker in LOCAL_QWEN_PERSONA_DRIFT_MARKERS)


def _get_local_qwen_cache_dir() -> Path:
    configured = os.getenv("LOCAL_QWEN_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "grannybot-local-qwen"


def _get_local_qwen_backend() -> str:
    configured = os.getenv("LOCAL_QWEN_BACKEND", "").strip().lower()
    if configured in {"llama_cpp", "llama-cpp"}:
        return "llama_cpp"
    if configured == "ollama":
        return "ollama"
    return DEFAULT_LOCAL_QWEN_BACKEND


def _get_local_qwen_ollama_model() -> str:
    configured = os.getenv("LOCAL_QWEN_OLLAMA_MODEL", "").strip()
    return configured or DEFAULT_LOCAL_QWEN_OLLAMA_MODEL


def _get_local_qwen_ollama_url() -> str:
    host = os.getenv("LOCAL_QWEN_OLLAMA_HOST", DEFAULT_LOCAL_QWEN_OLLAMA_HOST).strip().rstrip("/")
    return f"{host}/api/chat"


def _get_local_qwen_ctx() -> int:
    return _get_positive_int("LOCAL_QWEN_CTX", DEFAULT_LOCAL_QWEN_CTX)


def _get_local_qwen_max_tokens() -> int:
    return _get_positive_int("LOCAL_QWEN_MAX_TOKENS", DEFAULT_LOCAL_QWEN_MAX_TOKENS)


def _get_local_qwen_request_timeout_seconds() -> int:
    value = _get_positive_int("LOCAL_QWEN_REQUEST_TIMEOUT_SECONDS", DEFAULT_LOCAL_QWEN_REQUEST_TIMEOUT_SECONDS)
    return min(60, max(5, value))


def _get_local_qwen_history_limit() -> int:
    return _get_positive_int("LOCAL_QWEN_HISTORY_LIMIT", DEFAULT_LOCAL_QWEN_HISTORY_LIMIT)


def _get_local_qwen_n_batch() -> int:
    return _get_positive_int("LOCAL_QWEN_N_BATCH", DEFAULT_LOCAL_QWEN_N_BATCH)


def _get_local_qwen_threads() -> int:
    configured = _get_positive_int("LOCAL_QWEN_THREADS", 0)
    if configured:
        return configured
    return max(1, min(2, os.cpu_count() or 1))


def _get_local_qwen_temperature() -> float:
    return _get_positive_float("LOCAL_QWEN_TEMPERATURE", DEFAULT_LOCAL_QWEN_TEMPERATURE)


def _get_local_qwen_top_p() -> float:
    return _get_positive_float("LOCAL_QWEN_TOP_P", DEFAULT_LOCAL_QWEN_TOP_P)


def _get_positive_int(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_positive_float(env_name: str, default: float) -> float:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _summarize_local_qwen_error(exc: Exception) -> str:
    if isinstance(exc, LocalQwenMetaLeakError):
        return "Qwen\uc774 \uba54\ud0c0 \uc124\uba85 \uac19\uc740 \ub2f5\uc744 \ub9cc\ub4e4\uc5b4 \ub2e4\uc2dc \ub9c9\uc558\uc2b5\ub2c8\ub2e4."
    if isinstance(exc, LocalQwenPersonaDriftError):
        return "Qwen\uc774 \ud560\uba38\ub2c8 \uc5ed\ud560\uc5d0\uc11c \ube57\ub098\uac04 \ub2f5\uc744 \ub9cc\ub4e4\uc5b4 \ub2e4\uc2dc \ub9c9\uc558\uc2b5\ub2c8\ub2e4."

    raw_message = str(exc).strip().lower()

    if "context window" in raw_message or "requested tokens" in raw_message:
        return "질문이 길어서 현재 Qwen 문맥 창 크기를 넘겼습니다."
    if "ollama server is unavailable" in raw_message:
        return "Ollama 서버에 연결하지 못했습니다."
    if "timed out" in raw_message or "timeout" in raw_message:
        return "Ollama 응답 시간이 초과되었습니다."
    if "ollama request failed" in raw_message:
        return "Ollama 요청이 실패했습니다."
    if "ollama returned invalid json" in raw_message:
        return "Ollama 결과를 해석하지 못했습니다."
    if "dependencies are not installed" in raw_message:
        return "필수 라이브러리가 아직 설치되지 않았습니다."
    if "libgomp" in raw_message:
        return "필수 시스템 라이브러리(libgomp)를 찾지 못했습니다."
    if "401" in raw_message or "403" in raw_message or "404" in raw_message:
        return "Qwen 모델 파일을 내려받지 못했습니다."
    if "no space left" in raw_message:
        return "디스크 공간이 부족합니다."
    if "memory" in raw_message or "bad alloc" in raw_message or "killed" in raw_message:
        return "메모리가 부족해 모델을 불러오지 못했습니다."
    if "model" in raw_message or "llama" in raw_message:
        return "모델을 불러오지 못했습니다."
    return "응답 생성 중 오류가 발생했습니다."


def _is_context_window_error(exc: Exception) -> bool:
    raw_message = str(exc).strip().lower()
    return "context window" in raw_message or "requested tokens" in raw_message


def _should_back_off_local_qwen_error(exc: Exception) -> bool:
    if isinstance(exc, (LocalQwenMetaLeakError, LocalQwenPersonaDriftError)):
        return False
    if _is_context_window_error(exc):
        return False
    return True
