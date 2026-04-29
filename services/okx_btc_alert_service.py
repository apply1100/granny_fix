import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

KIYOTAKA_POINTS_API_URL = "https://api.kiyotaka.ai/v1/points"
OKX_BTC_ALERT_STATE_PATH = Path(__file__).resolve().parents[1] / "memory" / "okx_btc_alert_watch.json"
SEOUL_TZ = timezone(timedelta(hours=9), "KST")
_DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OkxBtcAlertError(RuntimeError):
    """Raised when OKX BTC alert data cannot be fetched or parsed."""


@dataclass(frozen=True)
class OkxBtcAlertLevel:
    side: str
    price: float
    size: float
    snapshot_timestamp: int
    reference_price: float
    event: str = "new"
    previous_size: float | None = None

    @property
    def local_time(self) -> str:
        utc_dt = datetime.fromtimestamp(self.snapshot_timestamp, tz=timezone.utc)
        return utc_dt.astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M:%S KST")

    @property
    def distance_pct(self) -> float:
        if not self.reference_price:
            return 0.0
        return ((self.price / self.reference_price) - 1.0) * 100.0

    @property
    def level_key(self) -> str:
        return f"{self.side}:{self.price:.2f}"


@dataclass(frozen=True)
class OkxBtcHeatmapBand:
    side: str
    price_min: float
    price_max: float
    snapshot_count: int
    sample_count: int
    max_size: float
    reference_price: float
    latest_snapshot_timestamp: int
    event: str = "new"
    previous_max_size: float | None = None

    @property
    def local_time(self) -> str:
        utc_dt = datetime.fromtimestamp(self.latest_snapshot_timestamp, tz=timezone.utc)
        return utc_dt.astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M:%S KST")

    @property
    def center_price(self) -> float:
        return (self.price_min + self.price_max) / 2.0

    @property
    def distance_pct(self) -> float:
        if not self.reference_price:
            return 0.0
        return ((self.center_price / self.reference_price) - 1.0) * 100.0

    @property
    def persistence_ratio(self) -> float:
        if self.sample_count <= 0:
            return 0.0
        return self.snapshot_count / self.sample_count

    @property
    def price_label(self) -> str:
        if math.isclose(self.price_min, self.price_max):
            return _format_price_short(self.price_min)
        return f"{_format_price_short(self.price_min, mode='down')}-{_format_price_short(self.price_max, mode='up')}"


@dataclass(frozen=True)
class OkxBtcHeatmapBandScan:
    bands: tuple[OkxBtcHeatmapBand, ...]
    snapshot_count: int
    reference_price: float
    latest_snapshot_timestamp: int


@dataclass(frozen=True)
class OkxHeatmapMarket:
    asset_code: str
    asset_label: str
    display_name: str
    exchange_id: str
    raw_symbol: str
    band_min_size: float
    band_merge_gap: float
    band_min_snapshots: int | None = None
    band_min_persistence_ratio: float = 0.0
    block_size: int | None = None


def get_okx_btc_poll_interval_seconds() -> int:
    configured_seconds = int(os.getenv("OKX_BTC_ALERT_POLL_INTERVAL_SECONDS", "3600"))
    return min(max(3600, configured_seconds), 14400)


def get_okx_btc_min_size() -> float:
    return float(os.getenv("OKX_BTC_ALERT_MIN_SIZE", "0.1"))


def get_okx_btc_min_size_change() -> float:
    return float(os.getenv("OKX_BTC_ALERT_MIN_SIZE_CHANGE", "0.1"))


def get_okx_btc_max_distance_pct() -> float:
    return float(os.getenv("OKX_BTC_ALERT_MAX_DISTANCE_PCT", "15"))


def get_okx_btc_report_limit() -> int:
    return max(1, int(os.getenv("OKX_BTC_ALERT_REPORT_LIMIT", "6")))


def get_bitfinex_eth_compact_report_limit() -> int:
    return max(1, int(os.getenv("BITFINEX_ETH_COMPACT_REPORT_LIMIT", "3")))


def get_okx_btc_block_size() -> int:
    return int(os.getenv("OKX_BTC_ALERT_BLOCK_SIZE", "5"))


def get_bitfinex_eth_block_size() -> int:
    return int(os.getenv("BITFINEX_ETH_BLOCK_SIZE", "1"))


def get_okx_btc_max_depth() -> int:
    return int(os.getenv("OKX_BTC_ALERT_MAX_DEPTH", "4000"))


def get_okx_btc_lookback_minutes() -> int:
    return max(60, int(os.getenv("OKX_BTC_ALERT_LOOKBACK_MINUTES", "120")))


def get_okx_btc_band_scan_period_seconds() -> int:
    return max(1800, int(os.getenv("OKX_BTC_BAND_SCAN_PERIOD_SECONDS", "21600")))


def get_okx_btc_alert_band_scan_period_seconds() -> int:
    return max(3600, int(os.getenv("OKX_BTC_ALERT_BAND_SCAN_PERIOD_SECONDS", "14400")))


def get_okx_btc_band_min_size() -> float:
    return float(os.getenv("OKX_BTC_BAND_MIN_SIZE", "0.1"))


def get_okx_eth_band_min_size() -> float:
    return float(os.getenv("OKX_ETH_BAND_MIN_SIZE", "5"))


def get_bitfinex_eth_band_min_size() -> float:
    return float(os.getenv("BITFINEX_ETH_BAND_MIN_SIZE", "10"))


def get_okx_btc_band_min_distance_pct() -> float:
    return float(os.getenv("OKX_BTC_BAND_MIN_DISTANCE_PCT", "0.5"))


def get_okx_btc_band_max_distance_pct() -> float:
    return float(os.getenv("OKX_BTC_BAND_MAX_DISTANCE_PCT", "40"))


def get_okx_btc_band_max_depth() -> int:
    return int(os.getenv("OKX_BTC_BAND_MAX_DEPTH", "6000"))


def get_okx_btc_band_merge_gap() -> float:
    return float(os.getenv("OKX_BTC_BAND_MERGE_GAP", "50"))


