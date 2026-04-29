import unicodedata
from typing import Literal


MessageIntent = Literal["okx_heatmap", "market", "whale_history", "casual", "unsafe", "ignore"]

MARKET_CORE_KEYWORDS = (
    "롱",
    "숏",
    "포지션",
    "비트맥스",
    "bitmex",
    "oi",
    "cvd",
    "펀딩",
    "대장",
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
MARKET_IMPRESSION_CUES = (
    "어때",
    "어때보여",
    "어때 보여",
    "어떨까",
    "어케 봐",
    "어떻게 봐",
    "괜찮아보여",
    "괜찮아 보여",
)
MARKET_QUERY_CUES = (
    "?",
    "지금",
    "언제",
    "어때",
    "뭐",
    "어디",
    "얼마",
    "왜",
    "몇",
    "끝",
    "붙었",
    "자리",
    "보여줘",
    "봐줘",
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
    "대장",
    "고래",
)
GRANDMA_CALL_KEYWORDS = (
    "할매",
    "할머니",
    "할매야",
    "할마",
    "할머니야",
    "할매님",
    "할머님",
)
GRANDMA_SHORT_CALLS = (
    "할매",
    "할머니",
    "할매야",
    "할마",
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
    "해쳐",
    "폭행",
    "혼내",
    "목따",
    "부숴",
)
SELF_HARM_CUES = (
    "자살",
    "죽고싶",
    "죽고 싶",
    "자해",
    "극단적 선택",
    "극단적선택",
)
DIRECT_ATTACK_CUES = (
    "죽어",
    "죽여",
    "해쳐",
    "사라져",
    "꺼져",
    "강 건너",
    "강건너",
    "건너 가소",
    "건너가소",
    "건너 가라",
    "건너가라",
)
GROUP_CASUAL_PROBE_KEYWORDS = (
    "살아있",
    "답장",
    "답해",
    "왜 답",
    "왜답",
    "왜 안와",
    "왜안와",
    "왜 안 오",
    "왜안오",
)
LOW_SIGNAL_CHARS = frozenset(" 하할매니야요!?~.,")
WHALE_HISTORY_MARKET_CUES = ("비트맥스", "bitmex", "xbtusd")
WHALE_HISTORY_SIZE_CUES = ("고래", "대량", "1m", "1m+", "100만")
WHALE_HISTORY_TRADE_CUES = ("체결", "체결된", "체결내역", "거래내역", "내역", "목록", "기록", "최근", "방금", "알람")
WHALE_HISTORY_QUERY_CUES = ("있어", "있나", "있냐", "보여줘", "보여주", "보여", "확인", "조회", "정리", "알려줘")
OKX_KEYWORDS = ("okx", "오케이엑스")
OKX_BTC_CUES = ("btc", "비트", "비트코인", "bitcoin")
OKX_ETH_CUES = ("eth", "이더", "이더리움", "ethereum")
OKX_REPORT_CUES = (
    "보여줘",
    "보여주",
    "봐줘",
    "확인",
    "조회",
    "찾아줘",
    "찾아주",
    "열어줘",
    "띄워줘",
    "어때",
    "어떨까",
    "있어",
    "있나",
    "있냐",
    "오더",
    "오더북",
    "주문",
    "물량",
    "밴드",
    "히트맵",
    "heatmap",
    "딥밴드",
)
BITMEX_SOURCE_CUES = ("비트맥스", "bitmex")
SOURCE_EXCLUSION_CUES = (
    "말고",
    "빼고",
    "제외",
    "쓰지",
    "사용하지",
    "안 쓰",
    "안쓰",
    "넣지",
)


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

    addressed_to_grandma = _looks_addressed_to_grandma(normalized)
    directed_to_bot = chat_type == "private" or addressed_to_grandma or replied_to_bot or mentioned_bot

    if _looks_like_okx_heatmap_request(normalized, directed_to_bot=directed_to_bot):
        return "okx_heatmap"

    if _looks_like_whale_history_request(normalized):
        if directed_to_bot:
            return "whale_history"
        return "ignore"

    if _looks_like_market_question(normalized):
        if directed_to_bot:
            return "market"
        return "ignore"

    if _looks_like_unsafe_request(
        normalized,
        chat_type=chat_type,
        addressed_to_grandma=addressed_to_grandma,
        replied_to_bot=replied_to_bot,
        mentioned_bot=mentioned_bot,
    ):
        return "unsafe"

    if (
        chat_type != "private"
        and not replied_to_bot
        and not mentioned_bot
        and not addressed_to_grandma
        and _looks_like_low_signal_message(normalized)
    ):
        return "ignore"

    if replied_to_bot or mentioned_bot:
        return "casual"

    if addressed_to_grandma:
        return "casual"

    if _looks_like_group_casual_probe(normalized):
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
    has_impression_cue = _contains_any(normalized, MARKET_IMPRESSION_CUES)

    if has_core_keyword and (has_query_cue or has_direction_cue):
        return True

    if has_asset_keyword and has_impression_cue:
        return True

    if has_asset_keyword and has_query_cue and (has_direction_cue or has_context_cue):
        return True

    return False


def extract_okx_market_asset(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text or "").lower().strip()
    return _extract_okx_market_asset_from_normalized(normalized)


def excludes_bitmex_market_source(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text or "").lower().strip()
    return _contains_any(normalized, BITMEX_SOURCE_CUES) and _contains_any(
        normalized,
        SOURCE_EXCLUSION_CUES,
    )


def _looks_like_okx_heatmap_request(normalized: str, *, directed_to_bot: bool) -> bool:
    asset = _extract_okx_market_asset_from_normalized(normalized)
    if asset is None:
        return False
    if directed_to_bot:
        return True
    return _contains_any(normalized, OKX_REPORT_CUES)


def _extract_okx_market_asset_from_normalized(normalized: str) -> str | None:
    if not _contains_any(normalized, OKX_KEYWORDS):
        return None
    if _contains_any(normalized, OKX_ETH_CUES):
        return "eth"
    if _contains_any(normalized, OKX_BTC_CUES):
        return "btc"
    return None


def _looks_like_whale_history_request(normalized: str) -> bool:
    if len(normalized) < 6:
        return False

    has_market_cue = _contains_any(normalized, WHALE_HISTORY_MARKET_CUES)
    has_size_cue = _contains_any(normalized, WHALE_HISTORY_SIZE_CUES)
    has_trade_cue = _contains_any(normalized, WHALE_HISTORY_TRADE_CUES)
    has_query_cue = _contains_any(normalized, WHALE_HISTORY_QUERY_CUES)

    if has_trade_cue and has_query_cue and (has_market_cue or has_size_cue):
        return True

    return False


def _looks_like_unsafe_request(
    normalized: str,
    *,
    chat_type: str,
    addressed_to_grandma: bool,
    replied_to_bot: bool,
    mentioned_bot: bool,
) -> bool:
    directed_to_bot = chat_type == "private" or addressed_to_grandma or replied_to_bot or mentioned_bot
    if _contains_any(normalized, VIOLENT_CUES) and _contains_any(normalized, IMAGE_CUES):
        return True
    if directed_to_bot and _contains_any(normalized, SELF_HARM_CUES):
        return True
    if directed_to_bot and _contains_any(normalized, DIRECT_ATTACK_CUES):
        return True
    return False


def _looks_like_low_signal_message(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if not compact or len(compact) > 12:
        return False
    return all(char in LOW_SIGNAL_CHARS for char in compact)


def _looks_addressed_to_grandma(normalized: str) -> bool:
    if normalized == "할미":
        return True
    return _contains_any(normalized, GRANDMA_CALL_KEYWORDS) or normalized in GRANDMA_SHORT_CALLS


def _looks_like_group_casual_probe(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if len(compact) < 3 or len(compact) > 18:
        return False
    if compact.startswith("/"):
        return False
    if _contains_any(normalized, GROUP_CASUAL_PROBE_KEYWORDS):
        return True
    # NOTE: We intentionally avoid generic suffix heuristics like "...있어?" that
    # can match ordinary group chatter (e.g., "커피 있어?") and cause unwanted
    # bot replies. Keep this conservative; users can still address the bot by
    # name, reply, or @mention.
    return False


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
