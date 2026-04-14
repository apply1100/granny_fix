import asyncio
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramConflictError, TelegramForbiddenError
from aiogram.types import BotCommand, Message, ReactionTypeEmoji
from dotenv import load_dotenv
from services.bitmex_watcher_service import (
    BitmexWatcherError,
    BitmexWhaleTrade,
    add_subscription,
    auto_register_on_market_interaction_enabled,
    ensure_subscription_for_market_interaction,
    fetch_new_whale_trades,
    format_trade_alert_header,
    get_poll_interval_seconds,
    get_recent_whale_trades_report,
    get_trade_delay_seconds,
    get_trade_threshold,
    format_trade_threshold_label,
    has_configured_subscription,
    has_runtime_subscription,
    is_delayed_trade_alert,
    list_subscriptions,
    remove_subscription,
)
from services.casual_chat_service import (
    build_grandma_quick_reply,
    build_grandma_safety_reply,
    build_grandma_unavailable_reply,
    pick_grandma_reaction_candidates,
)
from services.message_intent_service import classify_message_intent
from services.memory_service import memory_service
from services.gemini_casual_service import get_grandma_casual_reply
from services.coinalyze_service import (
    CoinalyzeError,
    get_bitmex_whale_grandma_reply,
    get_bitmex_whale_report,
)

