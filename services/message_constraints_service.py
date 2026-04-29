import unicodedata
from typing import Literal

from pydantic import BaseModel, Field


ToolName = Literal["bitmex", "okx_heatmap", "kiyotaka_capture"]
ReplyMode = Literal["text_only", "brief"]


class ConstraintSet(BaseModel):
    excluded_tools: tuple[ToolName, ...] = Field(default_factory=tuple)
    reply_modes: tuple[ReplyMode, ...] = Field(default_factory=tuple)
    reasons: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def wants_text_only(self) -> bool:
        return "text_only" in self.reply_modes or "kiyotaka_capture" in self.excluded_tools


class ConstraintViolation(BaseModel):
    kind: Literal["tool_excluded", "reply_mentions_excluded_tool"]
    tool: ToolName
    reason: str


TOOL_ALIASES: dict[ToolName, tuple[str, ...]] = {
    "bitmex": ("비트맥스", "bitmex", "비맥"),
    "okx_heatmap": ("okx", "오케이엑스", "오케엑스", "오켁스"),
    "kiyotaka_capture": ("키요타카", "kiyotaka", "캡처", "캡쳐", "스크린샷", "사진", "이미지", "브라우저"),
}

EXCLUSION_CUES = (
    "말고",
    "빼고",
    "빼줘",
    "빼",
    "제외",
    "쓰지",
    "사용하지",
    "안 쓰",
    "안쓰",
    "넣지",
    "하지 말",
)
TEXT_ONLY_CUES = (
    "텍스트로",
    "글로",
    "말로만",
    "말로 해",
    "말로 설명",
    "대답만",
    "답만",
    "사진 말고",
    "캡처 말고",
    "캡쳐 말고",
    "스크린샷 말고",
    "이미지 말고",
)
BRIEF_CUES = ("짧게", "간단히", "요약", "한줄", "한 줄")
EXPLANATORY_EXCLUSION_CUES = EXCLUSION_CUES + ("못 쓰", "쓸 수 없", "요청대로", "제외했")


def extract_message_constraints(text: str) -> ConstraintSet:
    normalized = _normalize(text)
    excluded_tools: list[ToolName] = []
    reply_modes: list[ReplyMode] = []
    reasons: list[str] = []

    for tool, aliases in TOOL_ALIASES.items():
        if _has_exclusion_for_tool(normalized, aliases):
            excluded_tools.append(tool)
            reasons.append(f"excluded:{tool}")

    if _contains_any(normalized, TEXT_ONLY_CUES):
        reply_modes.append("text_only")
        excluded_tools.append("kiyotaka_capture")
        reasons.append("reply_mode:text_only")

    if _contains_any(normalized, BRIEF_CUES):
        reply_modes.append("brief")
        reasons.append("reply_mode:brief")

    return ConstraintSet(
        excluded_tools=_dedupe_tuple(excluded_tools),
        reply_modes=_dedupe_tuple(reply_modes),
        reasons=_dedupe_tuple(reasons),
    )


def validate_tool_selection(tool: ToolName | None, constraints: ConstraintSet) -> ConstraintViolation | None:
    if tool and tool in constraints.excluded_tools:
        return ConstraintViolation(
            kind="tool_excluded",
            tool=tool,
            reason=f"user excluded {tool}",
        )
    return None


def find_reply_constraint_violation(
    reply: str,
    constraints: ConstraintSet,
    *,
    selected_tool: ToolName | None = None,
) -> ConstraintViolation | None:
    tool_violation = validate_tool_selection(selected_tool, constraints)
    if tool_violation:
        return tool_violation

    normalized = _normalize(reply)
    for tool in constraints.excluded_tools:
        aliases = TOOL_ALIASES[tool]
        if _contains_any(normalized, aliases) and not _mentions_exclusion_context(normalized, aliases):
            return ConstraintViolation(
                kind="reply_mentions_excluded_tool",
                tool=tool,
                reason=f"reply mentions excluded {tool}",
            )
    return None


def build_constraint_violation_reply(violation: ConstraintViolation) -> str:
    if violation.tool == "bitmex":
        return "알겠다. 비트맥스 기준은 빼고 답해야 하는데 그 조건을 어긴 답변이 섞일 뻔했다. OKX 기준으로 다시 물어보면 그쪽으로 보겠다."
    if violation.tool == "kiyotaka_capture":
        return "알겠다. 사진이나 캡처는 빼고 텍스트로만 답해야 하는 요청이었다. 텍스트 기준으로 다시 정리해보겠다."
    return "알겠다. 방금 답변이 네가 뺀 기준을 건드릴 뻔했다. 제외 조건을 지키도록 다시 정리하겠다."


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower().strip()


def _has_exclusion_for_tool(text: str, aliases: tuple[str, ...]) -> bool:
    for alias in aliases:
        start = text.find(alias)
        while start != -1:
            window = text[max(0, start - 16) : start + len(alias) + 24]
            if _contains_any(window, EXCLUSION_CUES):
                return True
            start = text.find(alias, start + len(alias))
    return False


def _mentions_exclusion_context(text: str, aliases: tuple[str, ...]) -> bool:
    for alias in aliases:
        start = text.find(alias)
        while start != -1:
            window = text[max(0, start - 20) : start + len(alias) + 28]
            if _contains_any(window, EXPLANATORY_EXCLUSION_CUES):
                return True
            start = text.find(alias, start + len(alias))
    return False


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _dedupe_tuple(values: list) -> tuple:
    return tuple(dict.fromkeys(values))