def get_okx_eth_band_merge_gap() -> float:
    return float(os.getenv("OKX_ETH_BAND_MERGE_GAP", "5"))


def get_bitfinex_eth_band_merge_gap() -> float:
    return float(os.getenv("BITFINEX_ETH_BAND_MERGE_GAP", "1"))


def get_bitfinex_eth_compact_max_band_width() -> float:
    return float(os.getenv("BITFINEX_ETH_COMPACT_MAX_BAND_WIDTH", "30"))


def get_okx_btc_band_min_snapshots() -> int:
    return max(2, int(os.getenv("OKX_BTC_BAND_MIN_SNAPSHOTS", "2")))


def get_bitfinex_eth_band_min_snapshots() -> int:
    return max(2, int(os.getenv("BITFINEX_ETH_BAND_MIN_SNAPSHOTS", "10")))


def get_bitfinex_eth_band_min_persistence_ratio() -> float:
    return min(1.0, max(0.0, float(os.getenv("BITFINEX_ETH_BAND_MIN_PERSISTENCE_RATIO", "0.50"))))


def get_okx_btc_alert_band_min_snapshots() -> int:
    return max(6, int(os.getenv("OKX_BTC_ALERT_BAND_MIN_SNAPSHOTS", "12")))


def get_okx_btc_alert_band_min_persistence_ratio() -> float:
    return max(0.0, float(os.getenv("OKX_BTC_ALERT_BAND_MIN_PERSISTENCE_RATIO", "0.05")))


def get_okx_btc_alert_band_min_size_change() -> float:
    return float(os.getenv("OKX_BTC_ALERT_BAND_MIN_SIZE_CHANGE", "0.1"))


def get_okx_btc_alert_max_band_age_seconds() -> int:
    return max(0, int(os.getenv("OKX_BTC_ALERT_MAX_BAND_AGE_SECONDS", "180")))


def _get_okx_heatmap_market(asset: str) -> OkxHeatmapMarket:
    normalized = (asset or "").strip().lower()
    if normalized == "eth":
        return OkxHeatmapMarket(
            asset_code="eth",
            asset_label="ETH",
            display_name="OKX ETH",
            exchange_id="OKEX_SWAP",
            raw_symbol="ETH-USDT-SWAP",
            band_min_size=get_okx_eth_band_min_size(),
            band_merge_gap=get_okx_eth_band_merge_gap(),
        )
    if normalized == "btc":
        return OkxHeatmapMarket(
            asset_code="btc",
            asset_label="BTC",
            display_name="OKX BTC",
            exchange_id="OKEX_SWAP",
            raw_symbol="BTC-USDT-SWAP",
            band_min_size=get_okx_btc_band_min_size(),
            band_merge_gap=get_okx_btc_band_merge_gap(),
        )
    raise OkxBtcAlertError(f"지원하지 않는 OKX 자산입니다: {asset}")


def _get_bitfinex_heatmap_market(asset: str) -> OkxHeatmapMarket:
    normalized = (asset or "").strip().lower()
    if normalized == "eth":
        return OkxHeatmapMarket(
            asset_code="eth",
            asset_label="ETH",
            display_name="BITFINEX ETH",
            exchange_id="BITFINEX",
            raw_symbol="ETHUST",
            band_min_size=get_bitfinex_eth_band_min_size(),
            band_merge_gap=get_bitfinex_eth_band_merge_gap(),
            band_min_snapshots=get_bitfinex_eth_band_min_snapshots(),
            band_min_persistence_ratio=get_bitfinex_eth_band_min_persistence_ratio(),
            block_size=get_bitfinex_eth_block_size(),
        )
    raise OkxBtcAlertError(f"지원하지 않는 BITFINEX 자산입니다: {asset}")


def get_okx_btc_delayed_alert_threshold_seconds() -> int:
    return max(get_okx_btc_poll_interval_seconds() * 2, 90)


def get_okx_btc_snapshot_delay_seconds(snapshot_timestamp: int, *, now_utc: datetime | None = None) -> int:
    comparison_time = now_utc or datetime.now(timezone.utc)
    snapshot_time = datetime.fromtimestamp(snapshot_timestamp, tz=timezone.utc)
    return max(int((comparison_time - snapshot_time).total_seconds()), 0)


def is_delayed_okx_btc_alert(level: OkxBtcAlertLevel, *, now_utc: datetime | None = None) -> bool:
    return get_okx_btc_snapshot_delay_seconds(level.snapshot_timestamp, now_utc=now_utc) > get_okx_btc_delayed_alert_threshold_seconds()


def get_configured_okx_btc_subscription_chat_ids() -> list[int]:
    raw_value = os.getenv("OKX_BTC_ALERT_CHAT_IDS", "")
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


def get_runtime_okx_btc_subscription_chat_ids() -> list[int]:
    return list(_load_state()["chat_ids"])


def has_configured_okx_btc_subscription(chat_id: int) -> bool:
    return chat_id in set(get_configured_okx_btc_subscription_chat_ids())


def has_runtime_okx_btc_subscription(chat_id: int) -> bool:
    return chat_id in set(get_runtime_okx_btc_subscription_chat_ids())


def has_okx_btc_subscription(chat_id: int) -> bool:
    return chat_id in set(list_okx_btc_subscriptions())


def add_okx_btc_subscription(chat_id: int) -> bool:
    state = _load_state()
    existing_ids = set(list_okx_btc_subscriptions())
    if chat_id in existing_ids:
        return False

    state["chat_ids"].append(chat_id)
    if len(_combine_chat_ids(state["chat_ids"], get_configured_okx_btc_subscription_chat_ids())) == 1:
        state["primed"] = False
        state["active_levels"] = {}
        state["active_bands"] = {}
    _save_state(state)
    return True


def remove_okx_btc_subscription(chat_id: int) -> bool:
    state = _load_state()
    if chat_id not in state["chat_ids"]:
        return False

    state["chat_ids"] = [item for item in state["chat_ids"] if item != chat_id]
    if not _combine_chat_ids(state["chat_ids"], get_configured_okx_btc_subscription_chat_ids()):
        state["primed"] = False
        state["active_levels"] = {}
        state["active_bands"] = {}
    _save_state(state)
    return True


