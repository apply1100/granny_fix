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
    "?ъ슜 媛?ν븳 紐낅졊??n"
    "/ping - 遊??묐떟 ?뺤씤\n"
    "/chatid - ?꾩옱 chat_id ?뺤씤\n"
    "/coinalyze - BitMEX ???泥닿껐 ?뚮┝ ?명똿 ?덈궡\n"
    "/bitmexwhale - OI/CVD 湲곗? BitMEX 濡깆닆 異붿젙\n"
    "/watchwhales - BitMEX 1M+ ?먮룞 ?뚮┝ ?쒖옉\n"
    "/unwatchwhales - BitMEX 1M+ ?먮룞 ?뚮┝ 以묒?\n"
    "/trackon - BitMEX 1M+ ?먮룞 ?뚮┝ ?쒖옉\n"
    "/trackoff - BitMEX 1M+ ?먮룞 ?뚮┝ 以묒?\n"
    "/trackstatus - ?꾩옱 梨꾪똿諛??먮룞 ?뚮┝ ?곹깭 ?뺤씤\n"
    "/testalert - 媛吏?1M ?뚮┝ ?뚯뒪??n"
    "/okxbit - OKX BTC ???덊듃留?諛대뱶 議고쉶\n"
    "/okxeth - OKX ETH ???덊듃留?諛대뱶 議고쉶\n"
    "/okxbiton - OKX BTC ?λ객???뚮엺 耳쒓린\n"
    "/okxbitoff - OKX BTC ?좉퇋 臾쇰웾 ?뚮엺 ?꾧린\n"
    "/okxbitstatus - OKX BTC ?뚮엺 ?곹깭 ?뺤씤\n"
    "/okxbtcusdtp - Kiyotaka API OKX BTC-USDT PERP ?덊듃留?諛대뱶 議고쉶\n"
    "/okxbtcusdtpwide - Kiyotaka API OKX BTC-USDT PERP ??대뱶 諛대뱶 議고쉶\n"
    "/bipaeth ?먮뒗 鍮꾪뙆 ?대뜑 - BITFINEX ETHUSDT 吏꾪븳 ?ㅻ뜑踰?議고쉶\n"
    "/testwhalealert - ?꾩옱 梨꾪똿諛⑹쑝濡?媛吏??뚮┝ ?뚯뒪??n\n"
    "?쒖옣 吏덈Ц? 洹몃깷 臾몄옣?쇰줈 臾쇱뼱遊먮룄 ?⑸땲??\n"
    "?? 吏湲?濡깆씠???륁씠??/ 鍮꾪듃留μ뒪 ?꾧? ?뚮━??/ OI 遺숈뿀??
)

COINALYZE_ALERT_TEXT = (
    "BitMEX ???泥닿껐 泥댄겕??Coinalyze ?명똿\n\n"
    "1. Coinalyze?먯꽌 BTC / USD Perp BitMEX 李⑦듃瑜??쎈땲??\n"
    "2. Alerts ?먮뒗 醫?紐⑥뼇 硫붾돱瑜??꾨쫭?덈떎.\n"
    "3. 議곌굔??trade size greater than ?쇰줈 怨좊쫭?덈떎.\n"
    "4. 媛믪? 1000000?쇰줈 ?ｌ뒿?덈떎.\n"
    "5. ??ν븯怨??붾젅洹몃옩 ?뚮┝???곌껐?⑸땲??\n\n"
    "鍮좊Ⅸ 泥댄겕 ?ъ씤??n"
    "- ?먯젙 ?몄?由ъ쿂???섍툒??遺숇뒗 ?쒓컙????뱁엳 ?좎슜?⑸땲??\n"
    "- ???뚮┝???몃┫ ??媛寃?洹쇱쿂濡??쇱?媛 ?щ젮?쒕뒗吏 ???뺤씤?섎㈃ ?⑸땲??\n\n"
    "李멸퀬 留곹겕\n"
    "- Alerts: https://coinalyze.net/alerts/\n"
    "- BTC/USD Perp BitMEX: https://coinalyze.net/bitcoin/usd/bitmex/btcusd_perp/price-chart-live/\n\n"
    "硫붾え: Coinalyze UI 臾멸뎄??議곌툑 諛붾????덉?留??듭떖 議고빀? "
    "BitMEX + BTC/USD Perp + trade size greater than + 1000000 ?낅땲??"
)