load_dotenv()
RUNTIME_LOG_PATH = Path(__file__).resolve().parent / "memory" / "bot.runtime.log"
RUNTIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(RUNTIME_LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
BOT_USERNAME = ""
BOT_USER_ID: int | None = None

router = Router()

BOT_COMMANDS = [
    BotCommand(command="trackon", description="BitMEX 1M+ auto alerts on"),
    BotCommand(command="trackoff", description="BitMEX 1M+ auto alerts off"),
    BotCommand(command="trackstatus", description="Show whale tracking status"),
    BotCommand(command="testalert", description="Send a fake whale alert"),
    BotCommand(command="bitmexwhale", description="Analyze BitMEX whale direction"),
    BotCommand(command="coinalyze", description="Show Coinalyze alert setup"),
    BotCommand(command="help", description="Show command help"),
]

HELP_TEXT = (
    "사용 가능한 명령어\n"
    "/ping - 봇 응답 확인\n"
    "/chatid - 현재 chat_id 확인\n"
    "/coinalyze - BitMEX 대량 체결 알림 세팅 안내\n"
    "/bitmexwhale - OI/CVD 기준 BitMEX 롱숏 추정\n"
    "/watchwhales - BitMEX 1M+ 자동 알림 시작\n"
    "/unwatchwhales - BitMEX 1M+ 자동 알림 중지\n"
    "/trackon - BitMEX 1M+ 자동 알림 시작\n"
    "/trackoff - BitMEX 1M+ 자동 알림 중지\n"
    "/trackstatus - 현재 채팅방 자동 알림 상태 확인\n"
    "/testalert - 가짜 1M 알림 테스트\n"
    "/testwhalealert - 현재 채팅방으로 가짜 알림 테스트\n\n"
    "시장 질문은 그냥 문장으로 물어봐도 됩니다.\n"
    "예: 지금 롱이냐 숏이냐 / 비트맥스 누가 때리냐 / OI 붙었냐"
)

COINALYZE_ALERT_TEXT = (
    "BitMEX 대량 체결 체크용 Coinalyze 세팅\n\n"
    "1. Coinalyze에서 BTC / USD Perp BitMEX 차트를 엽니다.\n"
    "2. Alerts 또는 종 모양 메뉴를 누릅니다.\n"
    "3. 조건을 trade size greater than 으로 고릅니다.\n"
    "4. 값은 1000000으로 넣습니다.\n"
    "5. 저장하고 텔레그램 알림을 연결합니다.\n\n"
    "빠른 체크 포인트\n"
    "- 자정 언저리처럼 수급이 붙는 시간대에 특히 유용합니다.\n"
    "- 이 알림이 울릴 때 가격 근처로 라지가 달려드는지 쓱 확인하면 됩니다.\n\n"
    "참고 링크\n"
    "- Alerts: https://coinalyze.net/alerts/\n"
    "- BTC/USD Perp BitMEX: https://coinalyze.net/bitcoin/usd/bitmex/btcusd_perp/price-chart-live/\n\n"
    "메모: Coinalyze UI 문구는 조금 바뀔 수 있지만 핵심 조합은 "
    "BitMEX + BTC/USD Perp + trade size greater than + 1000000 입니다."
)

BITMEX_WHALE_HELP_TEXT = (
    "BitMEX 고래 포지션 추정은 Coinalyze API가 필요합니다.\n"
    ".env에 COINALYZE_API_KEY를 넣은 뒤 /bitmexwhale 를 보내면,\n"
    "최근 5분 OI와 최근 15분 매수우위(CVD 대용)·청산·펀딩을 같이 읽어서\n"
    "신규 롱/신규 숏/롱 정리/숏 커버링 중 어디에 가까운지 추정해 드립니다."
)

WATCH_WHALES_TEXT = (
    "BitMEX 대형 체결 자동 알림을 등록했습니다.\n"
    f"- 기준 체결: {get_trade_threshold():,} contracts\n"
    f"- 체크 주기: {get_poll_interval_seconds()}초\n"
    "- 이 채팅방으로 대형 체결이 나오면 먼저 보내드릴게요.\n"
    "- 봇이 실행 중이어야 자동 알림이 동작합니다."
)

UNWATCH_WHALES_TEXT = "BitMEX 대형 체결 자동 알림을 이 채팅방에서 해제했습니다."
MARKET_QUESTION_HINT = (
    "시장 질문이면 그냥 말로 물어보거라.\n"
    "예: 지금 롱이냐 숏이냐 / 비트맥스 누가 때리냐 / OI 붙었냐"
)
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
MARKET_ASSET_KEYWORDS = ("btc", "xbt", "비트코인", "bitcoin", "이더", "ethereum", "eth")
MARKET_QUERY_CUES = (
    "?",
    "지금",
    "어때",
    "어떄",
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
GRANDMA_FOLLOW_UP_CUES = (
    "음",
    "응",
    "왜",
    "왜?",
    "음?",
    "응?",
    "뭐",
    "뭐해",
    "어디갔",
    "있냐",
    "있나",
    "안하네",
    "반응",
)
GENERAL_CHAT_CUES = (
    "?",
    "왜",
    "뭐",
    "어때",
    "어떻게",
    "언제",
    "가능",
    "되냐",
    "되나",
    "해줘",
    "보여줘",
    "알려줘",
    "안하네",
    "작동",
    "고장",
    "망가",
    "버그",
    "뇌수술",
)
GRANDMA_SHORT_CALLS = (
    "할매",
    "할머니",
    "할미",
    "할망",
    "음",
    "음?",
    "응",
    "응?",
    "왜",
    "왜?",
    "뭐",
    "뭐?",
)


@router.message(Command("start"))
async def start(message: Message):
    await _safe_answer(message, HELP_TEXT)


@router.message(Command("help"))
async def help_command(message: Message):
    await _safe_answer(message, HELP_TEXT)


@router.message(Command("ping"))
async def ping(message: Message):
    await _safe_answer(message, "pong")


@router.message(Command("chatid"))
async def chatid(message: Message):
    await _safe_answer(message, f"chat_id: {message.chat.id}")


@router.message(Command("coinalyze"))
async def coinalyze(message: Message):
    await _maybe_auto_register_market_chat(message)
    await _safe_answer(message, COINALYZE_ALERT_TEXT)


@router.message(Command("bitmexwhale"))
async def bitmexwhale(message: Message):
    await _maybe_auto_register_market_chat(message)
    if not await _safe_answer(message, "BitMEX 고래 포지션 추정 중..."):
        return

    try:
        report = await asyncio.to_thread(get_bitmex_whale_report)
    except CoinalyzeError as exc:
        await _safe_answer(message, f"{BITMEX_WHALE_HELP_TEXT}\n\n사유: {exc}")
        return
    except Exception:
        await _safe_answer(message, "BitMEX 고래 추정 중 예기치 않은 오류가 났습니다. 잠시 뒤 다시 시도해 주세요.")
        return

    await _safe_answer(message, report)


@router.message(Command("watchwhales"))
@router.message(Command("trackon"))
async def watchwhales(message: Message):
    added = await asyncio.to_thread(add_subscription, message.chat.id)
    if added:
        await _safe_answer(message, WATCH_WHALES_TEXT)
        return

    configured = await asyncio.to_thread(has_configured_subscription, message.chat.id)
    if configured:
        await _safe_answer(
            message,
            "이 채팅방은 Railway 고정 등록으로 이미 BitMEX 자동 알림을 받고 있습니다.\n"
            "- 재배포 후에도 유지됩니다.\n"
            "- 현재 상태는 /trackstatus 로 다시 확인할 수 있습니다."
        )
        return

    await _safe_answer(message, "이미 이 채팅방은 BitMEX 대형 체결 자동 알림을 받고 있습니다.")


@router.message(Command("unwatchwhales"))
@router.message(Command("trackoff"))
async def unwatchwhales(message: Message):
    removed = await asyncio.to_thread(remove_subscription, message.chat.id)
    if removed:
        configured = await asyncio.to_thread(has_configured_subscription, message.chat.id)
        if configured:
            await _safe_answer(
                message,
                "이 채팅방의 수동 등록은 해제했습니다.\n"
                "- 다만 Railway 환경변수 BITMEX_ALERT_CHAT_IDS 에도 들어 있어서 알림은 계속 올 수 있습니다.\n"
                "- 완전히 끄려면 그 변수에서 현재 chat_id를 빼야 합니다."
            )
            return

        await _safe_answer(message, UNWATCH_WHALES_TEXT)
        return

    configured = await asyncio.to_thread(has_configured_subscription, message.chat.id)
    if configured:
        await _safe_answer(
            message,
            "이 채팅방은 Railway 환경변수 BITMEX_ALERT_CHAT_IDS 로 고정 등록돼 있습니다.\n"
            "- 현재 chat_id는 /chatid 로 볼 수 있습니다.\n"
            "- 완전히 끄려면 Railway 변수에서 그 chat_id를 빼 주세요."
        )
        return

    await _safe_answer(message, "이 채팅방은 아직 자동 알림 등록이 없습니다.")


@router.message(Command("trackstatus"))
async def trackstatus(message: Message):
    await _maybe_auto_register_market_chat(message)
    runtime_enabled = await asyncio.to_thread(has_runtime_subscription, message.chat.id)
    configured_enabled = await asyncio.to_thread(has_configured_subscription, message.chat.id)
    enabled = runtime_enabled or configured_enabled
    source = _describe_subscription_source(runtime_enabled, configured_enabled)
    coinalyze_ready = bool(os.environ.get("COINALYZE_API_KEY", "").strip())
    auto_register_enabled = await asyncio.to_thread(auto_register_on_market_interaction_enabled)

    lines = [
        "BitMEX 자동 알림 상태",
        f"- 현재 채팅: {'켜짐' if enabled else '꺼짐'}",
        f"- 등록 방식: {source}",
        f"- 기준 체결: {get_trade_threshold():,} contracts ({format_trade_threshold_label()})",
        f"- 체크 주기: {get_poll_interval_seconds()}초",
        f"- Coinalyze 추정: {'가능' if coinalyze_ready else 'API 키 없음'}",
        f"- 자동 재등록: {'켜짐' if auto_register_enabled else '꺼짐'}",
        f"- chat_id: {message.chat.id}",
    ]

    if configured_enabled:
        lines.append("- 메모: Railway 환경변수에 등록돼 있어 재배포 후에도 유지됩니다.")
    elif enabled and auto_register_enabled:
        lines.append("- 메모: 현재는 런타임 등록입니다. 재배포 후에도 /trackstatus, /bitmexwhale, /coinalyze 또는 BitMEX 질문이 오면 자동으로 다시 붙습니다.")
    elif enabled:
        lines.append("- 메모: 현재는 런타임 등록이라 재배포 후에는 다시 /trackon 이 필요할 수 있습니다.")
    elif auto_register_enabled:
        lines.append("- 메모: 아직 꺼져 있어도 /trackstatus, /bitmexwhale, /coinalyze 또는 BitMEX 질문이 오면 자동으로 켜집니다.")
    else:
        lines.append("- 메모: 자동 알림을 켜려면 /trackon 을 보내면 됩니다.")

    await _safe_answer(message, "\n".join(lines))


@router.message(Command("testwhalealert"))
@router.message(Command("testalert"))
async def testwhalealert(message: Message):
    await _maybe_auto_register_market_chat(message)
    fake_trade = BitmexWhaleTrade(
        trade_id="test-alert",
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        side="Buy",
        size=get_trade_threshold(),
        price=69999.0,
        symbol="XBTUSD",
    )
    threshold_label = format_trade_threshold_label()
    header = format_trade_alert_header(fake_trade).replace(
        f"BitMEX {threshold_label} 자동 알림",
        f"BitMEX {threshold_label} 테스트 알림",
        1,
    )
    report = (
        "BitMEX 고래 포지션 추정\n"
        "- 추정: 테스트 알림입니다\n"
        "- 신뢰도: 테스트\n"
        "- 한줄 요약: 실제 체결이 아니라 자동 알림 경로 확인용입니다.\n"
        "- 메모: 실전에서는 여기에 OI/CVD/청산/펀딩 기반 추정이 붙습니다."
    )
    await _safe_answer(message, f"{header}\n\n{report}")


@router.message(F.text)
async def market_chat(message: Message):
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    reply_to_message = getattr(message, "reply_to_message", None)
    replied_to_bot = bool(
        reply_to_message and getattr(getattr(reply_to_message, "from_user", None), "is_bot", False)
    )
    mentioned_bot = _is_explicit_bot_mention(message)
    intent = classify_message_intent(
        text=text,
        chat_type=str(getattr(message.chat, "type", "")),
        replied_to_bot=replied_to_bot,
        mentioned_bot=mentioned_bot,
    )
    logger.info(
        "[Incoming Text] chat_id=%s chat_type=%s replied_to_bot=%s mentioned_bot=%s intent=%s text=%r",
        message.chat.id,
        getattr(message.chat, "type", ""),
        replied_to_bot,
        mentioned_bot,
        intent,
        text[:200],
    )

    if intent == "whale_history":
        await _maybe_auto_register_market_chat(message)
        await _acknowledge_message(message, is_market=True)
        try:
            report = await asyncio.to_thread(get_recent_whale_trades_report)
        except BitmexWatcherError as exc:
            await _safe_answer(message, f"최근 BitMEX 고래 체결 내역을 가져오지 못했습니다.\n\n사유: {exc}")
            return
        except Exception:
            await _safe_answer(message, "BitMEX 체결 내역 정리 중에 잠깐 꼬였구나. 조금 있다가 다시 물어보거라.")
            return

        await _safe_answer(message, report)
        return

    if intent == "market":
        await _maybe_auto_register_market_chat(message)
        await _acknowledge_message(message, is_market=True)
        if not await _safe_answer(message, "할매가 비트맥스 흐름 보고 오는 중이구나..."):
            return
        try:
            reply = await asyncio.to_thread(get_bitmex_whale_grandma_reply, text)
        except CoinalyzeError as exc:
            await _safe_answer(message, f"{BITMEX_WHALE_HELP_TEXT}\n\n사유: {exc}")
            return
        except Exception:
            await _safe_answer(message, "시장 흐름 읽는 중에 잠깐 헷갈렸구나. 조금 있다가 다시 물어보거라.")
            return

        await _safe_answer(message, reply)
        return

    if intent == "unsafe":
        await _acknowledge_message(message, is_market=False)
        await _safe_answer(message, build_grandma_safety_reply(text))
        return

    if intent == "casual":
        await _acknowledge_message(message, is_market=False)

        addressed_quick_reply = _build_addressed_quick_reply(
            text=text,
            replied_to_bot=replied_to_bot,
            mentioned_bot=mentioned_bot,
        )
        if addressed_quick_reply:
            await _safe_answer(message, addressed_quick_reply)
            return

        try:
            chat_id = message.chat.id
            memory_service.add_message(chat_id, "user", text)
            history = memory_service.get_history(chat_id)[:-1]
            reply = await get_grandma_casual_reply(text, history)
            memory_service.add_message(chat_id, "assistant", reply)
            await _safe_answer(message, reply)
        except Exception:
            logger.exception(
                "[Casual Reply] failed chat_id=%s replied_to_bot=%s mentioned_bot=%s text=%r",
                message.chat.id,
                replied_to_bot,
                mentioned_bot,
                text[:200],
            )
            await _safe_answer(message, build_grandma_unavailable_reply(text))
        return


async def run_bitmex_whale_watcher(bot: Bot):
    while True:
        try:
            chat_ids = await asyncio.to_thread(list_subscriptions)
            if chat_ids:
                new_trades = await asyncio.to_thread(fetch_new_whale_trades)
                for trade in new_trades:
                    header = format_trade_alert_header(trade)
                    delay_seconds = await asyncio.to_thread(get_trade_delay_seconds, trade)
                    delayed = await asyncio.to_thread(is_delayed_trade_alert, trade)
                    try:
                        report = await asyncio.to_thread(get_bitmex_whale_report)
                    except CoinalyzeError as exc:
                        report = f"Coinalyze 분석 실패: {exc}"

                    alert_text = f"{header}\n\n{report}"
                    for chat_id in chat_ids:
                        try:
                            await bot.send_message(chat_id, alert_text)
                            logger.info(
                                f"[BitMEX Watcher] alert sent trade_id={trade.trade_id} "
                                f"chat_id={chat_id} local_time='{trade.local_time}' "
                                f"side={trade.side} size={trade.size} symbol={trade.symbol} "
                                f"delayed={delayed} delay_seconds={delay_seconds}"
                            )
                        except TelegramForbiddenError as exc:
                            await _cleanup_failed_runtime_subscription(chat_id)
                            logger.error(f"[BitMEX Watcher] send forbidden for chat {chat_id}: {exc}")
                        except TelegramBadRequest as exc:
                            if _is_terminal_chat_error(exc):
                                await _cleanup_failed_runtime_subscription(chat_id)
                            logger.error(f"[BitMEX Watcher] send bad request for chat {chat_id}: {exc}")
                        except Exception:
                            logger.exception(f"[BitMEX Watcher] send failed for chat {chat_id}")
        except BitmexWatcherError as exc:
            logger.error(f"[BitMEX Watcher] {exc}")
        except Exception:
            logger.exception(f"[BitMEX Watcher] unexpected error")

        await asyncio.sleep(get_poll_interval_seconds())


async def register_bot_commands(bot: Bot):
    global BOT_USERNAME, BOT_USER_ID
    await bot.set_my_commands(BOT_COMMANDS)
    me = await bot.get_me()
    BOT_USERNAME = (me.username or "").lower()
    BOT_USER_ID = me.id


async def _cleanup_failed_runtime_subscription(chat_id: int) -> None:
    if await asyncio.to_thread(has_runtime_subscription, chat_id):
        await asyncio.to_thread(remove_subscription, chat_id)


async def _maybe_auto_register_market_chat(message: Message) -> None:
    added = await asyncio.to_thread(ensure_subscription_for_market_interaction, message.chat.id)
    if added:
        logger.info(f"[BitMEX Watcher] auto-registered chat {message.chat.id} from market interaction")


def _is_terminal_chat_error(exc: TelegramBadRequest) -> bool:
    message = str(exc).lower()
    terminals = ["chat not found", "user is deactivated", "not enough rights", "bot was kicked", "bot was blocked"]
    return any(t in message for t in terminals)


def _describe_subscription_source(runtime_enabled: bool, configured_enabled: bool) -> str:
    if runtime_enabled and configured_enabled:
        return "수동 등록 + Railway 고정 등록"
    if configured_enabled:
        return "Railway 고정 등록"
    if runtime_enabled:
        return "수동 등록"
    return "미등록"


def _looks_like_market_question(text: str) -> bool:
    return classify_message_intent(
        text=text,
        chat_type="private",
        replied_to_bot=False,
        mentioned_bot=False,
    ) in {"market", "whale_history"}


def _looks_like_casual_chat(message: Message) -> bool:
    reply_to_message = getattr(message, "reply_to_message", None)
    replied_to_bot = bool(
        reply_to_message and getattr(getattr(reply_to_message, "from_user", None), "is_bot", False)
    )
    mentioned_bot = _is_explicit_bot_mention(message)
    return classify_message_intent(
        text=message.text or "",
        chat_type=str(getattr(message.chat, "type", "")),
        replied_to_bot=replied_to_bot,
        mentioned_bot=mentioned_bot,
    ) in {"casual", "unsafe"}


async def _acknowledge_message(message: Message, *, is_market: bool) -> None:
    reaction_candidates = pick_grandma_reaction_candidates(is_market=is_market, text=message.text or "")
    await _try_set_grandma_reaction(message, reaction_candidates=reaction_candidates)
    await _try_send_typing(message)


async def _safe_answer(message: Message, text: str) -> bool:
    try:
        await message.answer(text)
        return True
    except TelegramForbiddenError as exc:
        await _cleanup_failed_runtime_subscription(message.chat.id)
        logger.error("[Bot Reply] send forbidden for chat %s: %s", message.chat.id, exc)
        return False
    except TelegramBadRequest as exc:
        if _is_terminal_chat_error(exc):
            await _cleanup_failed_runtime_subscription(message.chat.id)
            logger.error("[Bot Reply] terminal send error for chat %s: %s", message.chat.id, exc)
            return False
        logger.error("[Bot Reply] send bad request for chat %s: %s", message.chat.id, exc)
        return False


async def _try_set_grandma_reaction(message: Message, *, reaction_candidates: list[str]) -> bool:
    last_error: Exception | None = None
    for emoji in reaction_candidates:
        try:
            await message.bot.set_message_reaction(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
                is_big=False,
            )
            return True
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        logger.error(f"[Grandma Reaction] failed for chat {message.chat.id}, message {message.message_id}: {last_error}")
    return False


async def _try_send_typing(message: Message) -> None:
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:
        return


def _build_reply_context_text(reply_to_message: Message | None) -> str | None:
    if reply_to_message is None:
        return None

    reply_text = (reply_to_message.text or reply_to_message.caption or "").strip()
    if not reply_text:
        return None

    author = "bot" if getattr(getattr(reply_to_message, "from_user", None), "is_bot", False) else "user"
    return f"{author}: {reply_text[:300]}"


def _build_addressed_quick_reply(*, text: str, replied_to_bot: bool, mentioned_bot: bool) -> str | None:
    direct_reply = build_grandma_quick_reply(text)
    if direct_reply:
        return direct_reply

    if not (replied_to_bot or mentioned_bot):
        return None

    stripped_text = _strip_explicit_bot_mentions(text).strip()
    if not stripped_text:
        return build_grandma_quick_reply("할매")

    return build_grandma_quick_reply(stripped_text)


def _is_explicit_bot_mention(message: Message) -> bool:
    text = message.text or ""
    entities = message.entities or []
    mention_name = f"@{BOT_USERNAME}" if BOT_USERNAME else ""

    for entity in entities:
        entity_type = str(getattr(entity, "type", ""))
        if entity_type == "text_mention":
            user = getattr(entity, "user", None)
            if BOT_USER_ID is not None and getattr(user, "id", None) == BOT_USER_ID:
                return True
        if entity_type == "mention" and mention_name:
            start = int(getattr(entity, "offset", 0))
            end = start + int(getattr(entity, "length", 0))
            if text[start:end].lower() == mention_name:
                return True

    return False


def _strip_explicit_bot_mentions(text: str) -> str:
    cleaned = text
    mention_name = f"@{BOT_USERNAME}" if BOT_USERNAME else ""
    if mention_name:
        cleaned = cleaned.replace(mention_name, " ")
        cleaned = cleaned.replace(mention_name.lower(), " ")
        cleaned = cleaned.replace(mention_name.upper(), " ")
    return " ".join(cleaned.split())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


async def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing")
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    dp = Dispatcher()
    dp.include_router(router)

    async with Bot(token=TOKEN) as bot:
        watcher_task = asyncio.create_task(run_bitmex_whale_watcher(bot))
        try:
            await register_bot_commands(bot)
            logger.info("Bot starting (aiogram)...")
            await dp.start_polling(bot)
        except TelegramConflictError as exc:
            logger.error("Polling conflict detected. Another bot instance is already consuming updates: %s", exc)
            raise
        finally:
            watcher_task.cancel()
            await asyncio.gather(watcher_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