def list_okx_btc_subscriptions() -> list[int]:
    state = _load_state()
    return _combine_chat_ids(state["chat_ids"], get_configured_okx_btc_subscription_chat_ids())


def fetch_new_okx_btc_levels() -> list[OkxBtcHeatmapBand]:
    state = _load_state()
    if not list_okx_btc_subscriptions():
        return []

    scan = fetch_okx_btc_alert_heatmap_band_scan()
    current_bands = list(_filter_recent_confirmed_alert_bands(scan))
    current_band_map = {_get_watch_band_key(band): band for band in current_bands}

    if not state["primed"]:
        state["primed"] = True
        state["active_levels"] = {}
        state["active_bands"] = _serialize_active_bands(current_band_map)
        _save_state(state)
        return []

    previous_bands: dict[str, dict] = state.get("active_bands", {})
    new_bands: list[OkxBtcHeatmapBand] = []
    for band_key, band in current_band_map.items():
        previous = previous_bands.get(band_key)
        if previous is None:
            nearby_previous = _find_nearby_previous_band(band, previous_bands)
            if nearby_previous is None:
                new_bands.append(band)
            continue

        previous_max_size = float(previous.get("max_size", 0.0))
        if band.max_size - previous_max_size >= get_okx_btc_alert_band_min_size_change():
            new_bands.append(
                replace(
                    band,
                    event="grew",
                    previous_max_size=previous_max_size,
                )
            )

    state["active_levels"] = {}
    state["active_bands"] = _serialize_active_bands(current_band_map)
    _save_state(state)
    return sorted(
        new_bands,
        key=lambda item: (item.persistence_ratio, item.max_size, -abs(item.distance_pct)),
        reverse=True,
    )


def fetch_current_okx_btc_levels() -> list[OkxBtcAlertLevel]:
    point = _fetch_latest_snapshot_point()
    return _extract_significant_levels(point)


def get_okx_btc_levels_report() -> str:
    scan = fetch_okx_btc_heatmap_band_scan()
    return _build_okx_levels_report(scan, market=_get_okx_heatmap_market("btc"))


def get_okx_btc_levels_report_with_focus_prices() -> tuple[str, tuple[float, ...]]:
    market = _get_okx_heatmap_market("btc")
    scan = fetch_okx_btc_alert_heatmap_band_scan()
    visible_scan = replace(scan, bands=_filter_recent_confirmed_alert_bands(scan))
    return _build_okx_levels_report(visible_scan, market=market), _get_okx_report_focus_prices(visible_scan)


def get_okx_eth_levels_report() -> str:
    scan = fetch_okx_eth_heatmap_band_scan()
    return _build_okx_levels_report(scan, market=_get_okx_heatmap_market("eth"))


def get_bitfinex_eth_levels_report() -> str:
    report, _focus_prices = get_bitfinex_eth_levels_report_with_focus_prices()
    return report


def get_bitfinex_eth_levels_report_with_focus_prices() -> tuple[str, tuple[float, ...]]:
    market = _get_bitfinex_heatmap_market("eth")
    scan = _fetch_current_order_wall_scan(market)
    return _build_compact_levels_report(scan, market=market), _get_compact_report_focus_prices(scan)


def _build_compact_levels_report(scan: OkxBtcHeatmapBandScan, *, market: OkxHeatmapMarket) -> str:
    ask_bands, bid_bands = _get_compact_report_bands(scan)
    limit = get_bitfinex_eth_compact_report_limit()
    lines = [market.display_name, ""]

    lines.append("위에:")
    lines.extend(_format_compact_band_lines(ask_bands[:limit], asset_label=market.asset_label))
    lines.append("")
    lines.append(f"현재가: {_format_price_plain(scan.reference_price)}")
    lines.append("")
    lines.append("밑에:")
    lines.extend(_format_compact_band_lines(bid_bands[:limit], asset_label=market.asset_label))

    return "\n".join(lines)


def _get_compact_report_bands(scan: OkxBtcHeatmapBandScan) -> tuple[list[OkxBtcHeatmapBand], list[OkxBtcHeatmapBand]]:
    limit = get_bitfinex_eth_compact_report_limit()
    ask_bands = _pick_strongest_compact_bands((band for band in scan.bands if band.side == "ask"), limit=limit)
    bid_bands = _pick_strongest_compact_bands((band for band in scan.bands if band.side == "bid"), limit=limit)
    ask_bands = sorted(ask_bands, key=lambda band: band.center_price, reverse=True)
    bid_bands = sorted(bid_bands, key=lambda band: band.center_price, reverse=True)
    return ask_bands, bid_bands


def _pick_strongest_compact_bands(
    bands: object,
    *,
    limit: int,
) -> list[OkxBtcHeatmapBand]:
    candidates = list(bands)
    max_width = get_bitfinex_eth_compact_max_band_width()
    narrow_candidates = [
        band for band in candidates if (band.price_max - band.price_min) <= max_width
    ]
    if narrow_candidates:
        candidates = narrow_candidates

    return sorted(
        candidates,
        key=lambda band: (band.max_size, band.persistence_ratio, band.snapshot_count, -abs(band.distance_pct)),
        reverse=True,
    )[:limit]


def _get_compact_report_focus_prices(scan: OkxBtcHeatmapBandScan) -> tuple[float, ...]:
    ask_bands, bid_bands = _get_compact_report_bands(scan)
    limit = get_bitfinex_eth_compact_report_limit()
    prices = [scan.reference_price]
    for band in [*ask_bands[:limit], *bid_bands[:limit]]:
        prices.extend([band.price_min, band.price_max])

    unique_prices: list[float] = []
    for price in prices:
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if not any(math.isclose(value, existing, rel_tol=0.0, abs_tol=0.01) for existing in unique_prices):
            unique_prices.append(value)
    return tuple(unique_prices)


