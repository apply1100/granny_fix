import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


BITMEX_TRADE_API_URL = "https://www.bitmex.com/api/v1/trade"
WATCH_STATE_PATH = Path(__file__).resolve().parents[1] / "memory" / "bitmex_whale_watch.json"
SEOUL_TZ = timezone(timedelta(hours=9), "KST")
MAX_STORED_IDS = 200
MAX_WATCHER_LOOKBACK_SECONDS = 300
AGGREGATION_WINDOW_SECONDS = 2
_DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class BitmexWatcherError(RuntimeError):
    """Raised when BitMEX whale watcher data cannot be fetched."""


@dataclass
class BitmexWhaleTrade:
    trade_id: str
    timestamp: str
    side: str
    size: int
    price: float
    symbol: str
    trade_count: int = 1
    component_ids: tuple[str, ...] = ()

    @property
    def local_time(self) -> str:
        utc_dt = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        return utc_dt.astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M:%S KST")


def get_delayed_alert_threshold_seconds() -> int:
    return max(get_poll_interval_seconds() * 2, 45)


def get_trade_delay_seconds(trade: BitmexWhaleTrade, *, now_utc: datetime | None = None) -> int:
    trade_time = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
    comparison_time = now_utc or datetime.now(timezone.utc)
    delay_seconds = int((comparison_time - trade_time).total_seconds())
    return max(delay_seconds, 0)


def is_delayed_trade_alert(trade: BitmexWhaleTrade, *, now_utc: datetime | None = None) -> bool:
    return get_trade_delay_seconds(trade, now_utc=now_utc) > get_delayed_alert_threshold_seconds()


def get_trade_threshold() -> int:
    return int(os.getenv("BITMEX_WHALE_TRADE_THRESHOLD", "1000000"))


def get_poll_interval_seconds() -> int:
    return int(os.getenv("BITMEX_WHALE_POLL_INTERVAL_SECONDS", "15"))


