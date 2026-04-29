import os
from typing import Literal

from pydantic import BaseModel, Field

from services.casual_chat_service import build_grandma_quick_reply, is_help_request
from services.message_constraints_service import (
    ConstraintSet,
    extract_message_constraints,
    validate_tool_selection,
)
from services.message_intent_service import (
    MessageIntent,
    classify_message_intent,
    extract_okx_market_asset,
)


RouteAction = Literal["ignore", "quick_reply", "safety_reply", "tool", "llm", "clarify"]
RouteTool = Literal["okx_heatmap", "bitmex", "whale_history"]
RouteAsset = Literal["btc", "eth"]


class RouteDecision(BaseModel):
    intent: MessageIntent
    action: RouteAction
    tool: RouteTool | None = None
    asset: RouteAsset | None = None
    excluded_tools: tuple[RouteTool, ...] = Field(default_factory=tuple)
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    reason: str = ""


def route_message(
    *,
    text: str,
    chat_type: str,
    replied_to_bot: bool = False,
    mentioned_bot: bool = False,
    constraints: ConstraintSet | None = None,
) -> RouteDecision:
    constraints = constraints or extract_message_constraints(text)
    intent = classify_message_intent(
        text=text,
        chat_type=chat_type,
        replied_to_bot=replied_to_bot,
        mentioned_bot=mentioned_bot,
    )

    if intent == "ignore":
        return RouteDecision(
            intent=intent,
            action="ignore",
            constraints=constraints,
            excluded_tools=_route_exclusions(constraints),
            reason="not addressed or low signal",
        )

    if intent == "unsafe":
        return RouteDecision(
            intent=intent,
            action="safety_reply",
            constraints=constraints,
            excluded_tools=_route_exclusions(constraints),
            reason="unsafe request",
        )

    if intent == "okx_heatmap":
        asset = extract_okx_market_asset(text) or "btc"
        violation = validate_tool_selection("okx_heatmap", constraints)
        if violation:
            return _clarify_route(intent=intent, constraints=constraints, reason=violation.reason)
        return RouteDecision(
            intent=intent,
            action="tool",
            tool="okx_heatmap",
            asset=asset,
            constraints=constraints,
            excluded_tools=_route_exclusions(constraints),
            reason="okx heatmap",
        )

    if intent == "whale_history":
        violation = validate_tool_selection("bitmex", constraints)
        if violation:
            return _clarify_route(intent=intent, constraints=constraints, reason=violation.reason)
        return RouteDecision(
            intent=intent,
            action="tool",
            tool="whale_history",
            constraints=constraints,
            excluded_tools=_route_exclusions(constraints),
            reason="whale trade history",
        )

    if intent == "market":
        violation = validate_tool_selection("bitmex", constraints)
        if violation:
            return _clarify_route(intent=intent, constraints=constraints, reason=violation.reason)
        return RouteDecision(
            intent=intent,
            action="tool",
            tool="bitmex",
            constraints=constraints,
            excluded_tools=_route_exclusions(constraints),
            reason="default market tool",
        )

    if intent == "casual":
        if is_help_request(text) or build_grandma_quick_reply(text):
            return RouteDecision(
                intent=intent,
                action="quick_reply",
                constraints=constraints,
                excluded_tools=_route_exclusions(constraints),
                reason="deterministic casual reply",
            )
        return RouteDecision(
            intent=intent,
            action="llm",
            constraints=constraints,
            excluded_tools=_route_exclusions(constraints),
            reason="casual llm reply",
        )

    return RouteDecision(
        intent="ignore",
        action="ignore",
        constraints=constraints,
        excluded_tools=_route_exclusions(constraints),
        reason="unhandled route",
    )


def pydantic_ai_router_enabled() -> bool:
    return os.getenv("PYDANTIC_AI_ROUTER_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


async def route_message_with_pydantic_ai(
    *,
    text: str,
    chat_type: str,
    replied_to_bot: bool = False,
    mentioned_bot: bool = False,
    constraints: ConstraintSet | None = None,
) -> RouteDecision:
    deterministic = route_message(
        text=text,
        chat_type=chat_type,
        replied_to_bot=replied_to_bot,
        mentioned_bot=mentioned_bot,
        constraints=constraints,
    )
    if not pydantic_ai_router_enabled() or deterministic.action != "llm":
        return deterministic

    try:
        from pydantic_ai import Agent
    except ImportError:
        return deterministic

    model_name = os.getenv("PYDANTIC_AI_ROUTER_MODEL", "openai:gpt-5.2")
    agent = Agent(
        model_name,
        output_type=RouteDecision,
        system_prompt=(
            "You route Korean Telegram bot messages. "
            "Return only a validated RouteDecision. "
            "Never select a tool that the user explicitly excluded. "
            "Prefer quick_reply for short deterministic grandma/persona chatter. "
            "Prefer llm only when no tool, safety, or deterministic reply fits."
        ),
    )
    result = await agent.run(
        "Message routing context:\n"
        f"- text: {text!r}\n"
        f"- chat_type: {chat_type!r}\n"
        f"- replied_to_bot: {replied_to_bot}\n"
        f"- mentioned_bot: {mentioned_bot}\n"
        f"- deterministic_route: {deterministic.model_dump()!r}\n"
    )
    return result.output


def _clarify_route(*, intent: MessageIntent, constraints: ConstraintSet, reason: str) -> RouteDecision:
    return RouteDecision(
        intent=intent,
        action="clarify",
        excluded_tools=_route_exclusions(constraints),
        constraints=constraints,
        reason=reason,
    )


def _route_exclusions(constraints: ConstraintSet) -> tuple[RouteTool, ...]:
    return tuple(
        tool
        for tool in constraints.excluded_tools
        if tool in {"bitmex", "okx_heatmap", "whale_history"}
    )