def _get_okx_report_focus_prices(scan: OkxBtcHeatmapBandScan) -> tuple[float, ...]:
    prices = [scan.reference_price]
    ranked_bands = sorted(
        scan.bands,
        key=lambda band: (band.max_size, band.persistence_ratio, band.snapshot_count, -abs(band.distance_pct)),
        reverse=True,
    )
    for band in ranked_bands[: get_okx_btc_report_limit()]:
        prices.extend([band.price_min, band.price_max])

    unique_prices: list[float] = []
    for price in prices:
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if not any(math.isclose(value, existing, rel_tol=0.0, abs_tol=0.01) for existing in unique_prices):
            unique_prices.append(value)
    return tuple(unique_prices)


def _format_compact_band_lines(bands: list[OkxBtcHeatmapBand], *, asset_label: str) -> list[str]:
    if not bands:
        return ["없음"]
    return [
        f"{index}. {_format_band_price_plain(band)} ({_format_size_plain(band.max_size)} {asset_label})"
        for index, band in enumerate(bands, start=1)
    ]


def _build_okx_levels_report(scan: OkxBtcHeatmapBandScan, *, market: OkxHeatmapMarket) -> str:
    ask_bands = [band for band in scan.bands if band.side == "ask"]
    bid_bands = [band for band in scan.bands if band.side == "bid"]
    lines = [
        f"{market.display_name} 딥 히트맵 밴드",
        f"- 시장: {market.display_name.split()[0]} {market.raw_symbol}",
        f"- 기준 시각: {datetime.fromtimestamp(scan.latest_snapshot_timestamp, tz=timezone.utc).astimezone(SEOUL_TZ).strftime('%Y-%m-%d %H:%M:%S KST')}",
        f"- 기준가: ${scan.reference_price:,.2f}",
        f"- 스캔 범위: 최근 {get_okx_btc_band_scan_period_seconds() // 3600}시간 minute 스냅샷",
        f"- 사용 스냅샷: {scan.snapshot_count}개",
        f"- 밴드 기준: {market.band_min_size:.1f} {market.asset_label} 이상, 현재가 대비 {get_okx_btc_band_min_distance_pct():.1f}%~{get_okx_btc_band_max_distance_pct():.1f}%, maxDepth {get_okx_btc_band_max_depth()}",
    ]

    if not scan.bands:
        lines.append("- 현재 기준으로 오래 남은 원거리 밴드를 찾지 못했습니다.")
        lines.append("- 메모: 호출 시점에 따라 더 짧은 범위로 축소 조회될 수 있습니다.")
        return "\n".join(lines)

    lines.append("")
    lines.append("위쪽 ASK 밴드")
    if ask_bands:
        for index, band in enumerate(ask_bands[:get_okx_btc_report_limit()], start=1):
            lines.append(
                f"{index}. {band.price_label} | 유지 {band.snapshot_count}/{band.sample_count} | 최대 {band.max_size:.3f} {market.asset_label} | 현재가 대비 {band.distance_pct:+.2f}%"
            )
        if len(ask_bands) > get_okx_btc_report_limit():
            lines.append(f"- 메모: ASK는 상위 {get_okx_btc_report_limit()}개만 표시했습니다.")
    else:
        lines.append("- 없음")

    lines.append("")
    lines.append("아래쪽 BID 밴드")
    if bid_bands:
        for index, band in enumerate(bid_bands[:get_okx_btc_report_limit()], start=1):
            lines.append(
                f"{index}. {band.price_label} | 유지 {band.snapshot_count}/{band.sample_count} | 최대 {band.max_size:.3f} {market.asset_label} | 현재가 대비 {band.distance_pct:+.2f}%"
            )
        if len(bid_bands) > get_okx_btc_report_limit():
            lines.append(f"- 메모: BID는 상위 {get_okx_btc_report_limit()}개만 표시했습니다.")
    else:
        lines.append("- 없음")

    lines.append("- 메모: 근처 벽보다 오래 남는 원거리 히트맵 밴드를 우선 보여줍니다.")
    return "\n".join(lines)


def get_okx_btc_status_report(chat_id: int) -> str:
    runtime_enabled = has_runtime_okx_btc_subscription(chat_id)
    configured_enabled = has_configured_okx_btc_subscription(chat_id)
    enabled = runtime_enabled or configured_enabled

    if runtime_enabled and configured_enabled:
        source = "수동 등록 + 환경변수 등록"
    elif configured_enabled:
        source = "환경변수 등록"
    elif runtime_enabled:
        source = "수동 등록"
    else:
        source = "미등록"

    lines = [
        "OKX 비트 알람 상태",
        f"- 현재 채팅: {'켜짐' if enabled else '꺼짐'}",
        f"- 등록 방식: {source}",
        (
            f"- 알람 기준: 최근 {get_okx_btc_alert_band_scan_period_seconds() // 3600}시간 "
            f"딥밴드 스캔에서 {get_okx_btc_band_min_size():.1f} BTC 이상, "
            f"현재가 대비 {get_okx_btc_band_min_distance_pct():.1f}%~{get_okx_btc_band_max_distance_pct():.1f}% 구간, "
            f"최소 {get_okx_btc_alert_band_min_snapshots()}개 스냅샷 또는 {get_okx_btc_alert_band_min_persistence_ratio() * 100:.1f}% 이상 유지된 신규/증가 밴드"
        ),
        f"- 알람 주기: {get_okx_btc_poll_interval_seconds()}초",
        f"- /okxbit 조회: 최근 {get_okx_btc_band_scan_period_seconds() // 3600}시간 딥 히트맵 밴드",
        f"- Kiyotaka API: {'있음' if _has_kiyotaka_api_key() else '없음'}",
        f"- chat_id: {chat_id}",
    ]
    return "\n".join(lines)


def has_kiyotaka_api_key() -> bool:
    return _has_kiyotaka_api_key()


