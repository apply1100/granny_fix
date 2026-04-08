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


QUICK_GREETING_CUES = (
    "안녕",
    "하이",
    "반가",
    "잘 있었",
)
QUICK_CALL_CUES = (
    "할매",
    "할머니",
    "할머니야",
    "할매야",
    "할마",
    "할머님",
)
QUICK_STATUS_CUES = (
    "뭐해",
    "뭐 하",
    "뭐하고 있",
    "요즘 뭐",
    "어디 가",
    "어디가",
    "잘 지내",
)


def build_grandma_quick_reply(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    if _is_quick_food_recommendation(normalized):
        return random.choice(
            (
                "에구, 저녁거리면 너무 거창한 건 말고 계란말이에 된장국 하나 놓고 김치랑 먹어도 속이 편하단다.",
                "할매 같으면 저녁엔 된장찌개나 김치찌개에 두부 좀 넣고 밥 한 그릇 먹겠다. 반찬은 멸치나 계란이면 충분허다.",
                "오늘 저녁은 너무 복잡하게 말고 비빔밥이나 볶음밥처럼 한 그릇으로 끝나는 게 낫겠다. 국물 땡기면 어묵탕도 괜찮다.",
            )
        )

    if _is_quick_status_question(normalized):
        return random.choice(
            (
                "에구, 할매는 방금 밥솥 눌러놓고 네가 또 뭘 하고 사나 생각하고 있었지. 너는 밥은 먹었느냐.",
                "허허, 나는 된장국 불 올려두고 쉬고 있었지. 네가 부르니 얼른 왔다.",
                "요즘이야 뭐, 허리 두드리고 동네 소식 듣고 그러지. 너는 오늘 뭐 했느냐.",
            )
        )

    if _is_quick_greeting(normalized):
        return random.choice(
            (
                "어이구, 우리 손주 왔느냐. 할매 여기 있다. 하고 싶은 말 있으면 해 보거라.",
                "허허, 왔구나. 할매 반갑다. 오늘은 무슨 얘기 해 줄까.",
                "에구, 부르니 반갑구나. 밥은 먹었느냐.",
            )
        )

    if _is_quick_call(normalized):
        return random.choice(
            (
                "왜 그러느냐, 할매 여기 있다.",
                "응, 불렀느냐. 할매 왔다.",
                "허허, 여기 있지. 무슨 일 있느냐.",
            )
        )

    return None


def _is_quick_greeting(text: str) -> bool:
    return _contains_any(text, QUICK_GREETING_CUES) and _contains_any(text, QUICK_CALL_CUES)


def _is_quick_call(text: str) -> bool:
    compact = re.sub(r"[\W_]+", "", text)
    if compact in {"할매", "할머니", "할머니야", "할매야", "할마", "할머님"}:
        return True
    return _contains_any(text, QUICK_CALL_CUES) and len(compact) <= 6


def _is_quick_status_question(text: str) -> bool:
    return _contains_any(text, QUICK_CALL_CUES) and _contains_any(text, QUICK_STATUS_CUES)


def _is_quick_food_recommendation(text: str) -> bool:
    food_cues = (
        "메뉴",
        "밥",
        "먹을거",
        "먹을 거",
        "먹을게",
        "먹을 게",
        "저녁",
        "점심",
        "아침",
        "야식",
        "반찬",
    )
    return (
        _contains_any(text, QUICK_CALL_CUES)
        and _contains_any(text, food_cues)
        and _contains_any(text, RECOMMEND_CUES)
    )