def auto_register_on_market_interaction_enabled() -> bool:
    value = os.getenv("BITMEX_AUTO_REGISTER_ON_MARKET_INTERACTION", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def format_trade_threshold_label() -> str:
    threshold = get_trade_threshold()
    if threshold >= 1_000_000 and threshold % 1_000_000 == 0:
        return f"{threshold // 1_000_000}M+"
    if threshold >= 1_000 and threshold % 1_000 == 0:
        return f"{threshold // 1_000}K+"
    return f"{threshold:,}+"


def get_configured_subscription_chat_ids() -> list[int]:
    raw_value = os.getenv("BITMEX_ALERT_CHAT_IDS", "")
    if not raw_value.strip():
        return []

    chat_ids: list[int] = []
    for token in raw_value.replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            chat_ids.append(int(token))
        except ValueError:
            continue
    return list(dict.fromkeys(chat_ids))


def get_runtime_subscription_chat_ids() -> list[int]:
    return list(_load_state()["chat_ids"])


def has_configured_subscription(chat_id: int) -> bool:
    return chat_id in set(get_configured_subscription_chat_ids())


def has_runtime_subscription(chat_id: int) -> bool:
    return chat_id in set(get_runtime_subscription_chat_ids())


def has_subscription(chat_id: int) -> bool:
    return chat_id in set(list_subscriptions())


def ensure_subscription_for_market_interaction(chat_id: int) -> bool:
    if not auto_register_on_market_interaction_enabled():
        return False
    if has_subscription(chat_id):
        return False
    return add_subscription(chat_id)


def add_subscription(chat_id: int) -> bool:
    state = _load_state()
    existing_ids = set(list_subscriptions())
    if chat_id in existing_ids:
        return False

    state["chat_ids"].append(chat_id)
    if len(_combine_chat_ids(state["chat_ids"], get_configured_subscription_chat_ids())) == 1:
        state["primed"] = False
        state["seen_trade_ids"] = []
    _save_state(state)
    return True


def remove_subscription(chat_id: int) -> bool:
    state = _load_state()
    if chat_id not in state["chat_ids"]:
        return False

    state["chat_ids"] = [item for item in state["chat_ids"] if item != chat_id]
    if not _combine_chat_ids(state["chat_ids"], get_configured_subscription_chat_ids()):
        state["primed"] = False
        state["seen_trade_ids"] = []
    _save_state(state)
    return True


def list_subscriptions() -> list[int]:
    state = _load_state()
    return _combine_chat_ids(state["chat_ids"], get_configured_subscription_chat_ids())


def fetch_new_whale_trades() -> list[BitmexWhaleTrade]:
    state = _load_state()
    if not list_subscriptions():
        return []

    since = state.get("last_fetched_at") if state["primed"] else None
    recent_trades = _fetch_recent_trades(since=since)
    state["last_fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    aggregated = _aggregate_trades(recent_trades)
    whale_trades = [trade for trade in aggregated if trade.size >= get_trade_threshold()]
    whale_trades.sort(key=lambda trade: trade.timestamp)

    if not state["primed"]:
        state["primed"] = True
        all_ids: list[str] = []
        for trade in whale_trades:
            all_ids.extend(_get_individual_trade_ids(trade))
        state["seen_trade_ids"] = all_ids[-MAX_STORED_IDS:]
        _save_state(state)
        return []

    seen_ids = set(state["seen_trade_ids"])
    new_trades = [
        trade for trade in whale_trades
        if not all(tid in seen_ids for tid in _get_individual_trade_ids(trade))
    ]
    if not new_trades:
        _save_state(state)
        return []

    new_component_ids: list[str] = []
    for trade in new_trades:
        new_component_ids.extend(_get_individual_trade_ids(trade))
    updated_ids = state["seen_trade_ids"] + new_component_ids
    state["seen_trade_ids"] = list(dict.fromkeys(updated_ids))[-MAX_STORED_IDS:]
    _save_state(state)
    return new_trades


def format_trade_alert_header(
    trade: BitmexWhaleTrade,
    *,
    now_utc: datetime | None = None,
) -> str:
    threshold_label = format_trade_threshold_label()
    delay_seconds = get_trade_delay_seconds(trade, now_utc=now_utc)
    delayed = delay_seconds > get_delayed_alert_threshold_seconds()
    title = (
        f"BitMEX {threshold_label} 딜레이 된 알람"
        if delayed
        else f"BitMEX {threshold_label} 자동 알림"
    )
    delay_line = f"\n- 지연 감지: {delay_seconds}초 늦게 잡힘" if delayed else ""
    aggregation_note = f" [{trade.trade_count}건 합산]" if trade.trade_count > 1 else ""
    return (
        f"{title}\n"
        f"- 체결 시각: {trade.local_time}\n"
        f"- 마켓: {trade.symbol}\n"
        f"- 체결 방향: {trade.side}\n"
        f"- 체결 크기: {trade.size:,} contracts (~${trade.size:,}){aggregation_note}\n"
        f"- 체결 가격: ${trade.price:,.2f}"
        f"{delay_line}"
    )


def get_recent_whale_report_limit() -> int:
    return max(1, int(os.getenv("BITMEX_WHALE_REPORT_LIMIT", "5")))


def get_recent_whale_trades_report() -> str:
    recent_trades = _fetch_recent_trades()
    aggregated = _aggregate_trades(recent_trades)
    whale_trades = [trade for trade in aggregated if trade.size >= get_trade_threshold()]
    whale_trades.sort(key=lambda trade: trade.timestamp, reverse=True)

    threshold_label = format_trade_threshold_label()
    fetch_count = int(os.getenv("BITMEX_WHALE_FETCH_COUNT", "200"))
    limit = get_recent_whale_report_limit()
    now_local = datetime.now(timezone.utc).astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M:%S KST")
    lines = [
        f"BitMEX {threshold_label} 최근 고래 체결 내역",
        f"- 조회 시각: {now_local}",
        f"- 기준 체결: {get_trade_threshold():,} contracts ({threshold_label})",
        f"- 조회 범위: 최근 {fetch_count}건 체결",
    ]

    if not whale_trades:
        lines.append(f"- 최근 조회 범위에서는 {threshold_label} 체결이 아직 없습니다.")
        return "\n".join(lines)

    lines.append("")
    for index, trade in enumerate(whale_trades[:limit], start=1):
        side_label = _format_trade_side_label(trade.side)
        agg_label = f" [{trade.trade_count}건]" if trade.trade_count > 1 else ""
        lines.append(
            f"{index}. {trade.local_time} | {side_label} | {trade.size:,} contracts{agg_label} | ${trade.price:,.2f}"
        )

    if len(whale_trades) > limit:
        lines.append("")
        lines.append(f"- 메모: 최근 {limit}건만 표시했습니다.")

    return "\n".join(lines)


def _fetch_recent_trades(*, since: str | None = None) -> list[BitmexWhaleTrade]:
    params = {
        "symbol": "XBTUSD",
        "count": int(os.getenv("BITMEX_WHALE_FETCH_COUNT", "200")),
        "reverse": "true",
    }
    if since:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        max_lookback = datetime.now(timezone.utc) - timedelta(seconds=MAX_WATCHER_LOOKBACK_SECONDS)
        effective_since = max(since_dt, max_lookback)
        params["startTime"] = effective_since.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["count"] = 1000
    url = f"{BITMEX_TRADE_API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with _DIRECT_HTTP_OPENER.open(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise BitmexWatcherError(f"BitMEX trade API 호출 실패: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise BitmexWatcherError("BitMEX trade API에 연결하지 못했습니다.") from exc
    except json.JSONDecodeError as exc:
        raise BitmexWatcherError("BitMEX trade 응답을 해석하지 못했습니다.") from exc

    return [
        BitmexWhaleTrade(
            trade_id=str(item.get("trdMatchID", "")),
            timestamp=str(item.get("timestamp", "")),
            side=str(item.get("side", "Unknown")),
            size=int(item.get("size", 0)),
            price=float(item.get("price", 0)),
            symbol=str(item.get("symbol", "XBTUSD")),
        )
        for item in payload
        if item.get("trdMatchID") and item.get("timestamp")
    ]


def _load_state() -> dict:
    if not WATCH_STATE_PATH.exists():
        return {"chat_ids": [], "seen_trade_ids": [], "primed": False}

    try:
        return json.loads(WATCH_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"chat_ids": [], "seen_trade_ids": [], "primed": False}


def _save_state(state: dict) -> None:
    WATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCH_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _combine_chat_ids(*chat_id_lists: list[int]) -> list[int]:
    merged: list[int] = []
    for chat_id_list in chat_id_lists:
        for chat_id in chat_id_list:
            if chat_id not in merged:
                merged.append(chat_id)
    return merged


def _format_trade_side_label(side: str) -> str:
    normalized = (side or "").strip().lower()
    if normalized == "buy":
        return "매수"
    if normalized == "sell":
        return "매도"
    return side or "알 수 없음"


def _get_individual_trade_ids(trade: BitmexWhaleTrade) -> list[str]:
    if trade.component_ids:
        return list(trade.component_ids)
    return [trade.trade_id]


def _aggregate_trades(trades: list[BitmexWhaleTrade]) -> list[BitmexWhaleTrade]:
    """Group trades by (side, symbol) within a short time window and sum sizes.

    This mimics how Coinalyze aggregates fills from the same large market order
    that BitMEX splits into multiple individual trade matches.
    """
    if not trades:
        return []

    sorted_trades = sorted(trades, key=lambda t: (t.symbol, t.timestamp, t.side))

    groups: list[list[BitmexWhaleTrade]] = []
    current_group: list[BitmexWhaleTrade] = [sorted_trades[0]]

    for trade in sorted_trades[1:]:
        anchor = current_group[0]
        same_side = trade.side == anchor.side
        same_symbol = trade.symbol == anchor.symbol

        anchor_time = datetime.fromisoformat(anchor.timestamp.replace("Z", "+00:00"))
        cur_time = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
        within_window = abs((cur_time - anchor_time).total_seconds()) <= AGGREGATION_WINDOW_SECONDS

        if same_side and same_symbol and within_window:
            current_group.append(trade)
        else:
            groups.append(current_group)
            current_group = [trade]

    groups.append(current_group)

    result: list[BitmexWhaleTrade] = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
            continue

        total_size = sum(t.size for t in group)
        total_value = sum(t.size * t.price for t in group)
        avg_price = total_value / total_size if total_size else 0.0
        component_ids = tuple(t.trade_id for t in group)
        result.append(BitmexWhaleTrade(
            trade_id="+".join(component_ids[:5]),
            timestamp=group[0].timestamp,
            side=group[0].side,
            size=total_size,
            price=round(avg_price, 2),
            symbol=group[0].symbol,
            trade_count=len(group),
            component_ids=component_ids,
        ))

    return result