def build_okx_btc_alert_message(levels: list[OkxBtcHeatmapBand], *, now_utc: datetime | None = None) -> str:
    if not levels:
        return "OKX BTC 딥밴드 알람\n- 새로 감지된 밴드가 없습니다."

    delayed = any(
        get_okx_btc_snapshot_delay_seconds(level.latest_snapshot_timestamp, now_utc=now_utc)
        > get_okx_btc_delayed_alert_threshold_seconds()
        for level in levels
    )
    title = "OKX BTC 딜레이된 딥밴드 알람" if delayed else "OKX BTC 딥밴드 알람"
    snapshot_timestamp = levels[0].latest_snapshot_timestamp
    delay_seconds = get_okx_btc_snapshot_delay_seconds(snapshot_timestamp, now_utc=now_utc)
    reference_price = levels[0].reference_price
    lines = [
        title,
        f"- 기준 시각: {levels[0].local_time}",
        f"- 기준가: ${reference_price:,.2f}",
        f"- 새로 감지된 밴드: {len(levels)}개",
        f"- 스캔 범위: 최근 {get_okx_btc_alert_band_scan_period_seconds() // 3600}시간 minute 스냅샷",
    ]
    if delayed:
        lines.append(f"- 딜레이된 알람: {delay_seconds}초 늦음")

    lines.append("")
    for index, level in enumerate(levels[:get_okx_btc_report_limit()], start=1):
        event_label = "신규" if level.event == "new" else "증가"
        detail = (
            f"{index}. {event_label} | {level.side.upper()} | {level.price_label} | "
            f"유지 {level.snapshot_count}/{level.sample_count} | 최대 {level.max_size:.3f} BTC | {level.distance_pct:+.2f}%"
        )
        if level.event == "grew" and level.previous_max_size is not None:
            detail += f" | 이전 {level.previous_max_size:.3f} BTC"
        lines.append(detail)

    if len(levels) > get_okx_btc_report_limit():
        lines.append("")
        lines.append(f"- 메모: 상위 {get_okx_btc_report_limit()}개만 보냈습니다.")

    lines.append("")
    lines.append("- 메모: 근처 작은 벽보다 오래 남는 원거리 딥밴드를 우선 추적합니다.")

    return "\n".join(lines)


def format_okx_btc_alert_header(level: OkxBtcHeatmapBand, *, now_utc: datetime | None = None) -> str:
    delayed = get_okx_btc_snapshot_delay_seconds(level.latest_snapshot_timestamp, now_utc=now_utc) > get_okx_btc_delayed_alert_threshold_seconds()
    delay_seconds = get_okx_btc_snapshot_delay_seconds(level.latest_snapshot_timestamp, now_utc=now_utc)
    title = "OKX BTC 딜레이된 딥밴드 알람" if delayed else "OKX BTC 딥밴드 알람"
    event_label = "신규 딥밴드" if level.event == "new" else "딥밴드 증가"
    delta_line = ""
    if level.event == "grew" and level.previous_max_size is not None:
        delta_line = f"\n- 이전 최대 크기: {level.previous_max_size:.3f} BTC -> 현재 {level.max_size:.3f} BTC"
    delay_line = f"\n- 딜레이된 알람: {delay_seconds}초 늦음" if delayed else ""
    return (
        f"{title}\n"
        f"- 구분: {event_label}\n"
        f"- 기준 시각: {level.local_time}\n"
        f"- 방향: {level.side.upper()}\n"
        f"- 밴드: {level.price_label}\n"
        f"- 최대 크기: {level.max_size:.3f} BTC\n"
        f"- 기준가 대비: {level.distance_pct:+.2f}%"
        f"{delta_line}"
        f"{delay_line}"
    )


def fetch_okx_btc_heatmap_band_scan() -> OkxBtcHeatmapBandScan:
    return _fetch_okx_heatmap_band_scan("btc")


def fetch_okx_btc_alert_heatmap_band_scan() -> OkxBtcHeatmapBandScan:
    return _fetch_okx_heatmap_band_scan("btc", period_seconds=get_okx_btc_alert_band_scan_period_seconds())


def fetch_okx_eth_heatmap_band_scan() -> OkxBtcHeatmapBandScan:
    return _fetch_okx_heatmap_band_scan("eth")


def _fetch_okx_heatmap_band_scan(asset: str, *, period_seconds: int | None = None) -> OkxBtcHeatmapBandScan:
    market = _get_okx_heatmap_market(asset)
    return _fetch_heatmap_band_scan(market, period_seconds=period_seconds)


