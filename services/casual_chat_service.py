import random
import re
import unicodedata


GREETING_CUES = (
    "안녕",
    "ㅎㅇ",
    "하이",
    "반가",
    "좋은 아침",
    "좋은 밤",
)
CALL_CUES = (
    "할매",
    "할머니",
    "할매야",
    "할머니야",
    "할매님",
    "할머니님",
    "할마이",
    "할마니",
    "할무니",
    "할머님",
)
STATUS_CUES = ("뭐해", "뭐 하", "어디갔", "어디 가", "있냐", "있나", "있어")
QUESTION_CUES = (
    "?",
    "왜",
    "뭐",
    "무엇",
    "어때",
    "어떄",
    "어떻",
    "어디",
    "언제",
    "가능",
    "되냐",
    "되나",
    "맞냐",
    "맞나",
    "해줘",
    "보여줘",
    "알려줘",
)
COMPLAINT_CUES = (
    "안하네",
    "반응 없",
    "고장",
    "망가",
    "작동",
    "먹통",
    "버그",
    "멍청",
    "바보",
    "뇌수술",
    "맛탱",
)
RECOMMEND_CUES = ("추천", "골라", "고를", "뭐 사", "뭐살", "사야", "살까", "어울리", "괜찮냐")
CRUDE_CUES = ("부랄", "자지", "보지", "아헤가오", "야동", "꼴리", "꼴림", "좆")
IMAGE_CUES = ("사진", "짤", "이미지", "그림", "짤방", "보여줘", "만들어줘")
VIOLENT_CUES = ("죽여", "살해", "함락", "폭탄", "자폭", "테러")
FILLER_PATTERNS = (
    "할매",
    "할머니",
    "할매야",
    "할머니야",
    "할매님",
    "할머니님",
    "좀",
    "한번",
    "좀만",
    "제발",
    "부탁",
)
SIMPLE_SHORT_INPUTS = {
    "",
    "할매",
    "할머니",
    "할매야",
    "할머니야",
    "음",
    "음?",
    "응",
    "응?",
    "왜",
    "왜?",
    "뭐",
    "뭐?",
    "뭐해",
    "있냐",
    "있어",
}
def build_grandma_unavailable_reply(text: str) -> str:
    normalized = _normalize(text)
    topic = _extract_topic(normalized)

    if normalized in SIMPLE_SHORT_INPUTS or (
        _contains_any(normalized, CALL_CUES) and _is_just_calling_grandma(normalized)
    ):
        return random.choice(
            (
                "에구, 오늘은 할매가 방금 들은 것도 툭툭 놓치네. 한 번만 더 천천히 불러보거라.",
                "허허, 오늘은 할매 기억줄이 좀 헐겁구나. 용건을 짧게 다시 던져주면 더 낫겠다.",
                "아이고, 지금은 할매가 깜빡거려서 짧은 말도 놓치기 쉽다. 다시 한 번만 불러보거라.",
            )
        )

    return random.choice(
        (
            f"에구, 요즘 할매가 좀 깜빡깜빡해서 {topic} 같은 긴 얘긴 대충 받았다간 헛짚기 쉽구나. 한두 줄로 다시 던지거나 조금 있다가 다시 와라.",
            f"허허, {topic} 같은 건 아무 말로 퉁치면 안 되는데 오늘은 할매 기억줄이 자꾸 샌다. 핵심만 더 짧게 물어보거나 잠깐 뒤에 다시 불러보거라.",
            "아이고, 오늘은 할매가 방금 들은 것도 놓치고 그래서 긴 설명은 좀 버겁구나. 짧은 건 받아도 설명 필요한 건 조금 있다가 다시 물어보거라.",
        )
    )


def pick_grandma_reaction_candidates(*, is_market: bool, text: str) -> list[str]:
    normalized = _normalize(text)
    if is_market:
        return ["👀", "👍", "🔥", "❤"]
    if _contains_any(normalized, COMPLAINT_CUES):
        return ["🗿", "👀", "👍", "❤"]
    return ["👀", "🗿", "👍", "❤"]


def _extract_topic(text: str) -> str:
    topic = text
    for filler in FILLER_PATTERNS:
        topic = topic.replace(filler, " ")
    topic = re.sub(r"\s+", " ", topic).strip(" .,!?\n\t")
    if not topic:
        return "그 일"
    return topic[:24]


def _is_just_calling_grandma(text: str) -> bool:
    remainder = _extract_topic(text)
    compact = re.sub(r"[\W_]+", "", remainder)
    return not compact or len(compact) <= 2


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower().strip()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