BITMEX_WHALE_HELP_TEXT = (
    "BitMEX 怨좊옒 ?ъ???異붿젙? Coinalyze API媛 ?꾩슂?⑸땲??\n"
    ".env??COINALYZE_API_KEY瑜??ｌ? ??/bitmexwhale 瑜?蹂대궡硫?\n"
    "理쒓렐 5遺?OI? 理쒓렐 15遺?留ㅼ닔?곗쐞(CVD ???쨌泥?궛쨌??⑹쓣 媛숈씠 ?쎌뼱??n"
    "?좉퇋 濡??좉퇋 ??濡??뺣━/??而ㅻ쾭留?以??대뵒??媛源뚯슫吏 異붿젙???쒕┰?덈떎."
)

WATCH_WHALES_TEXT = (
    "BitMEX ???泥닿껐 ?먮룞 ?뚮┝???깅줉?덉뒿?덈떎.\n"
    f"- 湲곗? 泥닿껐: {get_trade_threshold():,} contracts\n"
    f"- 泥댄겕 二쇨린: {get_poll_interval_seconds()}珥?n"
    "- ??梨꾪똿諛⑹쑝濡????泥닿껐???섏삤硫?癒쇱? 蹂대궡?쒕┫寃뚯슂.\n"
    "- 遊뉗씠 ?ㅽ뻾 以묒씠?댁빞 ?먮룞 ?뚮┝???숈옉?⑸땲??"
)

UNWATCH_WHALES_TEXT = "BitMEX ???泥닿껐 ?먮룞 ?뚮┝????梨꾪똿諛⑹뿉???댁젣?덉뒿?덈떎."
MARKET_QUESTION_HINT = (
    "?쒖옣 吏덈Ц?대㈃ 洹몃깷 留먮줈 臾쇱뼱蹂닿굅??\n"
    "?? 吏湲?濡깆씠???륁씠??/ 鍮꾪듃留μ뒪 ?꾧? ?뚮━??/ OI 遺숈뿀??
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
    if not await _safe_answer(message, "BitMEX 怨좊옒 ?ъ???異붿젙 以?.."):
        return

    try:
        report = await asyncio.to_thread(get_bitmex_whale_report)
    except CoinalyzeError as exc:
        await _safe_answer(message, f"{BITMEX_WHALE_HELP_TEXT}\n\n?ъ쑀: {exc}")
        return
    except Exception:
        await _safe_answer(message, "BitMEX 怨좊옒 異붿젙 以??덇린移??딆? ?ㅻ쪟媛 ?ъ뒿?덈떎. ?좎떆 ???ㅼ떆 ?쒕룄??二쇱꽭??")
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
            "OKX 鍮꾪듃 ?λ객???뚮엺????梨꾪똿諛⑹뿉 ?깅줉?덈떎.\n"
            f"- 泥댄겕 二쇨린: {get_okx_btc_poll_interval_seconds() // 3600}?쒓컙\n"
            "- 硫붾え: 泥섏쓬 ??踰덉? ?꾩옱 源딆? 諛대뱶瑜?湲곗?媛믪쑝濡??↔퀬, 洹??ㅼ쓬遺???덈줈 ?앷린嫄곕굹 ???먭볼?뚯쭊 諛대뱶留??뚮┛??",
        )
        return

    await _safe_answer(message, "??梨꾪똿諛⑹? ?대? OKX 鍮꾪듃 ?λ객???뚮엺??諛쏄퀬 ?덈떎.")


@router.message(Command("okxbitoff"))
async def okxbitoff(message: Message):
    removed = await asyncio.to_thread(remove_okx_btc_subscription, message.chat.id)
    if removed:
        await _safe_answer(message, "OKX 鍮꾪듃 ?λ객???뚮엺????梨꾪똿諛⑹뿉??猿먮떎.")
        return

    await _safe_answer(message, "??梨꾪똿諛⑹? ?꾩쭅 OKX 鍮꾪듃 ?λ객???뚮엺???깅줉?섏뼱 ?덉? ?딅떎.")


