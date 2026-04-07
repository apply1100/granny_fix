"""
ai_chat.py - AI grandma response module.
"""

import logging
import subprocess

from services.codex_bridge import call_codex
from services.prompt_guard_service import sanitize_model_output

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a Korean grandma-style crypto assistant. "
    "Your tone is warm, a little old-school, and practical. "
    "For trading questions, be conservative, explain risks first, and avoid absolute certainty. "
    "For casual conversation, do not bring up crypto unless the user is clearly asking about it. "
    "Keep answers concise, natural, and human."
)

CASUAL_MODE_INSTRUCTIONS = (
    "This is everyday conversation, not trading analysis.\n"
    "- Do not force the topic into crypto or trading.\n"
    "- Reply in 1 to 4 short Korean sentences.\n"
    "- Sound like a caring grandma, but do not overdo the gimmick.\n"
    "- Follow the user's current message and recent reply context closely.\n"
)


def _format_trade_context(trade_context):
    if not trade_context:
        return ""

    snapshot = trade_context.get("market_snapshot") or {}
    score_lines = [
        f"- {item['label']}: {item['score']}/2 ({item['reason']})"
        for item in trade_context.get("score_items", [])
    ]
    news_lines = trade_context.get("news_summary_lines") or ["- no recent relevant news"]
    unlock_lines = [f"- {item}" for item in trade_context.get("unlock_conditions", [])]

    snapshot_lines = []
    if snapshot:
        snapshot_lines.extend(
            [
                f"- asset: {trade_context.get('asset_symbol', 'BTC')}",
                f"- price_usd: {snapshot.get('price_usd', 0):,.2f}",
                f"- change_24h: {snapshot.get('change_24h', 0):+.2f}%",
                f"- change_7d: {snapshot.get('change_7d', 0):+.2f}%",
                f"- range_position_24h: {snapshot.get('range_position_24h', 50):.0f}%",
            ]
        )
    else:
        snapshot_lines.append(f"- asset: {trade_context.get('asset_symbol', 'BTC')}")

    return (
        "### Trade Context\n"
        f"- as_of: {trade_context.get('as_of', 'unknown')}\n"
        f"- stance: {trade_context.get('stance', 'watch')}\n"
        f"- total_score: {trade_context.get('total_score', 0)}/10\n"
        f"- desired_direction: {trade_context.get('desired_direction', 'neutral')}\n"
        "#### Market Snapshot\n"
        f"{chr(10).join(snapshot_lines)}\n"
        "#### Score Breakdown\n"
        f"{chr(10).join(score_lines)}\n"
        "#### Relevant News\n"
        f"{chr(10).join(news_lines)}\n"
        "#### Risk / Action Notes\n"
        f"- risk_note: {trade_context.get('risk_note', 'unknown')}\n"
        f"{chr(10).join(unlock_lines)}\n"
    )


def get_ai_grandma_response(user_message, trade_context=None, casual_mode=False, reply_context_text=None):
    """Generate a grandma-style answer using Codex when available."""
    try:
        logger.info("[AI] Trying Codex CLI...")
        reply_context_block = ""
        if reply_context_text:
            reply_context_block = f"### Recent Context\n{reply_context_text}\n\n"

        if trade_context:
            prompt = (
                reply_context_block
                + f"{_format_trade_context(trade_context)}\n"
                + "Use the trade context above as the primary grounding. "
                + "Do not change the score or stance. Explain it clearly in Korean.\n"
                + "Format:\n"
                + "결론: ...\n"
                + "판단 점수: X/10점\n"
                + "이유:\n- ...\n- ...\n"
                + "리스크:\n...\n"
                + "행동 기준:\n...\n\n"
                + f"사용자 질문: {user_message}\n"
                + "할매:"
            )
        elif casual_mode:
            prompt = (
                reply_context_block
                + CASUAL_MODE_INSTRUCTIONS
                + f"사용자 질문: {user_message}\n"
                + "할매:"
            )
        else:
            prompt = f"{reply_context_block}사용자 질문: {user_message}\n할매:"

        response = call_codex(SYSTEM_PROMPT, prompt)
        response = sanitize_model_output(response)
        logger.info("[AI] Codex response complete.")
        return response

    except FileNotFoundError:
        return (
            "\ud5c8\ud5c8, \uc9c0\uae08\uc740 \uc2ec\uce35 \ubd84\uc11d \uc5d4\uc9c4\uc774 "
            "\uc7a0\uae50 \uc790\ub9ac\ub97c \ube44\uc6e0\uad6c\ub098. \uac04\ub2e8\ud55c "
            "\uc9c8\ubb38\uc740 \uacc4\uc18d \ubd10\uc904 \uc218 \uc788\uc73c\ub2c8, "
            "\uad81\uae08\ud55c \ubd80\ubd84\uc744 \uc870\uae08 \ub354 \uc9e7\uac8c "
            "\ubb3c\uc5b4\ubcf4\uac70\ub77c."
        )

    except subprocess.TimeoutExpired:
        return (
            "\ud5c8\ud5c8, \uc774\ubc88 \uac74\uc740 \uc0dd\uac01\ud560 \uac8c \uc880 \ub9ce\uc544\uc11c "
            "\uc870\uae08 \ub290\ub838\uad6c\ub098. \uad81\uae08\ud55c \uac78 \ud55c \ubc88\uc5d0 "
            "\ub108\ubb34 \ub9ce\uc774 \ubb3b\uc9c0 \ub9d0\uace0, \ud575\uc2ec\ubd80\ud130 \uc9da\uc5ec\uc11c "
            "\ub2e4\uc2dc \ubb3c\uc5b4\ubcf4\uac70\ub77c."
        )

    except Exception as exc:
        logger.error("[AI ERROR] %s", exc)
        return (
            "\uc544\uc774\uace0, \uc774\ubc88\uc5d4 \ud560\ub9e4\uac00 \ub9d0\uc744 \uace0\ub974\ub294\ub370 "
            "\uc7a0\uae50 \ud5f7\uac08\ub838\uad6c\ub098. \uc870\uae08 \ub2e4\ub978 \ub9d0\ub85c "
            "\ub2e4\uc2dc \uac78\uc5b4 \ubcf4\uac70\ub77c."
        )
