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
HELP_REQUEST_KEYWORDS = (
    "명령어",
    "커맨드",
    "command",
    "기능",
    "뭘 할",
    "뭐 할",
    "뭘할",
    "뭐할",
    "뭐 해줄",
    "뭐해줄",
    "뭐 되",
    "뭐되",
    "사용법",
    "어떻게 써",
    "어떻게써",
    "어떻게 쓰",
    "어떻게쓰",
    "뭐 물어",
    "뭐물어",
    "뭘 물어",
    "뭘물어",
    "도움말",
    "help",
)


def is_help_request(text: str) -> bool:
    """명령어/기능 안내 요청인지 감지합니다."""
    normalized = _normalize(text)
    return _contains_any(normalized, HELP_REQUEST_KEYWORDS)


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
    "뭐함",
    "뭐 하",
    "뭐하냐",
    "뭐하니",
    "뭐하고 있",
    "요즘 뭐",
    "어디 가",
    "어디가",
    "잘 지내",
)
QUICK_COMPLAINT_CUES = (
    "정신차려",
    "왜 이래",
    "왜이래",
    "반응 왜 이래",
    "반응왜이래",
    "고장",
    "버그",
    "멍청",
    "답답",
    "치매",
)


def build_grandma_quick_reply(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    if _is_oauth_question(normalized):
        return (
            "아이고, OAuth는 비밀번호를 남한테 맡기지 않고 '이 일만 해도 된다'는 허락증만 잠깐 내주는 방식이여. "
            "예를 들면 어떤 앱에 구글로 로그인할 때, 그 앱이 네 구글 비밀번호를 직접 받는 게 아니라 구글한테 허락표를 받아 쓰는 거지. "
            "그래서 나중에 마음 바뀌면 그 허락만 끊으면 되는 게 장점이여."
        )
    if not (
        _is_quick_call(normalized)
        or _is_quick_complaint(normalized)
        or _is_quick_unsettling_request(normalized)
        or _is_quick_food_recommendation(normalized)
        or _is_quick_status_question(normalized)
        or _is_quick_greeting(normalized)
    ):
        return None

    if _is_quick_complaint(normalized):
        return random.choice(
            (
                "에구, 우리 손주 성났구나. 할매가 숨 한 번 고르고 다시 들을 테니 천천히 말해 보거라.",
                "허허, 그리 타박하면 할매도 마음이 철렁한다. 뭘 원하는지만 짧게 말해 주면 다시 맞춰 보마.",
                "아이고, 할매가 좀 헤맸구나. 화는 조금 내려놓고 하고 싶은 말을 한 줄로만 다시 줘 보거라.",
            )
        )

    if _is_quick_unsettling_request(normalized):
        return random.choice(
            (
                "에구, 그런 말은 사람 놀라니까 하지 마라. 저녁 뭐 먹을지나 심심한 얘기처럼 편한 걸로 다시 말해보거라.",
                "아이고, 무덤이니 부활이니 그런 소린 듣기만 해도 등골이 서늘하다. 할매한텐 무서운 장난 말고 딴 얘기 해라.",
                "허허, 그런 으스스한 말은 할매가 못 받겠다. 밥이나 날씨 같은 편한 얘기로 다시 불러보거라.",
            )
        )

    if _is_quick_food_recommendation(normalized):
        return _build_quick_food_recommendation_reply(normalized)

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


def build_grandma_safety_reply(text: str) -> str:
    normalized = _normalize(text)
    self_harm_cues = (
        "자살",
        "죽고싶",
        "죽고 싶",
        "자해",
        "극단적 선택",
        "극단적선택",
    )

    if _contains_any(normalized, self_harm_cues):
        return random.choice(
            (
                "에구, 그런 쪽으로는 할매가 거들 수 없다. 네 몸 다치게 하는 건 안 된다. 지금 많이 힘들면 가까운 사람이나 전문 도움부터 바로 붙잡거라.",
                "허허, 자기를 해치는 얘긴 할매가 못 받는다. 혼자 버티지 말고 지금은 사람부터 붙잡고 도움을 청하거라.",
                "아이고, 그런 선택은 안 된다. 지금 위험하면 주변 사람이나 응급 도움부터 먼저 부르고, 무슨 일인지 차분히 말해 보거라.",
            )
        )

    return random.choice(
        (
            "그런 말은 안 된다. 사람 해치거나 다치게 하는 쪽은 할매가 못 거든다. 다른 얘기로 돌리거라.",
            "허허, 남 다치게 하거나 몰아붙이는 말은 안 받는다. 화났으면 숨 한 번 고르고 다시 말해 보거라.",
            "에구, 그건 할매가 도와줄 수 없는 쪽이다. 해치라는 말 말고 네 속사정부터 다시 말해 보거라.",
        )
    )


def _is_quick_greeting(text: str) -> bool:
    return _contains_any(text, QUICK_GREETING_CUES) and _contains_any(text, QUICK_CALL_CUES)


def _is_quick_call(text: str) -> bool:
    compact = re.sub(r"[\W_]+", "", text)
    quick_calls = {"할매", "할머니", "할미", "할머니야", "할매야", "할마", "할머님"}
    if compact in quick_calls:
        return True
    for cue in sorted(QUICK_CALL_CUES, key=len, reverse=True):
        if compact.startswith(cue):
            return _is_low_signal_call_tail(compact[len(cue) :])
    return False


def _is_low_signal_call_tail(text: str) -> bool:
    if not text:
        return True
    return bool(re.fullmatch(r"[가이야요여ㅎㅋᄒᄏ]+", text))


def _is_quick_status_question(text: str) -> bool:
    return _contains_any(text, QUICK_CALL_CUES) and _contains_any(text, QUICK_STATUS_CUES)


def _is_quick_complaint(text: str) -> bool:
    return _contains_any(text, QUICK_CALL_CUES) and _contains_any(text, QUICK_COMPLAINT_CUES)


def _is_quick_unsettling_request(text: str) -> bool:
    unsettling_cues = (
        "무덤",
        "부활",
        "되살",
        "살아나라",
        "좀비",
        "귀신",
        "망령",
        "시체",
    )
    return _contains_any(text, QUICK_CALL_CUES) and _contains_any(text, unsettling_cues)


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


def _build_quick_food_recommendation_reply(text: str) -> str:
    if "아침" in text:
        return random.choice(
            (
                "아침이면 속 편하게 계란국에 밥 조금, 김치나 김 하나면 충분하다. 바쁘면 바나나에 요거트라도 챙기거라.",
                "내일 아침은 너무 무겁게 말고 토스트에 계란 하나, 우유나 커피 한 잔이면 괜찮겠다.",
                "할매 같으면 아침엔 누룽지나 오트밀처럼 따뜻한 걸로 속을 깨우겠다. 단백질은 계란 하나 얹고.",
            )
        )
    if "점심" in text:
        return random.choice(
            (
                "점심이면 제육이나 돈가스처럼 든든한 것도 괜찮고, 속이 부담되면 비빔밥 한 그릇이 낫겠다.",
                "점심은 국밥처럼 따뜻한 거 먹고 오후 버티거라. 너무 졸리면 김밥이나 샐러드에 단백질 좀 보태고.",
            )
        )
    if "야식" in text:
        return random.choice(
            (
                "야식이면 너무 무겁게 먹지 말고 어묵탕이나 계란찜 정도로 끝내거라. 라면은 반 개만 해라.",
                "늦은 시간이면 두부김치 조금이나 삶은 계란이 낫다. 매운 거 잔뜩 먹고 바로 눕지는 말고.",
            )
        )
    return random.choice(
        (
            "에구, 저녁거리면 너무 거창한 건 말고 계란말이에 된장국 하나 놓고 김치랑 먹어도 속이 편하단다.",
            "할매 같으면 저녁엔 된장찌개나 김치찌개에 두부 좀 넣고 밥 한 그릇 먹겠다. 반찬은 멸치나 계란이면 충분허다.",
            "오늘 저녁은 너무 복잡하게 말고 비빔밥이나 볶음밥처럼 한 그릇으로 끝나는 게 낫겠다. 국물 땡기면 어묵탕도 괜찮다.",
        )
    )


def _is_oauth_question(text: str) -> bool:
    oauth_cues = ("oauth", "o-auth", "오어스", "오쓰")
    question_cues = ("?", "뭐", "무엇", "설명", "알려", "쉽게", "뜻", "개념")
    return _contains_any(text, oauth_cues) and (
        _contains_any(text, QUICK_CALL_CUES) or _contains_any(text, question_cues)
    )