def _fetch_heatmap_band_scan(market: OkxHeatmapMarket, *, period_seconds: int | None = None) -> OkxBtcHeatmapBandScan:
    last_error: OkxBtcAlertError | None = None
    resolved_period_seconds = period_seconds if period_seconds is not None else get_okx_btc_band_scan_period_seconds()
    fallback_periods = [resolved_period_seconds]
    for candidate in (max(resolved_period_seconds // 2, 7200), 3600):
        if candidate not in fallback_periods:
            fallback_periods.append(candidate)

    for candidate_period in fallback_periods:
        try:
            points = _fetch_snapshot_points(
                interval="MINUTE",
                period_seconds=candidate_period,
                max_depth=get_okx_btc_band_max_depth(),
                sort_direction="SORT_DIRECTION_ASC",
                exchange=market.exchange_id,
                raw_symbol=market.raw_symbol,
                block_size=market.block_size if market.block_size is not None else get_okx_btc_block_size(),
                error_label=market.display_name,
            )
            return _extract_heatmap_band_scan(points, market=market)
        except OkxBtcAlertError as exc:
            last_error = exc
            if "HTTP 429" not in str(exc):
                raise

    raise last_error or OkxBtcAlertError(f"{market.display_name} 딥 히트맵 밴드를 불러오지 못했습니다.")


def _fetch_current_order_wall_scan(market: OkxHeatmapMarket) -> OkxBtcHeatmapBandScan:
    points = _fetch_snapshot_points(
        interval="MINUTE",
        period_seconds=3600,
        max_depth=get_okx_btc_band_max_depth(),
        sort_direction="SORT_DIRECTION_DESC",
        exchange=market.exchange_id,
        raw_symbol=market.raw_symbol,
        block_size=market.block_size if market.block_size is not None else get_okx_btc_block_size(),
        error_label=market.display_name,
    )
    try:
        latest_point = points[0]
    except IndexError as exc:
        raise OkxBtcAlertError(f"{market.display_name} 현재 오더북 스냅샷이 비어 있습니다.") from exc
    return _extract_current_order_wall_scan(latest_point, market=market)


def _fetch_latest_snapshot_point() -> dict:
    points = _fetch_snapshot_points(
        interval="MINUTE",
        period_seconds=get_okx_btc_lookback_minutes(),
        max_depth=get_okx_btc_max_depth(),
        sort_direction="SORT_DIRECTION_DESC",
    )
    try:
        return points[0]
    except IndexError as exc:
        raise OkxBtcAlertError("Kiyotaka 응답에서 OKX BTC 스냅샷을 찾지 못했습니다.") from exc


def _fetch_snapshot_points(
    *,
    interval: str,
    period_seconds: int,
    max_depth: int,
    sort_direction: str,
    exchange: str = "OKEX_SWAP",
    raw_symbol: str = "BTC-USDT-SWAP",
    block_size: int | None = None,
    error_label: str = "OKX BTC",
) -> list[dict]:
    resolved_block_size = block_size if block_size is not None else get_okx_btc_block_size()
    payload = _request_json(
        KIYOTAKA_POINTS_API_URL,
        {
            "type": "BLOCK_BOOK_SNAPSHOT_AGG",
            "exchange": exchange,
            "rawSymbol": raw_symbol,
            "interval": interval,
            "period": period_seconds,
            "blockSize": resolved_block_size,
            "maxDepth": max_depth,
            "sortDirection": sort_direction,
        },
    )
    try:
        raw_points = payload["series"][0]["points"]
        return [item["Point"] for item in raw_points if isinstance(item, dict) and isinstance(item.get("Point"), dict)]
    except (KeyError, IndexError, TypeError) as exc:
        raise OkxBtcAlertError(f"Kiyotaka 응답에서 {error_label} 스냅샷 목록을 찾지 못했습니다.") from exc


def _extract_heatmap_band_scan(points: list[dict], *, market: OkxHeatmapMarket | None = None) -> OkxBtcHeatmapBandScan:
    resolved_market = market or _get_okx_heatmap_market("btc")
    if not points:
        raise OkxBtcAlertError(f"OKX {resolved_market.asset_label} 히트맵 스냅샷이 비어 있습니다.")

    ordered_points = sorted(points, key=_get_snapshot_timestamp)
    latest_point = ordered_points[-1]
    latest_reference_price = _get_reference_price_from_point(latest_point)
    latest_snapshot_timestamp = _get_snapshot_timestamp(latest_point)
    min_size = resolved_market.band_min_size
    min_distance_pct = get_okx_btc_band_min_distance_pct()
    max_distance_pct = get_okx_btc_band_max_distance_pct()
    min_snapshots = resolved_market.band_min_snapshots or get_okx_btc_band_min_snapshots()
    merge_gap = resolved_market.band_merge_gap
    min_persistence_ratio = resolved_market.band_min_persistence_ratio
    price_stats: dict[str, dict[float, dict[str, object]]] = {"bid": {}, "ask": {}}

    for point in ordered_points:
        snapshot_timestamp = _get_snapshot_timestamp(point)
        for side_name in ("bids", "asks"):
            side = "bid" if side_name == "bids" else "ask"
            values = point.get(side_name, [])
            seen_prices: set[float] = set()
            for index in range(0, len(values), 2):
                try:
                    price = float(values[index])
                    size = float(values[index + 1])
                except (TypeError, ValueError, IndexError):
                    continue

                if size < min_size:
                    continue

                if not _is_price_on_current_side(price, side=side, reference_price=latest_reference_price):
                    continue

                distance_pct = abs(((price / latest_reference_price) - 1.0) * 100.0) if latest_reference_price else 0.0
                if distance_pct < min_distance_pct or distance_pct > max_distance_pct:
                    continue

                stats = price_stats[side].setdefault(
                    price,
                    {
                        "timestamps": set(),
                        "max_size": 0.0,
                    },
                )
                if price not in seen_prices:
                    cast_timestamps = stats["timestamps"]
                    assert isinstance(cast_timestamps, set)
                    cast_timestamps.add(snapshot_timestamp)
                    seen_prices.add(price)
                stats["max_size"] = max(float(stats["max_size"]), size)

    bands: list[OkxBtcHeatmapBand] = []
    sample_count = len(ordered_points)
    for side, entries in price_stats.items():
        current_cluster: list[tuple[float, set[int], float]] = []
        previous_price: float | None = None
        for price, stats in sorted(entries.items()):
            timestamps = set(stats["timestamps"])
            if len(timestamps) < min_snapshots:
                continue
            max_size = float(stats["max_size"])
            if previous_price is None or abs(price - previous_price) <= merge_gap:
                current_cluster.append((price, timestamps, max_size))
            else:
                _append_band_from_cluster(
                    bands,
                    current_cluster,
                    side=side,
                    sample_count=sample_count,
                    reference_price=latest_reference_price,
                    min_snapshots=min_snapshots,
                    min_persistence_ratio=min_persistence_ratio,
                )
                current_cluster = [(price, timestamps, max_size)]
            previous_price = price

        _append_band_from_cluster(
            bands,
            current_cluster,
            side=side,
            sample_count=sample_count,
            reference_price=latest_reference_price,
            min_snapshots=min_snapshots,
            min_persistence_ratio=min_persistence_ratio,
        )

    ranked_bands = sorted(
        bands,
        key=lambda item: (item.persistence_ratio, item.max_size, -abs(item.distance_pct)),
        reverse=True,
    )
    return OkxBtcHeatmapBandScan(
        bands=tuple(ranked_bands),
        snapshot_count=sample_count,
        reference_price=latest_reference_price,
        latest_snapshot_timestamp=latest_snapshot_timestamp,
    )


def _extract_current_order_wall_scan(point: dict, *, market: OkxHeatmapMarket) -> OkxBtcHeatmapBandScan:
    reference_price = _get_reference_price_from_point(point)
    snapshot_timestamp = _get_snapshot_timestamp(point)
    min_size = market.band_min_size
    min_distance_pct = get_okx_btc_band_min_distance_pct()
    max_distance_pct = get_okx_btc_band_max_distance_pct()
    merge_gap = market.band_merge_gap
    bands: list[OkxBtcHeatmapBand] = []

    for side_name in ("bids", "asks"):
        side = "bid" if side_name == "bids" else "ask"
        values = point.get(side_name, [])
        levels: list[tuple[float, float]] = []
        for index in range(0, len(values), 2):
            try:
                price = float(values[index])
                size = float(values[index + 1])
            except (TypeError, ValueError, IndexError):
                continue

            if size < min_size:
                continue
            if not _is_price_on_current_side(price, side=side, reference_price=reference_price):
                continue

            distance_pct = abs(((price / reference_price) - 1.0) * 100.0) if reference_price else 0.0
            if distance_pct < min_distance_pct or distance_pct > max_distance_pct:
                continue
            levels.append((price, size))

        current_cluster: list[tuple[float, float]] = []
        previous_price: float | None = None
        for price, size in sorted(levels):
            if previous_price is None or abs(price - previous_price) <= merge_gap:
                current_cluster.append((price, size))
            else:
                _append_current_wall_band(
                    bands,
                    current_cluster,
                    side=side,
                    reference_price=reference_price,
                    latest_snapshot_timestamp=snapshot_timestamp,
                )
                current_cluster = [(price, size)]
            previous_price = price

        _append_current_wall_band(
            bands,
            current_cluster,
            side=side,
            reference_price=reference_price,
            latest_snapshot_timestamp=snapshot_timestamp,
        )

    ranked_bands = sorted(
        bands,
        key=lambda item: (item.max_size, -abs(item.distance_pct)),
        reverse=True,
    )
    return OkxBtcHeatmapBandScan(
        bands=tuple(ranked_bands),
        snapshot_count=1,
        reference_price=reference_price,
        latest_snapshot_timestamp=snapshot_timestamp,
    )


def _append_current_wall_band(
    bands: list[OkxBtcHeatmapBand],
    cluster: list[tuple[float, float]],
    *,
    side: str,
    reference_price: float,
    latest_snapshot_timestamp: int,
) -> None:
    if not cluster:
        return

    prices = [price for price, _size in cluster]
    max_size = max(size for _price, size in cluster)
    bands.append(
        OkxBtcHeatmapBand(
            side=side,
            price_min=min(prices),
            price_max=max(prices),
            snapshot_count=1,
            sample_count=1,
            max_size=max_size,
            reference_price=reference_price,
            latest_snapshot_timestamp=latest_snapshot_timestamp,
        )
    )


def _append_band_from_cluster(
    bands: list[OkxBtcHeatmapBand],
    cluster: list[tuple[float, set[int], float]],
    *,
    side: str,
    sample_count: int,
    reference_price: float,
    min_snapshots: int,
    min_persistence_ratio: float,
) -> None:
    if not cluster:
        return

    timestamps: set[int] = set()
    max_size = 0.0
    prices: list[float] = []
    for price, snapshot_timestamps, size in cluster:
        prices.append(price)
        timestamps.update(snapshot_timestamps)
        max_size = max(max_size, size)

    if len(timestamps) < min_snapshots:
        return
    if sample_count > 0 and len(timestamps) / sample_count < min_persistence_ratio:
        return
    latest_snapshot_timestamp = max(timestamps)

    bands.append(
        OkxBtcHeatmapBand(
            side=side,
            price_min=min(prices),
            price_max=max(prices),
            snapshot_count=len(timestamps),
            sample_count=sample_count,
            max_size=max_size,
            reference_price=reference_price,
            latest_snapshot_timestamp=latest_snapshot_timestamp,
        )
    )


def _extract_significant_levels(point: dict) -> list[OkxBtcAlertLevel]:
    best_bid = _get_best_price(point.get("bids", []), side="bid")
    best_ask = _get_best_price(point.get("asks", []), side="ask")
    reference_price = _compute_reference_price(best_bid, best_ask)
    snapshot_timestamp = _get_snapshot_timestamp(point)
    max_distance_pct = get_okx_btc_max_distance_pct()
    min_size = get_okx_btc_min_size()
    levels: list[OkxBtcAlertLevel] = []

    for side_name in ("bids", "asks"):
        side = "bid" if side_name == "bids" else "ask"
        values = point.get(side_name, [])
        for index in range(0, len(values), 2):
            try:
                price = float(values[index])
                size = float(values[index + 1])
            except (TypeError, ValueError, IndexError):
                continue

            distance_pct = abs(((price / reference_price) - 1.0) * 100.0) if reference_price else 0.0
            if (
                size < min_size
                or not _is_price_on_current_side(price, side=side, reference_price=reference_price)
                or distance_pct > max_distance_pct
            ):
                continue
            levels.append(
                OkxBtcAlertLevel(
                    side=side,
                    price=price,
                    size=size,
                    snapshot_timestamp=snapshot_timestamp,
                    reference_price=reference_price,
                )
            )

    return sorted(levels, key=lambda item: item.size, reverse=True)


def _get_reference_price_from_point(point: dict) -> float:
    best_bid = _get_best_price(point.get("bids", []), side="bid")
    best_ask = _get_best_price(point.get("asks", []), side="ask")
    return _compute_reference_price(best_bid, best_ask)


def _get_best_price(values: list[float], *, side: str) -> float | None:
    prices = values[0::2]
    if not prices:
        return None
    if side == "bid":
        return max(float(price) for price in prices)
    return min(float(price) for price in prices)


def _compute_reference_price(best_bid: float | None, best_ask: float | None) -> float:
    if best_bid and best_ask:
        return (best_bid + best_ask) / 2.0
    if best_bid:
        return best_bid
    if best_ask:
        return best_ask
    raise OkxBtcAlertError("기준가를 계산할 수 있는 bid/ask 값이 없습니다.")


def _is_price_on_current_side(price: float, *, side: str, reference_price: float) -> bool:
    if not reference_price:
        return True
    if side == "bid":
        return price < reference_price
    if side == "ask":
        return price > reference_price
    return True


def _get_snapshot_timestamp(point: dict) -> int:
    timestamp = point.get("timestamp", {})
    seconds = timestamp.get("s") if isinstance(timestamp, dict) else None
    if not isinstance(seconds, int):
        raise OkxBtcAlertError("Kiyotaka 스냅샷 시각을 해석하지 못했습니다.")
    return seconds


def _request_json(url: str, params: dict) -> dict:
    api_key = _get_kiyotaka_api_key()
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={
            "Accept": "application/json",
            "X-Kiyotaka-Key": api_key,
        },
    )

    try:
        with _DIRECT_HTTP_OPENER.open(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise OkxBtcAlertError("Kiyotaka API 호출이 너무 많아 잠시 제한되었습니다 (HTTP 429).") from exc
        raise OkxBtcAlertError(f"Kiyotaka API 호출 실패: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OkxBtcAlertError("Kiyotaka API에 연결하지 못했습니다.") from exc
    except json.JSONDecodeError as exc:
        raise OkxBtcAlertError("Kiyotaka API 응답을 해석하지 못했습니다.") from exc


def _has_kiyotaka_api_key() -> bool:
    return bool(os.getenv("KIYOTAKA_API_KEY", "").strip())


def _get_kiyotaka_api_key() -> str:
    api_key = os.getenv("KIYOTAKA_API_KEY", "").strip()
    if not api_key:
        raise OkxBtcAlertError("KIYOTAKA_API_KEY가 없습니다.")
    return api_key


def _load_state() -> dict:
    if not OKX_BTC_ALERT_STATE_PATH.exists():
        return {
            "chat_ids": [],
            "active_levels": {},
            "active_bands": {},
            "primed": False,
        }

    try:
        payload = json.loads(OKX_BTC_ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}

    return {
        "chat_ids": payload.get("chat_ids", []),
        "active_levels": payload.get("active_levels", {}),
        "active_bands": payload.get("active_bands", {}),
        "primed": bool(payload.get("primed", False)),
    }


def _save_state(state: dict) -> None:
    OKX_BTC_ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    OKX_BTC_ALERT_STATE_PATH.write_text(
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


def _serialize_active_levels(level_map: dict[str, OkxBtcAlertLevel]) -> dict[str, dict]:
    return {
        key: {
            "size": level.size,
            "timestamp": level.snapshot_timestamp,
        }
        for key, level in level_map.items()
    }


def _serialize_active_bands(band_map: dict[str, OkxBtcHeatmapBand]) -> dict[str, dict]:
    return {
        key: {
            "side": band.side,
            "price_min": band.price_min,
            "price_max": band.price_max,
            "snapshot_count": band.snapshot_count,
            "sample_count": band.sample_count,
            "max_size": band.max_size,
            "reference_price": band.reference_price,
            "latest_snapshot_timestamp": band.latest_snapshot_timestamp,
        }
        for key, band in band_map.items()
    }


def _is_confirmed_alert_band(band: OkxBtcHeatmapBand) -> bool:
    min_snapshots = get_okx_btc_alert_band_min_snapshots()
    min_persistence_ratio = get_okx_btc_alert_band_min_persistence_ratio()
    return band.snapshot_count >= min_snapshots or band.persistence_ratio >= min_persistence_ratio


def _filter_recent_confirmed_alert_bands(scan: OkxBtcHeatmapBandScan) -> tuple[OkxBtcHeatmapBand, ...]:
    return tuple(
        band
        for band in scan.bands
        if _is_confirmed_alert_band(band) and _is_recent_alert_band(band, scan)
    )


def _is_recent_alert_band(band: OkxBtcHeatmapBand, scan: OkxBtcHeatmapBandScan) -> bool:
    return scan.latest_snapshot_timestamp - band.latest_snapshot_timestamp <= get_okx_btc_alert_max_band_age_seconds()


def _find_nearby_previous_band(band: OkxBtcHeatmapBand, previous_bands: dict[str, dict]) -> dict | None:
    for previous in previous_bands.values():
        if previous.get("side") != band.side:
            continue
        try:
            previous_min = float(previous.get("price_min", 0.0))
            previous_max = float(previous.get("price_max", 0.0))
        except (TypeError, ValueError):
            continue

        previous_center = (previous_min + previous_max) / 2.0
        if abs(previous_center - band.center_price) <= _get_watch_band_match_tolerance():
            return previous
    return None


def _get_watch_band_key(band: OkxBtcHeatmapBand) -> str:
    step = max(get_okx_btc_band_merge_gap(), 1.0)
    price_min = round(band.price_min / step) * step
    price_max = round(band.price_max / step) * step
    return f"{band.side}:{price_min:.2f}:{price_max:.2f}"


def _get_watch_band_match_tolerance() -> float:
    return max(get_okx_btc_band_merge_gap() * 2.0, 100.0)


def _format_price_short(price: float, *, mode: str = "nearest") -> str:
    value = price / 1000.0
    if mode == "down":
        value = math.floor(value * 10.0) / 10.0
    elif mode == "up":
        value = math.ceil(value * 10.0) / 10.0
    else:
        value = round(value, 1)
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}k"


def _format_band_price_plain(band: OkxBtcHeatmapBand) -> str:
    if math.isclose(band.price_min, band.price_max):
        return _format_price_plain(band.price_min)
    return f"{_format_price_plain(band.price_min)}-{_format_price_plain(band.price_max)}"


def _format_price_plain(price: float) -> str:
    rounded = round(price)
    if math.isclose(price, rounded, abs_tol=0.01):
        return str(rounded)
    return f"{price:.2f}".rstrip("0").rstrip(".")


def _format_size_plain(size: float) -> str:
    if size >= 100:
        return f"{size:,.0f}"
    if size >= 10:
        return f"{size:,.1f}".rstrip("0").rstrip(".")
    return f"{size:,.2f}".rstrip("0").rstrip(".")