@router.message(Command("okxbitstatus"))
async def okxbitstatus(message: Message):
    try:
        report = await asyncio.to_thread(get_okx_btc_status_report, message.chat.id)
    except OkxBtcAlertError as exc:
        await _safe_answer(message, f"OKX 鍮꾪듃 ?뚮엺 ?곹깭瑜??쎌? 紐삵뻽??\n\n?ъ쑀: {exc}")
        return

    await _safe_answer(message, report)


async def _answer_okx_heatmap_report(message: Message, *, asset: str) -> None:
    normalized_asset = (asset or "").strip().lower()
    asset_label = "ETH" if normalized_asset == "eth" else "BTC"
    fetch_report = get_okx_eth_levels_report if normalized_asset == "eth" else get_okx_btc_levels_report

    await _acknowledge_message(message, is_market=True)
    if not await _safe_answer(message, f"OKX {asset_label} ???덊듃留?諛대뱶瑜??ㅼ?怨??덈떎..."):
        return

    try:
        report = await asyncio.to_thread(fetch_report)
    except OkxBtcAlertError as exc:
        await _safe_answer(message, f"OKX {asset_label} ???덊듃留?諛대뱶瑜?媛?몄삤吏 紐삵뻽??\n\n?ъ쑀: {exc}")
        return
    except Exception:
        await _safe_answer(message, f"OKX {asset_label} ???덊듃留?諛대뱶瑜??뺣━?섎뒗 以묒뿉 ?먮윭媛 ?щ떎. ?좎떆 ???ㅼ떆 臾쇱뼱遊먮씪.")
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
            "??梨꾪똿諛⑹? ?쒕쾭 怨좎젙 ?깅줉?쇰줈 ?대? BitMEX ?먮룞 ?뚮┝??諛쏄퀬 ?덉뒿?덈떎.\n"
            "- ?щ같???꾩뿉???좎??⑸땲??\n"
            "- ?꾩옱 ?곹깭??/trackstatus 濡??ㅼ떆 ?뺤씤?????덉뒿?덈떎."
        )
        return

    await _safe_answer(message, "?대? ??梨꾪똿諛⑹? BitMEX ???泥닿껐 ?먮룞 ?뚮┝??諛쏄퀬 ?덉뒿?덈떎.")


