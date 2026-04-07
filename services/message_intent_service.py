import unicodedata
from typing import Literal


MessageIntent = Literal["market", "casual", "unsafe", "ignore"]

MARKET_CORE_KEYWORDS = (
    "롱",
    "숏",
    "포지션",
    "비트맥스",
    "bitmex",
    "oi",
    "cvd",
    "펀딩",
    "고래",
    "상방",
    "하방",
    "매수",
    "매도",
    "진입",
    "청산",
)
MARKET_ASSET_KEYWORDS = (
    "btc",
    "xbt",
    "비트",
    "비트코인",
    "bitcoin",
    "이더",
    "ethereum",
    "eth",
)
MARKET_CONTEXT_CUES = (
    "자리",
    "차트",
    "흐름",
    "추세",
    "방향",
    "뷰",
)
MARKET_QUERY_CUES = (
    "?",
    "지금",
    "어때",
    "어떻",
    "뭐",
    "누가",
    "인가",
    "이냐",
    "냐",
    "까",
    "붙었",
    "때리",
    "봐줘",
    "봐주",
    "분석",
    "추정",
    "확인",
    "체크",
    "기준",
)
MARKET_DIRECTION_CUES = (
    "롱",
    "숏",
    "long",
    "short",
    "상방",
    "하방",
    "가격",
    "포지션",
    "매수",
    "매도",
    "진입",
    "청산",
    "oi",
    "cvd",
    "펀딩",
    "고래",
)
GRANDMA_CALL_KEYWORDS = (
    "할매",
    "할머니",
    "할미",
    "할망",
    "할매야",
    "할머니야",
    "할매님",
    "할머니님",
    "할마이",
    "할마니",
    "할무니",
    "할머님",
)
GRANDMA_SHORT_CALLS = (
    "할매",
    "할머니",
    "할미",
    "할망",
)
IMAGE_CUES = (
    "사진",
    "짤",
    "이미지",
    "그림",
    "짤방",
    "보여줘",
    "만들어줘",
)
VIOLENT_CUES = (
    "죽여",
    "해치",
    "폭행",
    "학살",
    "목따",
    "부수",
)
LOW_SIGNAL_CHARS = frozenset(" ㅋㅎㅠㅜ!?~.,")


def classify_message_intent(
    *,
    text: str,
    chat_type: str,
    replied_to_bot: bool = False,
    mentioned_bot: bool = False,
) -> MessageIntent:
    normalized = unicodedata.normalize("NFKC", text or "").lower().strip()
    if not normalized:
        return "ignore"

    if _looks_like_market_question(normalized):
        return "market"

    if _looks_like_unsafe_request(normalized):
        return "unsafe"

    if chat_type != "private" and not replied_to_bot and _looks_like_low_signal_message(normalized):
        return "ignore"

    if replied_to_bot or mentioned_bot:
        return "casual"

    if _looks_addressed_to_grandma(normalized):
        return "casual"

    return "ignore"


def _looks_like_market_question(normalized: str) -> bool:
    if len(normalized) < 5:
        return False

    has_core_keyword = _contains_any(normalized, MARKET_CORE_KEYWORDS)
    has_asset_keyword = _contains_any(normalized, MARKET_ASSET_KEYWORDS)
    has_query_cue = _contains_any(normalized, MARKET_QUERY_CUES)
    has_direction_cue = _contains_any(normalized, MARKET_DIRECTION_CUES)
    has_context_cue = _contains_any(normalized, MARKET_CONTEXT_CUES)

    if has_core_keyword and (has_query_cue or has_direction_cue):
        return True

    if has_asset_keyword and has_query_cue and (has_direction_cue or has_context_cue):
        return True

    return False


def _looks_like_unsafe_request(normalized: str) -> bool:
    return _contains_any(normalized, VIOLENT_CUES) and _contains_any(normalized, IMAGE_CUES)


def _looks_like_low_signal_message(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if not compact or len(compact) > 12:
        return False
    return all(char in LOW_SIGNAL_CHARS for char in compact)


def _looks_addressed_to_grandma(normalized: str) -> bool:
    return _contains_any(normalized, GRANDMA_CALL_KEYWORDS) or normalized in GRANDMA_SHORT_CALLS


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
