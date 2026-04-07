import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BITMEX_TRADE_API_URL = "https://www.bitmex.com/api/v1/trade"
WATCH_STATE_PATH = Path(__file__).resolve().parents[1] / "memory" / "bitmex_whale_watch.json"
SEOUL_TZ = ZoneInfo("Asia/Seoul")
MAX_STORED_IDS = 200


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

    @property
    def local_time(self) -> str:
        utc_dt = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        return utc_dt.astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M:%S KST")


def get_trade_threshold() -> int:
    return int(os.getenv("BITMEX_WHALE_TRADE_THRESHOLD", "1000000"))


def get_poll_interval_seconds() -> int:
    return int(os.getenv("BITMEX_WHALE_POLL_INTERVAL_SECONDS", "15"))


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

    recent_trades = _fetch_recent_trades()
    whale_trades = [trade for trade in recent_trades if trade.size >= get_trade_threshold()]
    whale_trades.sort(key=lambda trade: trade.timestamp)

    if not state["primed"]:
        state["primed"] = True
        state["seen_trade_ids"] = [trade.trade_id for trade in whale_trades][-MAX_STORED_IDS:]
        _save_state(state)
        return []

    seen_ids = set(state["seen_trade_ids"])
    new_trades = [trade for trade in whale_trades if trade.trade_id not in seen_ids]
    if not new_trades:
        return []

    updated_ids = state["seen_trade_ids"] + [trade.trade_id for trade in new_trades]
    state["seen_trade_ids"] = list(dict.fromkeys(updated_ids))[-MAX_STORED_IDS:]
    _save_state(state)
    return new_trades


def format_trade_alert_header(trade: BitmexWhaleTrade) -> str:
    threshold_label = format_trade_threshold_label()
    return (
        f"BitMEX {threshold_label} 자동 알림\n"
        f"- 체결 시각: {trade.local_time}\n"
        f"- 마켓: {trade.symbol}\n"
        f"- 체결 방향: {trade.side}\n"
        f"- 체결 크기: {trade.size:,} contracts (~${trade.size:,})\n"
        f"- 체결 가격: ${trade.price:,.2f}"
    )


def _fetch_recent_trades() -> list[BitmexWhaleTrade]:
    params = {
        "symbol": "XBTUSD",
        "count": int(os.getenv("BITMEX_WHALE_FETCH_COUNT", "50")),
        "reverse": "true",
    }
    url = f"{BITMEX_TRADE_API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
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