@router.message(Command("unwatchwhales"))
@router.message(Command("trackoff"))
async def unwatchwhales(message: Message):
    removed = await asyncio.to_thread(remove_subscription, message.chat.id)
    if removed:
        configured = await asyncio.to_thread(has_configured_subscription, message.chat.id)
        if configured:
            await _safe_answer(
                message,
                "??梨꾪똿諛⑹쓽 ?섎룞 ?깅줉? ?댁젣?덉뒿?덈떎.\n"
                "- ?ㅻ쭔 ?쒕쾭 ?섍꼍蹂??BITMEX_ALERT_CHAT_IDS ?먮룄 ?ㅼ뼱 ?덉뼱???뚮┝? 怨꾩냽 ?????덉뒿?덈떎.\n"
                "- ?꾩쟾???꾨젮硫?洹?蹂?섏뿉???꾩옱 chat_id瑜?鍮쇱빞 ?⑸땲??"
            )
            return

        await _safe_answer(message, UNWATCH_WHALES_TEXT)
        return

    configured = await asyncio.to_thread(has_configured_subscription, message.chat.id)
    if configured:
        await _safe_answer(
            message,
            "??梨꾪똿諛⑹? ?쒕쾭 ?섍꼍蹂??BITMEX_ALERT_CHAT_IDS 濡?怨좎젙 ?깅줉???덉뒿?덈떎.\n"
            "- ?꾩옱 chat_id??/chatid 濡?蹂????덉뒿?덈떎.\n"
            "- ?꾩쟾???꾨젮硫??쒕쾭 蹂?섏뿉??洹?chat_id瑜?鍮?二쇱꽭??"
        )
        return

    await _safe_answer(message, "??梨꾪똿諛⑹? ?꾩쭅 ?먮룞 ?뚮┝ ?깅줉???놁뒿?덈떎.")


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
        "BitMEX ?먮룞 ?뚮┝ ?곹깭",
        f"- ?꾩옱 梨꾪똿: {'耳쒖쭚' if enabled else '爰쇱쭚'}",
        f"- ?깅줉 諛⑹떇: {source}",
        f"- 湲곗? 泥닿껐: {get_trade_threshold():,} contracts ({format_trade_threshold_label()})",
        f"- 泥댄겕 二쇨린: {get_poll_interval_seconds()}珥?,
        f"- Coinalyze 異붿젙: {'媛?? if coinalyze_ready else 'API ???놁쓬'}",
        f"- ?먮룞 ?щ벑濡? {'耳쒖쭚' if auto_register_enabled else '爰쇱쭚'}",
        f"- chat_id: {message.chat.id}",
    ]

    if configured_enabled:
        lines.append("- 硫붾え: ?쒕쾭 ?섍꼍蹂?섏뿉 ?깅줉???덉뼱 ?щ같???꾩뿉???좎??⑸땲??")
    elif enabled and auto_register_enabled:
        lines.append("- 硫붾え: ?꾩옱???고????깅줉?낅땲?? ?щ같???꾩뿉??/trackstatus, /bitmexwhale, /coinalyze ?먮뒗 BitMEX 吏덈Ц???ㅻ㈃ ?먮룞?쇰줈 ?ㅼ떆 遺숈뒿?덈떎.")
    elif enabled:
        lines.append("- 硫붾え: ?꾩옱???고????깅줉?대씪 ?щ같???꾩뿉???ㅼ떆 /trackon ???꾩슂?????덉뒿?덈떎.")
    elif auto_register_enabled:
        lines.append("- 硫붾え: ?꾩쭅 爰쇱졇 ?덉뼱??/trackstatus, /bitmexwhale, /coinalyze ?먮뒗 BitMEX 吏덈Ц???ㅻ㈃ ?먮룞?쇰줈 耳쒖쭛?덈떎.")
    else:
        lines.append("- 硫붾え: ?먮룞 ?뚮┝??耳쒕젮硫?/trackon ??蹂대궡硫??⑸땲??")

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
        f"BitMEX {threshold_label} ?먮룞 ?뚮┝",
        f"BitMEX {threshold_label} ?뚯뒪???뚮┝",
        1,
    )
    report = (
        "BitMEX 怨좊옒 ?ъ???異붿젙\n"
        "- 異붿젙: ?뚯뒪???뚮┝?낅땲??n"
        "- ?좊ː?? ?뚯뒪??n"
        "- ?쒖쨪 ?붿빟: ?ㅼ젣 泥닿껐???꾨땲???먮룞 ?뚮┝ 寃쎈줈 ?뺤씤?⑹엯?덈떎.\n"
        "- 硫붾え: ?ㅼ쟾?먯꽌???ш린??OI/CVD/泥?궛/???湲곕컲 異붿젙??遺숈뒿?덈떎."
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
            await _safe_answer(message, f"{market_label} 罹≪쿂???꾩쭅 李띾뒗 以묒씠?? ?꾨즺?섎㈃ ?ъ쭊?쇰줈 ?곕줈 ?щ┛??")
        else:
            await _safe_answer(message, "諛⑷툑 Kiyotaka ?묒뾽? ?앸궗嫄곕굹 ?쒕쾭 ?ъ떆?묒쑝濡??딄꼈?? ?꾩슂?섎㈃ /bipaeth ??踰???蹂대궡以?")
        return

    reply_to_message = getattr(message, "reply_to_message", None)
    replied_to_bot = bool(
        reply_to_message
        and BOT_USER_ID is not None
        and getattr(getattr(reply_to_message, "from_user", None), "id", None) == BOT_USER_ID
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
            await _safe_answer(message, f"理쒓렐 BitMEX 怨좊옒 泥닿껐 ?댁뿭??媛?몄삤吏 紐삵뻽?듬땲??\n\n?ъ쑀: {exc}")
            return
        except Exception:
            await _safe_answer(message, "BitMEX 泥닿껐 ?댁뿭 ?뺣━ 以묒뿉 ?좉퉸 瑗ъ?援щ굹. 議곌툑 ?덈떎媛 ?ㅼ떆 臾쇱뼱蹂닿굅??")
            return

        await _safe_answer(message, report)
        return

    if intent == "market":
        await _maybe_auto_register_market_chat(message)
        await _acknowledge_message(message, is_market=True)
        if route.tool != "bitmex":
            await _safe_answer(message, "?좊ℓ媛 ?????덈뒗 ?쒖옣 ?꾧뎄瑜?怨좊Ⅴ吏 紐삵뻽援щ굹. OKX ?덊듃留듭씠??BitMEX 以?萸?蹂쇱? ?ㅼ떆 留먰빐?ㅼ삤.")
            return
        if not await _safe_answer(message, "?좊ℓ媛 鍮꾪듃留μ뒪 ?먮쫫 蹂닿퀬 ?ㅻ뒗 以묒씠援щ굹..."):
            return
        try:
            reply = await asyncio.to_thread(get_bitmex_whale_grandma_reply, text)
        except CoinalyzeError as exc:
            await _safe_answer(message, f"{BITMEX_WHALE_HELP_TEXT}\n\n?ъ쑀: {exc}")
            return
        except Exception:
            await _safe_answer(message, "?쒖옣 ?먮쫫 ?쎈뒗 以묒뿉 ?좉퉸 ?룰컝?멸뎄?? 議곌툑 ?덈떎媛 ?ㅼ떆 臾쇱뼱蹂닿굅??")
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

        # 紐낅졊??湲곕뒫 臾몄쓽??LLM 嫄곗튂吏 ?딄퀬 諛붾줈 Help ?덈궡
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
                        report = f"Coinalyze 遺꾩꽍 ?ㅽ뙣: {exc}"

                    alert_text = f"{header}\n\n{report}"
                    for chat_id in chat_ids:
                        try:
                            await bot.send_message(chat_id, alert_text)
                            logger.info(
                                "[BitMEX Watcher] alert sent trade_id=%s chat_id=%s local_time=%r side=%s size=%s symbol=%s delayed=%s delay_seconds=%s",
                                trade.trade_id, chat_id, trade.local_time,
                                trade.side, trade.size, trade.symbol,
                                delayed, delay_seconds,
                            )
                        except TelegramForbiddenError as exc:
                            await _cleanup_failed_runtime_subscription(chat_id)
                            logger.error("[BitMEX Watcher] send forbidden for chat %s: %s", chat_id, exc)
                        except TelegramBadRequest as exc:
                            if _is_terminal_chat_error(exc):
                                await _cleanup_failed_runtime_subscription(chat_id)
                            logger.error("[BitMEX Watcher] send bad request for chat %s: %s", chat_id, exc)
                        except Exception:
                            logger.exception("[BitMEX Watcher] send failed for chat %s", chat_id)
        except BitmexWatcherError as exc:
            logger.error("[BitMEX Watcher] %s", exc)
        except Exception:
            logger.exception("[BitMEX Watcher] unexpected error")

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
        logger.info("[BitMEX Watcher] auto-registered chat %s from market interaction", message.chat.id)


def _is_terminal_chat_error(exc: TelegramBadRequest) -> bool:
    message = str(exc).lower()
    terminals = ["chat not found", "user is deactivated", "not enough rights", "bot was kicked", "bot was blocked"]
    return any(t in message for t in terminals)


def _describe_subscription_source(runtime_enabled: bool, configured_enabled: bool) -> str:
    if runtime_enabled and configured_enabled:
        return "?섎룞 ?깅줉 + ?쒕쾭 怨좎젙 ?깅줉"
    if configured_enabled:
        return "?쒕쾭 怨좎젙 ?깅줉"
    if runtime_enabled:
        return "?섎룞 ?깅줉"
    return "誘몃벑濡?


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
        reply_to_message
        and BOT_USER_ID is not None
        and getattr(getattr(reply_to_message, "from_user", None), "id", None) == BOT_USER_ID
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
            "?뚭쿋?? OKX ?덊듃留?湲곗?? 鍮쇨퀬 蹂대씪???살쑝濡?諛쏆븯??\n\n"
            "吏湲??붿껌? OKX 履??꾧뎄濡?泥섎━?섎뒗 ?뺥깭?? 洹멸구 鍮쇰㈃ 諛붾줈 議고쉶?섍릿 ?대졄?? "
            "BitMEX 怨좊옒 ?먮쫫?쇰줈 蹂쇱?, ?꾨땲硫?洹몃깷 留먮줈留??뺣━?좎? ?ㅼ떆 留먰빐?ㅼ삤."
        )
    if "kiyotaka_capture" in excluded:
        return "?뚭쿋?? ?ъ쭊?대굹 罹≪쿂??鍮쇨퀬 ?띿뒪?몃줈留??뺣━?섍쿋?? ?대뼡 ?쒖옣 湲곗??쇰줈 蹂쇱? ??踰덈쭔 ??留먰빐?ㅼ삤."
    return "?뚭쿋?? ?ㅺ? 類 湲곗????덉뼱??諛붾줈 ?꾧뎄瑜??뚮━吏??딄쿋?? ?대뼡 湲곗??쇰줈 蹂쇱? ?ㅼ떆 留먰빐?ㅼ삤."


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
    return f"?덉긽 {_format_eta_duration(typical_seconds)}, 理쒕? {_format_eta_duration(timeout_seconds)}"


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
        return "1遺??대궡"
    return f"??{minutes}遺?


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
            f"?묐룞 以묒씠?? Kiyotaka API濡?{market_label} 吏꾪븳 ?ㅻ뜑踰쎌쓣 議고쉶 以묒씠??\n"
            "- API ???뺤씤\n"
            "- ?먮┸??臾쇰웾 ?쒖쇅?섍퀬 ?ㅻ옒 ?좎???諛대뱶留??꾪꽣留?以?n"
            f"- {'Kiyotaka 罹≪쿂 以鍮?以? if capture_allowed else '?붿껌?濡??띿뒪???묐떟 紐⑤뱶'}"
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
                    f"{spec.title}\nKiyotaka API媛 ?ㅽ뙣?댁꽌 釉뚮씪?곗? 罹≪쿂 fallback?쇰줈 ?섏뼱媛꾨떎.",
                )
            else:
                await _safe_edit_message_text(
                    status_message,
                    f"{spec.title}\nKiyotaka API 議고쉶媛 ?ㅽ뙣?댁꽌 留곹겕 ?덈궡濡?????④릿??",
                )
                await _safe_answer(
                    message,
                    build_kiyotaka_shortcut_reply(spec, note=f"API 議고쉶 ?ㅽ뙣: {exc}"),
                )
                return True
        else:
            if spec.capture_with_api and capture_allowed:
                jobs = _get_kiyotaka_capture_jobs(spec, focus_prices)
                eta_text = _get_kiyotaka_capture_eta_text(spec, jobs)
                await _safe_edit_message_text(
                    status_message,
                    f"{spec.title}\nAPI 議고쉶 ?꾨즺. ?띿뒪??癒쇱? 蹂대궡怨?Kiyotaka 罹≪쿂???ㅼ뿉??李띾뒗 以묒씠?? {eta_text}.",
                )
                await _safe_answer(message, f"{report}\n\n罹≪쿂???ㅼ뿉??李띻퀬 ?덈떎. {eta_text}. ?꾨즺?섎㈃ ?ъ쭊?쇰줈 ?댁뼱??蹂대궦??")
                _start_kiyotaka_capture_task(message, spec, report, focus_prices, status_message)
                return True

            await _safe_edit_message_text(
                status_message,
                f"{spec.title}\nKiyotaka API 議고쉶 ?꾨즺. {'?붿껌?濡?罹≪쿂???곗? ?딆븯??' if not capture_allowed else '釉뚮씪?곗? 罹≪쿂???곗? ?딆븯??'}",
            )
            await _safe_answer(message, report)
            await _safe_delete_message(status_message)
            return True

    if not capture_allowed:
        await _safe_answer(
            message,
            build_kiyotaka_shortcut_reply(spec, note="?붿껌?濡??ъ쭊/罹≪쿂???곗? ?딄퀬 ?띿뒪???덈궡留??④릿??"),
        )
        return True

    progress_text = (
        f"{spec.title}\n"
        "?좊ℓ媛 Kiyotaka 李⑦듃 李얘퀬 ?덈떎. 釉뚮씪?곗? fallback 紐⑤뱶??\n"
        "- ?щ낵 寃??以?n"
        "- ?덊듃留?罹≪쿂 以鍮?以?
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
            f"{spec.title}\n?좊ℓ媛 ?ㅽ겕由곗꺑? 紐?李띿뼱??留곹겕濡????梨숆꺼?붾떎.",
        )
        await _safe_answer(
            message,
            build_kiyotaka_shortcut_reply(spec, note=f"?ㅽ겕由곗꺑? 吏湲?紐?李띿뼱??留곹겕濡????蹂대궦?? ?ъ쑀: {exc}"),
        )
        return True
    except Exception:
        logger.exception("[Kiyotaka] unexpected screenshot failure for %s", spec.key)
        typing_stop.set()
        with suppress(Exception):
            await typing_task
        await _safe_edit_message_text(
            status_message,
            f"{spec.title}\n?좊ℓ媛 ?ㅽ겕由곗꺑 留뚮뱾???좉퉸 ?룰컝?몃떎. 留곹겕濡????蹂대궦??",
        )
        await _safe_answer(
            message,
            build_kiyotaka_shortcut_reply(spec, note="?ㅽ겕由곗꺑 ?앹꽦 以??덇린移??딆? ?ㅻ쪟媛 ?섏꽌 留곹겕濡????蹂대궦??"),
        )
        return True
    finally:
        typing_stop.set()
        with suppress(Exception):
            await typing_task

    caption = f"{spec.title}\n{spec.search_query} | {spec.timeframe} | {spec.view}"
    await _safe_edit_message_text(
        status_message,
        f"{spec.title}\n?좊ℓ媛 ?덊듃留?罹≪쿂?댁꽌 蹂대궡??以묒씠??",
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
            f"{spec.title}\n?ъ쭊 ?꾩넚??瑗ъ뿬???띿뒪???덈궡濡?????④릿??",
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
        raise OkxBtcAlertError("KIYOTAKA_API_KEY媛 ?놁뒿?덈떎.")

    normalized_asset = (spec.api_asset or "").strip().lower()
    if normalized_asset == "btc":
        return get_okx_btc_levels_report_with_focus_prices()
    if normalized_asset == "eth":
        return get_okx_eth_levels_report(), ()
    if normalized_asset == "bitfinex_eth":
        return get_bitfinex_eth_levels_report_with_focus_prices()
    raise OkxBtcAlertError(f"吏?먰븯吏 ?딅뒗 Kiyotaka API ?먯궛?낅땲?? {spec.api_asset}")


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
                        f"{spec.title}\nKiyotaka capture {index}/{len(jobs)}: {label}\n?⑥? {eta_text}.",
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
                await _safe_answer(message, f"{market_label} Kiyotaka 罹≪쿂 ?ㅽ뙣 ({label}): {exc}")
                continue
            except Exception:
                logger.exception("[Kiyotaka] unexpected background screenshot failure for %s job=%s", spec.key, label)
                await _safe_answer(message, f"{market_label} Kiyotaka 罹≪쿂?먯꽌 ?덇린移??딆? ?ㅻ쪟媛 ?щ떎 ({label}).")
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
                f"{spec.title}\n罹≪쿂??留뚮뱾?덉?留??붾젅洹몃옩 ?ъ쭊 ?꾩넚???ㅽ뙣?덈떎.",
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
    return "kiyotaka" in normalized and ("罹≪쿂" in source_text or "capture" in normalized or "?ㅻ뜑踰? in source_text)


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
        logger.error("[Grandma Reaction] failed for chat %s, message %s: %s", message.chat.id, message.message_id, last_error)
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
        return build_grandma_quick_reply("?좊ℓ")

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
        "?뚭쿋?? 鍮꾪듃留μ뒪 湲곗?? 鍮쇨퀬 留먰븯留?\n\n"
        "?ㅻ쭔 吏湲??좊ℓ?쒗뀒 遺숈뼱 ?덈뒗 ?ㅼ떆媛??④린 諛⑺뼢 ?꾧뎄??BitMEX 履쎌씠?? 洹멸구 鍮쇰㈃ 濡??륁쓣 ?レ옄濡??⑥젙?섍릿 ?대졄?? "
        "OKX ?ㅻ뜑遺??덊듃留듭쑝濡?蹂대젮硫?`okx 鍮꾪듃 諛대뱶 ?뺤씤`泥섎읆 臾쇱뼱蹂대㈃ 洹?湲곗??쇰줈 ?ㅼ떆 蹂????덈떎."
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

