from dataclasses import dataclass
import unicodedata


KIYOTAKA_CHART_URL = "https://chart.kiyotaka.ai/"


@dataclass(frozen=True)
class KiyotakaShortcutSpec:
    key: str
    title: str
    search_query: str
    result_symbol: str
    result_exchange: str
    result_index: int
    timeframe: str
    view: str
    chart_drag_y: int = 0
    chart_url: str = KIYOTAKA_CHART_URL
    api_asset: str | None = None
    capture_with_api: bool = False
    split_capture_with_api: bool = False
    capture_fallback_targets: tuple[tuple[str, str, str], ...] = ()


_SHORTCUT_SPECS = {
    "okxbtcusdtp": KiyotakaShortcutSpec(
        key="okxbtcusdtp",
        title="OKX BTC-USDT PERP 히트맵",
        search_query="BTC-USDT",
        result_symbol="BTCUSDT",
        result_exchange="OKX.F",
        result_index=1,
        timeframe="1m",
        view="Heatmap",
        chart_drag_y=260,
        api_asset="btc",
        capture_with_api=True,
        split_capture_with_api=True,
    ),
    "okxbtcusdtpwide": KiyotakaShortcutSpec(
        key="okxbtcusdtpwide",
        title="OKX BTC-USDT PERP 히트맵 와이드",
        search_query="BTC-USDT",
        result_symbol="BTCUSDT",
        result_exchange="OKX.F",
        result_index=1,
        timeframe="1m",
        view="Heatmap",
        chart_drag_y=420,
        api_asset="btc",
        capture_with_api=True,
        split_capture_with_api=True,
    ),
    "bitfinexethusdt": KiyotakaShortcutSpec(
        key="bitfinexethusdt",
        title="BITFINEX ETHUSDT 진한 오더벽",
        search_query="ETHUSDT",
        result_symbol="ETHUSDT",
        result_exchange="BITFINEX",
        result_index=1,
        timeframe="5m",
        view="Heatmap",
        chart_drag_y=260,
        api_asset="bitfinex_eth",
        capture_with_api=True,
    ),
}

_SHORTCUT_ALIASES = {
    "okxbtcusdp": "okxbtcusdtp",
    "okxbtcusdpwide": "okxbtcusdtpwide",
    "bipaeth": "bitfinexethusdt",
    "비파 이더": "bitfinexethusdt",
    "비파이더": "bitfinexethusdt",
    "비트파이넥스 이더": "bitfinexethusdt",
    "bitfinex eth": "bitfinexethusdt",
    "bitfinex ethusdt": "bitfinexethusdt",
}


def get_kiyotaka_shortcut_spec(text: str) -> KiyotakaShortcutSpec | None:
    normalized = _normalize(text)
    if normalized.startswith("/"):
        normalized = normalized[1:]
    normalized = normalized.split("@", 1)[0]
    normalized = _SHORTCUT_ALIASES.get(normalized, normalized)
    if normalized in _SHORTCUT_SPECS:
        return _SHORTCUT_SPECS[normalized]

    head = normalized.split(maxsplit=1)[0]
    head = _SHORTCUT_ALIASES.get(head, head)
    if head in _SHORTCUT_SPECS:
        return _SHORTCUT_SPECS[head]

    for alias, key in sorted(_SHORTCUT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if normalized.startswith(f"{alias} "):
            return _SHORTCUT_SPECS[key]
    return None


def build_kiyotaka_shortcut_reply(spec: KiyotakaShortcutSpec, *, note: str | None = None) -> str:
    lines = [
        spec.title,
        spec.chart_url,
        "",
        f"검색: {spec.search_query} -> {spec.result_symbol} / {spec.result_exchange}",
        f"설정: {spec.timeframe} / {spec.view}",
    ]
    if note:
        lines.extend(["", f"메모: {note}"])
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip().lower()
