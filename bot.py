import asyncio
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from contextlib import suppress

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramConflictError, TelegramForbiddenError
from aiogram.types import BotCommand, BufferedInputFile, Message, ReactionTypeEmoji
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
from services.okx_btc_alert_service import (
    OkxBtcAlertError,
    add_okx_btc_subscription,
    build_okx_btc_alert_message,
    fetch_new_okx_btc_levels,
    get_bitfinex_eth_levels_report_with_focus_prices,
    get_okx_btc_levels_report,
    get_okx_btc_levels_report_with_focus_prices,
    get_okx_eth_levels_report,
    get_okx_btc_poll_interval_seconds,
    get_okx_btc_status_report,
    has_runtime_okx_btc_subscription,
    has_kiyotaka_api_key,
    list_okx_btc_subscriptions,
    remove_okx_btc_subscription,
)
from services.casual_chat_service import (
    build_grandma_quick_reply,
    build_grandma_safety_reply,
    build_grandma_unavailable_reply,
    is_help_request,
    pick_grandma_reaction_candidates,
)
from services.kiyotaka_shortcut_service import (
    build_kiyotaka_shortcut_reply,
    get_kiyotaka_shortcut_spec,
)
from services.kiyotaka_screenshot_service import (
    KiyotakaScreenshotError,
    capture_kiyotaka_screenshot,
)
from services.message_constraints_service import (
    ConstraintSet,
    build_constraint_violation_reply,
    extract_message_constraints,
    find_reply_constraint_violation,
)
from services.message_router_service import route_message_with_pydantic_ai
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
_ACTIVE_KIYOTAKA_CAPTURES: dict[int, str] = {}
_KIYOTAKA_CAPTURE_TASKS: set[asyncio.Task] = set()

router = Router()

BOT_COMMANDS = [
    BotCommand(command="trackon", description="BitMEX 1M+ auto alerts on"),
    BotCommand(command="trackoff", description="BitMEX 1M+ auto alerts off"),
    BotCommand(command="trackstatus", description="Show whale tracking status"),
    BotCommand(command="testalert", description="Send a fake whale alert"),
    BotCommand(command="bitmexwhale", description="Analyze BitMEX whale direction"),
    BotCommand(command="okxbit", description="Show persistent OKX BTC deep heatmap bands"),
    BotCommand(command="okxeth", description="Show persistent OKX ETH deep heatmap bands"),
    BotCommand(command="okxbiton", description="Turn on OKX BTC deep band alerts for this chat"),
    BotCommand(command="okxbitoff", description="Turn off OKX BTC alerts for this chat"),
    BotCommand(command="okxbitstatus", description="Show OKX BTC alert status"),
    BotCommand(command="okxbtcusdtp", description="Show Kiyotaka API OKX BTC-USDT heatmap bands"),
    BotCommand(command="okxbtcusdtpwide", description="Show Kiyotaka API OKX BTC-USDT wide bands"),
    BotCommand(command="bipaeth", description="Show Kiyotaka API Bitfinex ETH strong order walls"),
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
    "/okxbit - OKX BTC 딥 히트맵 밴드 조회\n"
    "/okxeth - OKX ETH 딥 히트맵 밴드 조회\n"
    "/okxbiton - OKX BTC 딥밴드 알람 켜기\n"
    "/okxbitoff - OKX BTC 신규 물량 알람 끄기\n"
    "/okxbitstatus - OKX BTC 알람 상태 확인\n"
    "/okxbtcusdtp - Kiyotaka API OKX BTC-USDT PERP 히트맵 밴드 조회\n"
    "/okxbtcusdtpwide - Kiyotaka API OKX BTC-USDT PERP 와이드 밴드 조회\n"
    "/bipaeth 또는 비파 이더 - BITFINEX ETHUSDT 진한 오더벽 조회\n"
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


@router.message(Command("okxbtcusdtp"))
@router.message(Command("okxbtcusdp"))
@router.message(Command("okxbtcusdtpwide"))
@router.message(Command("okxbtcusdpwide"))
@router.message(Command("bipaeth"))
async def okxbtcusdtp(message: Message):
    await _maybe_answer_kiyotaka_snapshot(message, message.text or "/okxbtcusdtp")


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


@router.message(Command("okxbit"))
@router.message(Command("okxbtc"))
async def okxbit(message: Message):
    await _maybe_answer_kiyotaka_snapshot(message, "/okxbtcusdtp")


@router.message(Command("okxeth"))
async def okxeth(message: Message):
    await _answer_okx_heatmap_report(message, asset="eth")


@router.message(Command("okxbiton"))
async def okxbiton(message: Message):
    added = await asyncio.to_thread(add_okx_btc_subscription, message.chat.id)
    if added:
        await _safe_answer(
            message,
            "OKX 비트 딥밴드 알람을 이 채팅방에 등록했다.\n"
            f"- 체크 주기: {get_okx_btc_poll_interval_seconds() // 3600}시간\n"
            "- 메모: 처음 한 번은 현재 깊은 밴드를 기준값으로 잡고, 그 다음부터 새로 생기거나 더 두꺼워진 밴드만 알린다.",
        )
        return

    await _safe_answer(message, "이 채팅방은 이미 OKX 비트 딥밴드 알람을 받고 있다.")


@router.message(Command("okxbitoff"))
async def okxbitoff(message: Message):
    removed = await asyncio.to_thread(remove_okx_btc_subscription, message.chat.id)
    if removed:
        await _safe_answer(message, "OKX 비트 딥밴드 알람을 이 채팅방에서 껐다.")
        return

    await _safe_answer(message, "이 채팅방은 아직 OKX 비트 딥밴드 알람에 등록되어 있지 않다.")


@router.message(Command("okxbitstatus"))
async def okxbitstatus(message: Message):
    try:
        report = await asyncio.to_thread(get_okx_btc_status_report, message.chat.id)
    except OkxBtcAlertError as exc:
        await _safe_answer(message, f"OKX 비트 알람 상태를 읽지 못했다.\n\n사유: {exc}")
        return

    await _safe_answer(message, report)


async def _answer_okx_heatmap_report(message: Message, *, asset: str) -> None:
    normalized_asset = (asset or "").strip().lower()
    asset_label = "ETH" if normalized_asset == "eth" else "BTC"
    fetch_report = get_okx_eth_levels_report if normalized_asset == "eth" else get_okx_btc_levels_report

    await _acknowledge_message(message, is_market=True)
    if not await _safe_answer(message, f"OKX {asset_label} 딥 히트맵 밴드를 뒤지고 있다..."):
        return

    try:
        report = await asyncio.to_thread(fetch_report)
    except OkxBtcAlertError as exc:
        await _safe_answer(message, f"OKX {asset_label} 딥 히트맵 밴드를 가져오지 못했다.\n\n사유: {exc}")
        return
    except Exception:
        await _safe_answer(message, f"OKX {asset_label} 딥 히트맵 밴드를 정리하는 중에 에러가 났다. 잠시 후 다시 물어봐라.")
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
            "이 채팅방은 서버 고정 등록으로 이미 BitMEX 자동 알림을 받고 있습니다.\n"
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
                "- 다만 서버 환경변수 BITMEX_ALERT_CHAT_IDS 에도 들어 있어서 알림은 계속 올 수 있습니다.\n"
                "- 완전히 끄려면 그 변수에서 현재 chat_id를 빼야 합니다."
            )
            return

        await _safe_answer(message, UNWATCH_WHALES_TEXT)
        return

    configured = await asyncio.to_thread(has_configured_subscription, message.chat.id)
    if configured:
        await _safe_answer(
            message,
            "이 채팅방은 서버 환경변수 BITMEX_ALERT_CHAT_IDS 로 고정 등록돼 있습니다.\n"
            "- 현재 chat_id는 /chatid 로 볼 수 있습니다.\n"
            "- 완전히 끄려면 서버 변수에서 그 chat_id를 빼 주세요."
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
        lines.append("- 메모: 서버 환경변수에 등록돼 있어 재배포 후에도 유지됩니다.")
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
    if not text:
        return

    constraints = extract_message_constraints(text)
    if await _maybe_answer_kiyotaka_snapshot(message, text, constraints=constraints):
        return

    if text.startswith("/"):
        return

    if _is_reply_to_kiyotaka_progress_message(message):
        market_label = _ACTIVE_KIYOTAKA_CAPTURES.get(message.chat.id)
        if market_label:
            await _safe_answer(message, f"{market_label} 캡처는 아직 찍는 중이다. 완료되면 사진으로 따로 올린다.")
        else:
            await _safe_answer(message, "방금 Kiyotaka 작업은 끝났거나 서버 재시작으로 끊겼다. 필요하면 /bipaeth 한 번 더 보내줘.")
        return

    reply_to_message = getattr(message, "reply_to_message", None)
    replied_to_bot = bool(
        reply_to_message and getattr(getattr(reply_to_message, "from_user", None), "is_bot", False)
    )
    mentioned_bot = _is_explicit_bot_mention(message)
    route = await route_message_with_pydantic_ai(
        text=text,
        chat_type=str(getattr(message.chat, "type", "")),
        replied_to_bot=replied_to_bot,
        mentioned_bot=mentioned_bot,
        constraints=constraints,
    )
    intent = route.intent
    logger.info(
        "[Incoming Text] chat_id=%s chat_type=%s replied_to_bot=%s mentioned_bot=%s intent=%s action=%s tool=%s text=%r",
        message.chat.id,
        getattr(message.chat, "type", ""),
        replied_to_bot,
        mentioned_bot,
        intent,
        route.action,
        route.tool,
        text[:200],
    )

    if route.action == "clarify":
        is_market_route = intent in {"market", "whale_history", "okx_heatmap"}
        if is_market_route:
            await _maybe_auto_register_market_chat(message)
        await _acknowledge_message(message, is_market=is_market_route)
        await _safe_answer(message, _build_route_clarification_reply(route))
        return

    if route.tool == "okx_heatmap":
        await _answer_okx_heatmap_report(message, asset=route.asset or "btc")
        return

    if route.tool == "whale_history":
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
        if route.tool != "bitmex":
            await _safe_answer(message, "할매가 쓸 수 있는 시장 도구를 고르지 못했구나. OKX 히트맵이나 BitMEX 중 뭘 볼지 다시 말해다오.")
            return
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

        violation = find_reply_constraint_violation(reply, route.constraints, selected_tool=route.tool)
        if violation:
            logger.warning("[Route Guard] blocked reply: %s", violation.reason)
            await _safe_answer(message, build_constraint_violation_reply(violation))
            return

        await _safe_answer(message, reply)
        return

    if intent == "unsafe":
        await _acknowledge_message(message, is_market=False)
        await _safe_answer(message, build_grandma_safety_reply(text))
        return

    if intent == "casual":
        await _acknowledge_message(message, is_market=False)

        # 명령어/기능 문의는 LLM 거치지 않고 바로 Help 안내
        if is_help_request(text):
            await _safe_answer(message, HELP_TEXT)
            return

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
            violation = find_reply_constraint_violation(reply, route.constraints, selected_tool=route.tool)
            if violation:
                logger.warning("[Route Guard] blocked casual reply: %s", violation.reason)
                reply = build_constraint_violation_reply(violation)
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


async def run_okx_btc_alert_watcher(bot: Bot):
    while True:
        try:
            chat_ids = await asyncio.to_thread(list_okx_btc_subscriptions)
            if chat_ids:
                new_levels = await asyncio.to_thread(fetch_new_okx_btc_levels)
                if new_levels:
                    alert_text = await asyncio.to_thread(build_okx_btc_alert_message, new_levels)
                    for chat_id in chat_ids:
                        try:
                            await bot.send_message(chat_id, alert_text)
                            logger.info(
                                "[OKX BTC Watcher] alert sent chat_id=%s bands=%s top_band=%s top_size=%s",
                                chat_id,
                                len(new_levels),
                                new_levels[0].price_label,
                                new_levels[0].max_size,
                            )
                        except TelegramForbiddenError as exc:
                            await _cleanup_failed_okx_btc_subscription(chat_id)
                            logger.error("[OKX BTC Watcher] send forbidden for chat %s: %s", chat_id, exc)
                        except TelegramBadRequest as exc:
                            if _is_terminal_chat_error(exc):
                                await _cleanup_failed_okx_btc_subscription(chat_id)
                            logger.error("[OKX BTC Watcher] send bad request for chat %s: %s", chat_id, exc)
                        except Exception:
                            logger.exception("[OKX BTC Watcher] send failed for chat %s", chat_id)
        except OkxBtcAlertError as exc:
            logger.error("[OKX BTC Watcher] %s", exc)
        except Exception:
            logger.exception("[OKX BTC Watcher] unexpected error")

        await asyncio.sleep(get_okx_btc_poll_interval_seconds())


async def register_bot_commands(bot: Bot):
    global BOT_USERNAME, BOT_USER_ID
    await bot.set_my_commands(BOT_COMMANDS)
    me = await bot.get_me()
    BOT_USERNAME = (me.username or "").lower()
    BOT_USER_ID = me.id


async def _cleanup_failed_runtime_subscription(chat_id: int) -> None:
    if await asyncio.to_thread(has_runtime_subscription, chat_id):
        await asyncio.to_thread(remove_subscription, chat_id)


async def _cleanup_failed_okx_btc_subscription(chat_id: int) -> None:
    if await asyncio.to_thread(has_runtime_okx_btc_subscription, chat_id):
        await asyncio.to_thread(remove_okx_btc_subscription, chat_id)


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
        return "수동 등록 + 서버 고정 등록"
    if configured_enabled:
        return "서버 고정 등록"
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


def _build_route_clarification_reply(route) -> str:
    excluded = set(route.constraints.excluded_tools)
    if "bitmex" in excluded:
        return _build_bitmex_excluded_market_reply()
    if "okx_heatmap" in excluded:
        return (
            "알겠다. OKX 히트맵 기준은 빼고 보라는 뜻으로 받았다.\n\n"
            "지금 요청은 OKX 쪽 도구로 처리되는 형태라, 그걸 빼면 바로 조회하긴 어렵다. "
            "BitMEX 고래 흐름으로 볼지, 아니면 그냥 말로만 정리할지 다시 말해다오."
        )
    if "kiyotaka_capture" in excluded:
        return "알겠다. 사진이나 캡처는 빼고 텍스트로만 정리하겠다. 어떤 시장 기준으로 볼지 한 번만 더 말해다오."
    return "알겠다. 네가 뺀 기준이 있어서 바로 도구를 돌리진 않겠다. 어떤 기준으로 볼지 다시 말해다오."


async def _safe_answer_photo(message: Message, photo_bytes: bytes, *, caption: str | None = None, filename: str = "chart.png") -> bool:
    photo = BufferedInputFile(photo_bytes, filename=filename)
    try:
        await message.answer_photo(photo=photo, caption=caption)
        return True
    except TelegramForbiddenError as exc:
        await _cleanup_failed_runtime_subscription(message.chat.id)
        logger.error("[Bot Reply] photo send forbidden for chat %s: %s", message.chat.id, exc)
        return False
    except TelegramBadRequest as exc:
        if _is_terminal_chat_error(exc):
            await _cleanup_failed_runtime_subscription(message.chat.id)
            logger.error("[Bot Reply] terminal photo send error for chat %s: %s", message.chat.id, exc)
            return False
        logger.error("[Bot Reply] photo send bad request for chat %s: %s", message.chat.id, exc)
        return False


async def _safe_progress_answer(message: Message, text: str) -> Message | None:
    try:
        return await message.answer(text)
    except TelegramForbiddenError as exc:
        await _cleanup_failed_runtime_subscription(message.chat.id)
        logger.error("[Bot Progress] send forbidden for chat %s: %s", message.chat.id, exc)
        return None
    except TelegramBadRequest as exc:
        if _is_terminal_chat_error(exc):
            await _cleanup_failed_runtime_subscription(message.chat.id)
            logger.error("[Bot Progress] terminal send error for chat %s: %s", message.chat.id, exc)
            return None
        logger.error("[Bot Progress] send bad request for chat %s: %s", message.chat.id, exc)
        return None


async def _safe_edit_message_text(status_message: Message | None, text: str) -> None:
    if status_message is None:
        return

    try:
        await status_message.edit_text(text)
    except Exception:
        return


async def _safe_delete_message(status_message: Message | None) -> None:
    if status_message is None:
        return

    try:
        await status_message.delete()
    except Exception:
        return


async def _typing_pulse(message: Message, stop_event: asyncio.Event, *, interval_seconds: float = 4.0) -> None:
    while not stop_event.is_set():
        await _try_send_typing(message)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue


def _get_kiyotaka_capture_timeout_ms() -> int:
    raw = os.getenv("KIYOTAKA_CAPTURE_TIMEOUT_MS", "120000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 120000
    return min(180000, max(45000, value))


def _get_kiyotaka_split_capture_timeout_ms() -> int:
    raw = os.getenv("KIYOTAKA_SPLIT_CAPTURE_TIMEOUT_MS", "90000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 90000
    return min(120000, max(45000, value))


def _get_kiyotaka_capture_timeout_for_spec_ms(spec) -> int:
    if getattr(spec, "split_capture_with_api", False):
        return min(_get_kiyotaka_capture_timeout_ms(), _get_kiyotaka_split_capture_timeout_ms())
    return _get_kiyotaka_capture_timeout_ms()


def _get_kiyotaka_capture_eta_text(spec, jobs: tuple[tuple[str, tuple[float, ...]], ...]) -> str:
    job_count = max(1, len(jobs))
    timeout_seconds = (job_count * _get_kiyotaka_capture_timeout_for_spec_ms(spec)) // 1000
    typical_seconds = min(timeout_seconds, job_count * _get_kiyotaka_typical_capture_seconds_per_job())
    return f"예상 {_format_eta_duration(typical_seconds)}, 최대 {_format_eta_duration(timeout_seconds)}"


def _get_kiyotaka_typical_capture_seconds_per_job() -> int:
    raw = os.getenv("KIYOTAKA_CAPTURE_ESTIMATE_SECONDS_PER_JOB", "50").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 50
    return min(120, max(20, value))


def _format_eta_duration(seconds: int) -> str:
    minutes = max(1, (max(0, int(seconds)) + 59) // 60)
    if minutes <= 1:
        return "1분 이내"
    return f"약 {minutes}분"


async def _maybe_answer_kiyotaka_snapshot(
    message: Message,
    text: str,
    *,
    constraints: ConstraintSet | None = None,
) -> bool:
    spec = get_kiyotaka_shortcut_spec(text)
    if spec is None:
        return False

    constraints = constraints or ConstraintSet()
    capture_allowed = not constraints.wants_text_only

    if spec.api_asset:
        market_label = _get_kiyotaka_api_market_label(spec)
        progress_text = (
            f"{spec.title}\n"
            f"작동 중이다. Kiyotaka API로 {market_label} 진한 오더벽을 조회 중이다.\n"
            "- API 키 확인\n"
            "- 흐릿한 물량 제외하고 오래 유지된 밴드만 필터링 중\n"
            f"- {'Kiyotaka 캡처 준비 중' if capture_allowed else '요청대로 텍스트 응답 모드'}"
        )
        status_message = await _safe_progress_answer(message, progress_text)
        try:
            logger.info("[Kiyotaka API] report start chat_id=%s key=%s text=%r", message.chat.id, spec.key, text[:120])
            report, focus_prices = await asyncio.to_thread(_get_kiyotaka_api_result_for_spec, spec)
        except OkxBtcAlertError as exc:
            logger.warning("[Kiyotaka API] report failed for %s: %s", spec.key, exc)
            if _kiyotaka_browser_fallback_enabled() and capture_allowed:
                await _safe_edit_message_text(
                    status_message,
                    f"{spec.title}\nKiyotaka API가 실패해서 브라우저 캡처 fallback으로 넘어간다.",
                )
            else:
                await _safe_edit_message_text(
                    status_message,
                    f"{spec.title}\nKiyotaka API 조회가 실패해서 링크 안내로 대신 남긴다.",
                )
                await _safe_answer(
                    message,
                    build_kiyotaka_shortcut_reply(spec, note=f"API 조회 실패: {exc}"),
                )
                return True
        else:
            if spec.capture_with_api and capture_allowed:
                jobs = _get_kiyotaka_capture_jobs(spec, focus_prices)
                eta_text = _get_kiyotaka_capture_eta_text(spec, jobs)
                await _safe_edit_message_text(
                    status_message,
                    f"{spec.title}\nAPI 조회 완료. 텍스트 먼저 보내고 Kiyotaka 캡처는 뒤에서 찍는 중이다. {eta_text}.",
                )
                await _safe_answer(message, f"{report}\n\n캡처는 뒤에서 찍고 있다. {eta_text}. 완료되면 사진으로 이어서 보낸다.")
                _start_kiyotaka_capture_task(message, spec, report, focus_prices, status_message)
                return True

            await _safe_edit_message_text(
                status_message,
                f"{spec.title}\nKiyotaka API 조회 완료. {'요청대로 캡처는 쓰지 않았다.' if not capture_allowed else '브라우저 캡처는 쓰지 않았다.'}",
            )
            await _safe_answer(message, report)
            await _safe_delete_message(status_message)
            return True

    if not capture_allowed:
        await _safe_answer(
            message,
            build_kiyotaka_shortcut_reply(spec, note="요청대로 사진/캡처는 쓰지 않고 텍스트 안내만 남긴다."),
        )
        return True

    progress_text = (
        f"{spec.title}\n"
        "할매가 Kiyotaka 차트 찾고 있다. 브라우저 fallback 모드다.\n"
        "- 심볼 검색 중\n"
        "- 히트맵 캡처 준비 중"
    )
    status_message = await _safe_progress_answer(message, progress_text)
    typing_stop = asyncio.Event()
    typing_task = asyncio.create_task(_typing_pulse(message, typing_stop))
    try:
        logger.info("[Kiyotaka] capture start chat_id=%s key=%s text=%r", message.chat.id, spec.key, text[:120])
        photo_bytes = await capture_kiyotaka_screenshot(spec, timeout_ms=_get_kiyotaka_capture_timeout_ms())
    except KiyotakaScreenshotError as exc:
        logger.warning("[Kiyotaka] screenshot failed for %s: %s", spec.key, exc)
        typing_stop.set()
        with suppress(Exception):
            await typing_task
        await _safe_edit_message_text(
            status_message,
            f"{spec.title}\n할매가 스크린샷은 못 찍어서 링크로 대신 챙겨왔다.",
        )
        await _safe_answer(
            message,
            build_kiyotaka_shortcut_reply(spec, note=f"스크린샷은 지금 못 찍어서 링크로 대신 보낸다. 사유: {exc}"),
        )
        return True
    except Exception:
        logger.exception("[Kiyotaka] unexpected screenshot failure for %s", spec.key)
        typing_stop.set()
        with suppress(Exception):
            await typing_task
        await _safe_edit_message_text(
            status_message,
            f"{spec.title}\n할매가 스크린샷 만들다 잠깐 헷갈렸다. 링크로 대신 보낸다.",
        )
        await _safe_answer(
            message,
            build_kiyotaka_shortcut_reply(spec, note="스크린샷 생성 중 예기치 않은 오류가 나서 링크로 대신 보낸다."),
        )
        return True
    finally:
        typing_stop.set()
        with suppress(Exception):
            await typing_task

    caption = f"{spec.title}\n{spec.search_query} | {spec.timeframe} | {spec.view}"
    await _safe_edit_message_text(
        status_message,
        f"{spec.title}\n할매가 히트맵 캡처해서 보내는 중이다.",
    )
    sent = await _safe_answer_photo(
        message,
        photo_bytes,
        caption=caption,
        filename=f"{spec.key}.png",
    )
    if sent:
        await _safe_delete_message(status_message)
    else:
        await _safe_edit_message_text(
            status_message,
            f"{spec.title}\n사진 전송이 꼬여서 텍스트 안내로 대신 남긴다.",
        )
    if not sent:
        await _safe_answer(message, build_kiyotaka_shortcut_reply(spec))
    return True


def _get_kiyotaka_api_market_label(spec) -> str:
    normalized_asset = (spec.api_asset or "").strip().lower()
    if normalized_asset == "bitfinex_eth":
        return "BITFINEX ETH"
    if normalized_asset == "eth":
        return "OKX ETH"
    if normalized_asset == "btc":
        return "OKX BTC"
    return (spec.api_asset or spec.title).upper()


def _get_kiyotaka_api_report_for_spec(spec) -> str:
    report, _focus_prices = _get_kiyotaka_api_result_for_spec(spec)
    return report


def _get_kiyotaka_api_result_for_spec(spec) -> tuple[str, tuple[float, ...]]:
    if not has_kiyotaka_api_key():
        raise OkxBtcAlertError("KIYOTAKA_API_KEY가 없습니다.")

    normalized_asset = (spec.api_asset or "").strip().lower()
    if normalized_asset == "btc":
        return get_okx_btc_levels_report_with_focus_prices()
    if normalized_asset == "eth":
        return get_okx_eth_levels_report(), ()
    if normalized_asset == "bitfinex_eth":
        return get_bitfinex_eth_levels_report_with_focus_prices()
    raise OkxBtcAlertError(f"지원하지 않는 Kiyotaka API 자산입니다: {spec.api_asset}")


def _get_kiyotaka_capture_jobs(spec, focus_prices: tuple[float, ...]) -> tuple[tuple[str, tuple[float, ...]], ...]:
    if getattr(spec, "split_capture_with_api", False):
        remote_focus_prices = tuple(float(price) for price in focus_prices[1:] if float(price) > 0)
        jobs: list[tuple[str, tuple[float, ...]]] = [("current area", ())]
        if remote_focus_prices:
            jobs.append(("API order area", remote_focus_prices))
        return tuple(jobs)
    return (("capture", focus_prices),)


def _format_focus_prices_for_caption(focus_prices: tuple[float, ...]) -> str:
    if not focus_prices:
        return ""
    formatted = ", ".join(_format_caption_price(price) for price in focus_prices[:6])
    if len(focus_prices) > 6:
        formatted += ", ..."
    return formatted


def _format_caption_price(price: float) -> str:
    if abs(price - round(price)) < 0.01:
        return f"{round(price):,}"
    return f"{price:,.1f}"


def _start_kiyotaka_capture_task(
    message: Message,
    spec,
    report: str,
    focus_prices: tuple[float, ...],
    status_message: Message | None,
) -> None:
    task = asyncio.create_task(
        _send_kiyotaka_capture_when_ready(
            message,
            spec,
            report=report,
            focus_prices=focus_prices,
            status_message=status_message,
        )
    )
    _KIYOTAKA_CAPTURE_TASKS.add(task)

    def _forget_task(done_task: asyncio.Task) -> None:
        _KIYOTAKA_CAPTURE_TASKS.discard(done_task)
        with suppress(asyncio.CancelledError):
            exc = done_task.exception()
            if exc is not None:
                logger.error("[Kiyotaka] background capture task crashed", exc_info=(type(exc), exc, exc.__traceback__))

    task.add_done_callback(_forget_task)


async def _send_kiyotaka_capture_when_ready(
    message: Message,
    spec,
    *,
    report: str,
    focus_prices: tuple[float, ...],
    status_message: Message | None,
) -> None:
    market_label = _get_kiyotaka_api_market_label(spec)
    _ACTIVE_KIYOTAKA_CAPTURES[message.chat.id] = market_label
    try:
        jobs = _get_kiyotaka_capture_jobs(spec, focus_prices)
        timeout_ms = _get_kiyotaka_capture_timeout_for_spec_ms(spec)
        sent_any = False
        for index, (label, job_focus_prices) in enumerate(jobs, start=1):
            try:
                if len(jobs) > 1:
                    eta_text = _get_kiyotaka_capture_eta_text(spec, jobs[index - 1 :])
                    await _safe_edit_message_text(
                        status_message,
                        f"{spec.title}\nKiyotaka capture {index}/{len(jobs)}: {label}\n남은 {eta_text}.",
                    )
                photo_bytes = await capture_kiyotaka_screenshot(
                    spec,
                    timeout_ms=timeout_ms,
                    focus_prices=job_focus_prices,
                )
            except KiyotakaScreenshotError as exc:
                logger.warning(
                    "[Kiyotaka] API report succeeded but screenshot failed for %s job=%s: %s",
                    spec.key,
                    label,
                    exc,
                )
                await _safe_answer(message, f"{market_label} Kiyotaka capture failed ({label}): {exc}")
                continue
            except Exception:
                logger.exception("[Kiyotaka] unexpected background screenshot failure for %s job=%s", spec.key, label)
                await _safe_answer(message, f"{market_label} Kiyotaka capture failed ({label}).")
                continue

            caption = f"{market_label} Kiyotaka capture {index}/{len(jobs)} - {label}"
            focus_summary = _format_focus_prices_for_caption(job_focus_prices)
            if focus_summary:
                caption = f"{caption}\nFocus: {focus_summary}"
            sent = await _safe_answer_photo(
                message,
                photo_bytes,
                caption=caption,
                filename=f"{spec.key}-{index}.png",
            )
            sent_any = sent_any or sent

        if sent_any:
            await _safe_delete_message(status_message)
        else:
            await _safe_edit_message_text(
                status_message,
                f"{spec.title}\n캡처는 만들었지만 텔레그램 사진 전송이 실패했다.",
            )

        _ = report
    finally:
        _ACTIVE_KIYOTAKA_CAPTURES.pop(message.chat.id, None)


def _is_reply_to_kiyotaka_progress_message(message: Message) -> bool:
    reply_to_message = getattr(message, "reply_to_message", None)
    if reply_to_message is None:
        return False
    if not getattr(getattr(reply_to_message, "from_user", None), "is_bot", False):
        return False

    source_text = (getattr(reply_to_message, "text", None) or getattr(reply_to_message, "caption", None) or "")
    normalized = source_text.lower()
    return "kiyotaka" in normalized and ("캡처" in source_text or "capture" in normalized or "오더벽" in source_text)


def _kiyotaka_browser_fallback_enabled() -> bool:
    return os.getenv("KIYOTAKA_BROWSER_FALLBACK_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


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


def _build_bitmex_excluded_market_reply() -> str:
    return (
        "알겠다. 비트맥스 기준은 빼고 말하마.\n\n"
        "다만 지금 할매한테 붙어 있는 실시간 단기 방향 도구는 BitMEX 쪽이라, 그걸 빼면 롱/숏을 숫자로 단정하긴 어렵다. "
        "OKX 오더북/히트맵으로 보려면 `okx 비트 밴드 확인`처럼 물어보면 그 기준으로 다시 볼 수 있다."
    )


def _should_skip_polling_for_runtime() -> bool:
    if os.getenv("ALLOW_RAILWAY_POLLING_BOT", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False

    return any(
        os.getenv(name)
        for name in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_DEPLOYMENT_ID",
        )
    )


async def main():
    if _should_skip_polling_for_runtime():
        logger.warning(
            "Disabled deployment runtime detected; exiting without Telegram polling. "
            "Set ALLOW_RAILWAY_POLLING_BOT=1 to override."
        )
        return

    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing")
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    dp = Dispatcher()
    dp.include_router(router)

    async with Bot(token=TOKEN) as bot:
        watcher_task = asyncio.create_task(run_bitmex_whale_watcher(bot))
        okx_watcher_task = asyncio.create_task(run_okx_btc_alert_watcher(bot))
        try:
            await register_bot_commands(bot)
            logger.info("Bot starting (aiogram)...")
            await dp.start_polling(bot)
        except TelegramConflictError as exc:
            logger.error("Polling conflict detected. Another bot instance is already consuming updates: %s", exc)
            raise
        finally:
            watcher_task.cancel()
            okx_watcher_task.cancel()
            await asyncio.gather(watcher_task, okx_watcher_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
