import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from services import okx_btc_alert_service


def _make_payload(*, bid_rows: list[tuple[float, float]], ask_rows: list[tuple[float, float]], timestamp: int = 1_776_750_300) -> dict:
    bids: list[float] = []
    asks: list[float] = []
    for price, size in bid_rows:
        bids.extend([price, size])
    for price, size in ask_rows:
        asks.extend([price, size])
    return {
        "series": [
            {
                "id": "test",
                "points": [
                    {
                        "Point": {
                            "bids": bids,
                            "asks": asks,
                            "timestamp": {"s": timestamp},
                        }
                    }
                ],
            }
        ]
    }


def _make_point(*, bid_rows: list[tuple[float, float]], ask_rows: list[tuple[float, float]], timestamp: int) -> dict:
    bids: list[float] = []
    asks: list[float] = []
    for price, size in bid_rows:
        bids.extend([price, size])
    for price, size in ask_rows:
        asks.extend([price, size])
    return {
        "bids": bids,
        "asks": asks,
        "timestamp": {"s": timestamp},
    }


def _make_band(
    *,
    side: str,
    price_min: float,
    price_max: float,
    snapshot_count: int,
    sample_count: int,
    max_size: float,
    reference_price: float,
    latest_snapshot_timestamp: int,
    event: str = "new",
    previous_max_size: float | None = None,
) -> okx_btc_alert_service.OkxBtcHeatmapBand:
    return okx_btc_alert_service.OkxBtcHeatmapBand(
        side=side,
        price_min=price_min,
        price_max=price_max,
        snapshot_count=snapshot_count,
        sample_count=sample_count,
        max_size=max_size,
        reference_price=reference_price,
        latest_snapshot_timestamp=latest_snapshot_timestamp,
        event=event,
        previous_max_size=previous_max_size,
    )


def _make_scan(*bands: okx_btc_alert_service.OkxBtcHeatmapBand, snapshot_count: int, reference_price: float, latest_snapshot_timestamp: int) -> okx_btc_alert_service.OkxBtcHeatmapBandScan:
    return okx_btc_alert_service.OkxBtcHeatmapBandScan(
        bands=bands,
        snapshot_count=snapshot_count,
        reference_price=reference_price,
        latest_snapshot_timestamp=latest_snapshot_timestamp,
    )


class OkxBtcAlertServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_path = Path("memory") / "test_okx_btc_alert_service_state.json"
        if self.state_path.exists():
            self.state_path.unlink()
        self.watch_state_patcher = patch.object(okx_btc_alert_service, "OKX_BTC_ALERT_STATE_PATH", self.state_path)
        self.watch_state_patcher.start()
        self.addCleanup(self.watch_state_patcher.stop)
        self.addCleanup(self._cleanup_state_file)

    def _cleanup_state_file(self) -> None:
        if self.state_path.exists():
            self.state_path.unlink()

    def test_add_and_remove_subscription(self) -> None:
        self.assertTrue(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
        self.assertFalse(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
        self.assertEqual(okx_btc_alert_service.list_okx_btc_subscriptions(), [-1001234567890])
        self.assertTrue(okx_btc_alert_service.remove_okx_btc_subscription(-1001234567890))
        self.assertEqual(okx_btc_alert_service.list_okx_btc_subscriptions(), [])

    def test_poll_interval_is_clamped_to_one_to_four_hours(self) -> None:
        with patch.dict(os.environ, {"OKX_BTC_ALERT_POLL_INTERVAL_SECONDS": "900"}, clear=False):
            self.assertEqual(okx_btc_alert_service.get_okx_btc_poll_interval_seconds(), 3600)

        with patch.dict(os.environ, {"OKX_BTC_ALERT_POLL_INTERVAL_SECONDS": "7200"}, clear=False):
            self.assertEqual(okx_btc_alert_service.get_okx_btc_poll_interval_seconds(), 7200)

        with patch.dict(os.environ, {"OKX_BTC_ALERT_POLL_INTERVAL_SECONDS": "28800"}, clear=False):
            self.assertEqual(okx_btc_alert_service.get_okx_btc_poll_interval_seconds(), 14400)

    def test_default_band_min_distance_is_half_percent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(okx_btc_alert_service.get_okx_btc_band_min_distance_pct(), 0.5)

    def test_default_alert_band_growth_threshold_is_sub_btc(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(okx_btc_alert_service.get_okx_btc_alert_band_min_size_change(), 0.1)

    def test_default_alert_band_max_age_is_three_minutes(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(okx_btc_alert_service.get_okx_btc_alert_max_band_age_seconds(), 180)

    def test_extract_significant_levels_keeps_nearby_small_levels(self) -> None:
        payload = _make_payload(
            bid_rows=[(75740, 1.2), (66600, 1.1), (51000, 26.0)],
            ask_rows=[(75760, 1.3), (75800, 0.8)],
        )
        with patch.dict(
            os.environ,
            {
                "OKX_BTC_ALERT_MIN_SIZE": "1",
                "OKX_BTC_ALERT_MAX_DISTANCE_PCT": "15",
            },
            clear=False,
        ):
            point = payload["series"][0]["points"][0]["Point"]
            levels = okx_btc_alert_service._extract_significant_levels(point)

        level_prices = {level.price for level in levels}
        self.assertIn(75740, level_prices)
        self.assertIn(66600, level_prices)
        self.assertNotIn(51000, level_prices)
        self.assertNotIn(75800, level_prices)

    def test_default_thresholds_allow_sub_btc_levels(self) -> None:
        payload = _make_payload(
            bid_rows=[(66600, 0.15), (66500, 0.05)],
            ask_rows=[(75760, 1.3)],
        )
        with patch.dict(os.environ, {}, clear=True):
            point = payload["series"][0]["points"][0]["Point"]
            levels = okx_btc_alert_service._extract_significant_levels(point)

        level_prices = {level.price for level in levels}
        self.assertIn(66600, level_prices)
        self.assertNotIn(66500, level_prices)

    def test_fetch_new_levels_primes_then_alerts_new_deep_band(self) -> None:
        first_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=50900,
                price_max=51100,
                snapshot_count=3,
                sample_count=4,
                max_size=7.5,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_300,
            ),
            snapshot_count=4,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_300,
        )
        second_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=50900,
                price_max=51100,
                snapshot_count=3,
                sample_count=4,
                max_size=7.5,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_360,
            ),
            _make_band(
                side="bid",
                price_min=52800,
                price_max=53000,
                snapshot_count=3,
                sample_count=4,
                max_size=5.1,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_360,
            ),
            snapshot_count=4,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.object(okx_btc_alert_service, "fetch_okx_btc_alert_heatmap_band_scan", side_effect=[first_scan, second_scan]):
            self.assertTrue(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
            primed = okx_btc_alert_service.fetch_new_okx_btc_levels()
            alerted = okx_btc_alert_service.fetch_new_okx_btc_levels()

        self.assertEqual(primed, [])
        self.assertEqual(len(alerted), 1)
        self.assertEqual(alerted[0].price_label, "52.8k-53k")
        self.assertEqual(alerted[0].event, "new")

    def test_fetch_new_levels_detects_deep_band_growth(self) -> None:
        first_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=52800,
                price_max=53000,
                snapshot_count=3,
                sample_count=4,
                max_size=5.1,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_300,
            ),
            snapshot_count=4,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_300,
        )
        second_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=52800,
                price_max=53000,
                snapshot_count=4,
                sample_count=5,
                max_size=6.0,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_360,
            ),
            snapshot_count=5,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.dict(os.environ, {"OKX_BTC_ALERT_BAND_MIN_SIZE_CHANGE": "0.5"}, clear=False):
            with patch.object(okx_btc_alert_service, "fetch_okx_btc_alert_heatmap_band_scan", side_effect=[first_scan, second_scan]):
                self.assertTrue(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
                okx_btc_alert_service.fetch_new_okx_btc_levels()
                alerted = okx_btc_alert_service.fetch_new_okx_btc_levels()

        self.assertEqual(len(alerted), 1)
        self.assertEqual(alerted[0].event, "grew")
        self.assertEqual(alerted[0].previous_max_size, 5.1)

    def test_fetch_new_levels_ignores_short_lived_alert_band(self) -> None:
        first_scan = _make_scan(
            snapshot_count=240,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_300,
        )
        second_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=52800,
                price_max=53000,
                snapshot_count=3,
                sample_count=240,
                max_size=5.1,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_360,
            ),
            snapshot_count=240,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.object(okx_btc_alert_service, "fetch_okx_btc_alert_heatmap_band_scan", side_effect=[first_scan, second_scan]):
            self.assertTrue(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
            okx_btc_alert_service.fetch_new_okx_btc_levels()
            alerted = okx_btc_alert_service.fetch_new_okx_btc_levels()

        self.assertEqual(alerted, [])

    def test_fetch_new_levels_ignores_stale_band_not_seen_recently(self) -> None:
        first_scan = _make_scan(
            snapshot_count=240,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_300,
        )
        second_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=52800,
                price_max=53000,
                snapshot_count=20,
                sample_count=240,
                max_size=5.1,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_300,
            ),
            snapshot_count=240,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_600,
        )
        with patch.dict(os.environ, {"OKX_BTC_ALERT_MAX_BAND_AGE_SECONDS": "180"}, clear=False):
            with patch.object(okx_btc_alert_service, "fetch_okx_btc_alert_heatmap_band_scan", side_effect=[first_scan, second_scan]):
                self.assertTrue(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
                okx_btc_alert_service.fetch_new_okx_btc_levels()
                alerted = okx_btc_alert_service.fetch_new_okx_btc_levels()

        self.assertEqual(alerted, [])

    def test_fetch_new_levels_ignores_nearby_shifted_band_as_new(self) -> None:
        first_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=52800,
                price_max=53000,
                snapshot_count=20,
                sample_count=240,
                max_size=5.1,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_300,
            ),
            snapshot_count=240,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_300,
        )
        second_scan = _make_scan(
            _make_band(
                side="bid",
                price_min=52850,
                price_max=53050,
                snapshot_count=20,
                sample_count=240,
                max_size=5.2,
                reference_price=78000,
                latest_snapshot_timestamp=1_776_750_360,
            ),
            snapshot_count=240,
            reference_price=78000,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.object(okx_btc_alert_service, "fetch_okx_btc_alert_heatmap_band_scan", side_effect=[first_scan, second_scan]):
            self.assertTrue(okx_btc_alert_service.add_okx_btc_subscription(-1001234567890))
            okx_btc_alert_service.fetch_new_okx_btc_levels()
            alerted = okx_btc_alert_service.fetch_new_okx_btc_levels()

        self.assertEqual(alerted, [])

    def test_build_alert_message_mentions_delay(self) -> None:
        level = _make_band(
            side="bid",
            price_min=66550,
            price_max=66650,
            snapshot_count=3,
            sample_count=4,
            max_size=1.4,
            reference_price=75750,
            latest_snapshot_timestamp=1_776_750_300,
        )
        with patch.dict(os.environ, {"OKX_BTC_ALERT_POLL_INTERVAL_SECONDS": "3600"}, clear=False):
            message = okx_btc_alert_service.build_okx_btc_alert_message(
                [level],
                now_utc=datetime.fromtimestamp(1_776_758_000, tz=timezone.utc),
            )

        self.assertIn("OKX BTC 딜레이된 딥밴드 알람", message)
        self.assertIn("딜레이된 알람: 7700초 늦음", message)
        self.assertIn("유지 3/4", message)
        self.assertIn("최대 1.400 BTC", message)

    def test_extract_heatmap_band_scan_groups_persistent_remote_levels(self) -> None:
        points = [
            _make_point(
                bid_rows=[(75950, 12.0), (52995, 0.8), (52990, 3.4), (52985, 2.1), (51070, 9.0)],
                ask_rows=[(76000, 8.0)],
                timestamp=1_776_750_240,
            ),
            _make_point(
                bid_rows=[(75955, 11.0), (52995, 1.0), (52990, 5.0), (52985, 1.5), (51070, 7.5)],
                ask_rows=[(76005, 9.0)],
                timestamp=1_776_750_300,
            ),
            _make_point(
                bid_rows=[(75960, 10.0), (52995, 0.7), (52990, 4.2), (51070, 8.2)],
                ask_rows=[(76010, 9.0)],
                timestamp=1_776_750_360,
            ),
        ]
        with patch.dict(
            os.environ,
            {
                "OKX_BTC_BAND_MIN_SIZE": "0.5",
                "OKX_BTC_BAND_MIN_DISTANCE_PCT": "10",
                "OKX_BTC_BAND_MAX_DISTANCE_PCT": "40",
                "OKX_BTC_BAND_MIN_SNAPSHOTS": "2",
                "OKX_BTC_BAND_MERGE_GAP": "10",
            },
            clear=False,
        ):
            scan = okx_btc_alert_service._extract_heatmap_band_scan(points)

        self.assertGreaterEqual(scan.snapshot_count, 3)
        self.assertGreaterEqual(len(scan.bands), 2)
        labels = {band.price_label for band in scan.bands}
        self.assertIn("52.9k-53k", labels)
        matching_band = next(band for band in scan.bands if band.price_label == "52.9k-53k")
        self.assertEqual(matching_band.side, "bid")
        self.assertEqual(matching_band.snapshot_count, 3)
        self.assertAlmostEqual(matching_band.max_size, 5.0)

    def test_extract_heatmap_band_scan_uses_band_own_latest_timestamp(self) -> None:
        points = [
            _make_point(
                bid_rows=[(77000, 1.0), (52900, 5.0)],
                ask_rows=[(78000, 1.0)],
                timestamp=1_776_750_240,
            ),
            _make_point(
                bid_rows=[(77000, 1.0), (52900, 6.0)],
                ask_rows=[(78000, 1.0)],
                timestamp=1_776_750_300,
            ),
            _make_point(
                bid_rows=[(77000, 1.0)],
                ask_rows=[(78000, 1.0)],
                timestamp=1_776_750_360,
            ),
        ]
        with patch.dict(
            os.environ,
            {
                "OKX_BTC_BAND_MIN_SIZE": "0.5",
                "OKX_BTC_BAND_MIN_DISTANCE_PCT": "10",
                "OKX_BTC_BAND_MAX_DISTANCE_PCT": "40",
                "OKX_BTC_BAND_MIN_SNAPSHOTS": "2",
                "OKX_BTC_BAND_MERGE_GAP": "10",
            },
            clear=False,
        ):
            scan = okx_btc_alert_service._extract_heatmap_band_scan(points)

        band = next(band for band in scan.bands if band.price_label == "52.9k")
        self.assertEqual(scan.latest_snapshot_timestamp, 1_776_750_360)
        self.assertEqual(band.latest_snapshot_timestamp, 1_776_750_300)

    def test_extract_heatmap_band_scan_drops_bid_prices_above_latest_reference(self) -> None:
        points = [
            _make_point(
                bid_rows=[(77300, 2.0), (77800, 24.0), (52900, 8.0)],
                ask_rows=[(77320, 2.0), (77800, 30.0)],
                timestamp=1_776_750_240,
            ),
            _make_point(
                bid_rows=[(77300, 2.0), (77800, 25.0), (52900, 9.0)],
                ask_rows=[(77320, 2.0), (77800, 31.0)],
                timestamp=1_776_750_300,
            ),
            _make_point(
                bid_rows=[(77300, 2.0), (52900, 10.0)],
                ask_rows=[(77320, 2.0), (77800, 32.0)],
                timestamp=1_776_750_360,
            ),
        ]
        with patch.dict(
            os.environ,
            {
                "OKX_BTC_BAND_MIN_SIZE": "0.5",
                "OKX_BTC_BAND_MIN_DISTANCE_PCT": "0.1",
                "OKX_BTC_BAND_MAX_DISTANCE_PCT": "40",
                "OKX_BTC_BAND_MIN_SNAPSHOTS": "2",
                "OKX_BTC_BAND_MERGE_GAP": "10",
            },
            clear=False,
        ):
            scan = okx_btc_alert_service._extract_heatmap_band_scan(points)

        crossed_bid_labels = [
            band.price_label
            for band in scan.bands
            if band.side == "bid" and band.center_price > scan.reference_price
        ]
        ask_labels = {band.price_label for band in scan.bands if band.side == "ask"}
        bid_labels = {band.price_label for band in scan.bands if band.side == "bid"}
        self.assertEqual(crossed_bid_labels, [])
        self.assertIn("77.8k", ask_labels)
        self.assertIn("52.9k", bid_labels)

    def test_get_levels_report_formats_deep_band_output(self) -> None:
        band = _make_band(
            side="bid",
            price_min=52900,
            price_max=53000,
            snapshot_count=3,
            sample_count=4,
            max_size=19.3,
            reference_price=78686.8,
            latest_snapshot_timestamp=1_776_750_360,
        )
        scan = _make_scan(
            band,
            snapshot_count=4,
            reference_price=78686.8,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.object(okx_btc_alert_service, "fetch_okx_btc_heatmap_band_scan", return_value=scan):
            report = okx_btc_alert_service.get_okx_btc_levels_report()

        self.assertIn("OKX BTC 딥 히트맵 밴드", report)
        self.assertIn("위쪽 ASK 밴드", report)
        self.assertIn("아래쪽 BID 밴드", report)
        self.assertIn("- 없음", report)
        self.assertIn("52.9k-53k", report)
        self.assertIn("유지 3/4", report)
        self.assertIn("최대 19.300 BTC", report)

    def test_get_btc_levels_report_with_focus_prices_uses_recent_confirmed_bands(self) -> None:
        fresh_band = _make_band(
            side="bid",
            price_min=52900,
            price_max=53000,
            snapshot_count=20,
            sample_count=240,
            max_size=19.3,
            reference_price=78686.8,
            latest_snapshot_timestamp=1_776_750_360,
        )
        stale_band = _make_band(
            side="bid",
            price_min=50900,
            price_max=51100,
            snapshot_count=20,
            sample_count=240,
            max_size=26.4,
            reference_price=78686.8,
            latest_snapshot_timestamp=1_776_750_000,
        )
        scan = _make_scan(
            fresh_band,
            stale_band,
            snapshot_count=240,
            reference_price=78686.8,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.object(okx_btc_alert_service, "fetch_okx_btc_alert_heatmap_band_scan", return_value=scan):
            report, focus_prices = okx_btc_alert_service.get_okx_btc_levels_report_with_focus_prices()

        self.assertIn("52.9k-53k", report)
        self.assertNotIn("50.9k-51.1k", report)
        self.assertEqual(focus_prices, (78686.8, 52900.0, 53000.0))

    def test_get_eth_levels_report_uses_eth_market_metadata(self) -> None:
        band = _make_band(
            side="ask",
            price_min=1820,
            price_max=1830,
            snapshot_count=2,
            sample_count=3,
            max_size=42.5,
            reference_price=1765.0,
            latest_snapshot_timestamp=1_776_750_360,
        )
        scan = _make_scan(
            band,
            snapshot_count=3,
            reference_price=1765.0,
            latest_snapshot_timestamp=1_776_750_360,
        )
        with patch.dict(os.environ, {"OKX_ETH_BAND_MIN_SIZE": "5"}, clear=False):
            with patch.object(okx_btc_alert_service, "fetch_okx_eth_heatmap_band_scan", return_value=scan):
                report = okx_btc_alert_service.get_okx_eth_levels_report()

        self.assertIn("OKX ETH 딥 히트맵 밴드", report)
        self.assertIn("OKX ETH-USDT-SWAP", report)
        self.assertIn("최대 42.500 ETH", report)

    def test_bitfinex_eth_scan_keeps_only_persistent_strong_bands(self) -> None:
        points = []
        for offset in range(10):
            bid_rows = [(2200, 1), (2100, 60)]
            ask_rows = [(2300, 1), (2400, 80)]
            if offset < 3:
                ask_rows.append((2450, 500))
            points.append(
                _make_point(
                    bid_rows=bid_rows,
                    ask_rows=ask_rows,
                    timestamp=1_776_750_300 + offset * 60,
                )
            )

        market = okx_btc_alert_service._get_bitfinex_heatmap_market("eth")
        with patch.dict(
            os.environ,
            {
                "BITFINEX_ETH_BAND_MIN_SIZE": "50",
                "BITFINEX_ETH_BAND_MIN_SNAPSHOTS": "2",
                "BITFINEX_ETH_BAND_MIN_PERSISTENCE_RATIO": "0.5",
                "OKX_BTC_BAND_MIN_DISTANCE_PCT": "0.1",
            },
            clear=False,
        ):
            market = okx_btc_alert_service._get_bitfinex_heatmap_market("eth")
            scan = okx_btc_alert_service._extract_heatmap_band_scan(points, market=market)

        labels = [band.price_label for band in scan.bands]
        self.assertIn("2.1k", labels)
        self.assertIn("2.4k", labels)
        self.assertNotIn("2.45k", labels)

    def test_bitfinex_eth_report_uses_compact_feedback_format(self) -> None:
        ask_high = _make_band(
            side="ask",
            price_min=2500,
            price_max=2500,
            snapshot_count=10,
            sample_count=10,
            max_size=116.7,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        ask_low = _make_band(
            side="ask",
            price_min=2460,
            price_max=2460,
            snapshot_count=10,
            sample_count=10,
            max_size=80.2,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        bid = _make_band(
            side="bid",
            price_min=2200,
            price_max=2200,
            snapshot_count=10,
            sample_count=10,
            max_size=60,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        scan = _make_scan(
            ask_low,
            bid,
            ask_high,
            snapshot_count=10,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )

        with patch.object(okx_btc_alert_service, "_fetch_current_order_wall_scan", return_value=scan):
            report, focus_prices = okx_btc_alert_service.get_bitfinex_eth_levels_report_with_focus_prices()

        self.assertIn("위에:\n1. 2500 (117 ETH)\n2. 2460 (80.2 ETH)", report)
        self.assertIn("현재가: 2300", report)
        self.assertIn("밑에:\n1. 2200 (60 ETH)", report)
        self.assertNotIn("스캔 범위", report)
        self.assertNotIn("유지", report)
        self.assertEqual(focus_prices, (2300.0, 2500.0, 2460.0, 2200.0))

    def test_bitfinex_eth_report_prefers_strong_visible_walls_over_far_prices(self) -> None:
        far_ask = _make_band(
            side="ask",
            price_min=2630,
            price_max=2630,
            snapshot_count=10,
            sample_count=10,
            max_size=26.7,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        strong_2480 = _make_band(
            side="ask",
            price_min=2485,
            price_max=2485,
            snapshot_count=10,
            sample_count=10,
            max_size=100,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        strong_2440 = _make_band(
            side="ask",
            price_min=2445,
            price_max=2445,
            snapshot_count=10,
            sample_count=10,
            max_size=121.5,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        strong_2410 = _make_band(
            side="ask",
            price_min=2410,
            price_max=2410,
            snapshot_count=10,
            sample_count=10,
            max_size=44,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        scan = _make_scan(
            far_ask,
            strong_2440,
            strong_2480,
            strong_2410,
            snapshot_count=10,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )

        with patch.object(okx_btc_alert_service, "_fetch_current_order_wall_scan", return_value=scan):
            report, focus_prices = okx_btc_alert_service.get_bitfinex_eth_levels_report_with_focus_prices()

        self.assertIn("1. 2485 (100 ETH)", report)
        self.assertIn("2. 2445 (122 ETH)", report)
        self.assertNotIn("2630", report)
        self.assertEqual(focus_prices, (2300.0, 2485.0, 2445.0, 2410.0))

    def test_bitfinex_eth_report_rejects_wide_diffuse_bands_when_narrow_walls_exist(self) -> None:
        diffuse = _make_band(
            side="ask",
            price_min=2290,
            price_max=2394,
            snapshot_count=10,
            sample_count=10,
            max_size=137,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        strong_2480 = _make_band(
            side="ask",
            price_min=2485,
            price_max=2485,
            snapshot_count=10,
            sample_count=10,
            max_size=100,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        strong_2440 = _make_band(
            side="ask",
            price_min=2445,
            price_max=2445,
            snapshot_count=10,
            sample_count=10,
            max_size=121.5,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )
        scan = _make_scan(
            diffuse,
            strong_2440,
            strong_2480,
            snapshot_count=10,
            reference_price=2300,
            latest_snapshot_timestamp=1_776_750_360,
        )

        with patch.object(okx_btc_alert_service, "_fetch_current_order_wall_scan", return_value=scan):
            report, focus_prices = okx_btc_alert_service.get_bitfinex_eth_levels_report_with_focus_prices()

        self.assertIn("2485", report)
        self.assertIn("2445", report)
        self.assertNotIn("2290-2394", report)
        self.assertEqual(focus_prices, (2300.0, 2485.0, 2445.0))

    def test_bitfinex_eth_market_uses_one_dollar_blocks(self) -> None:
        market = okx_btc_alert_service._get_bitfinex_heatmap_market("eth")

        self.assertEqual(market.block_size, 1)

    def test_bitfinex_eth_report_uses_current_order_snapshot_sizes(self) -> None:
        point = {
            "timestamp": {"s": 1_776_750_360},
            "asks": [2276, 1, 2444, 122, 2484, 100, 2354, 9],
            "bids": [2274, 1, 2106, 101, 2055, 106],
        }

        with patch.object(okx_btc_alert_service, "_fetch_snapshot_points", return_value=[point]):
            report, focus_prices = okx_btc_alert_service.get_bitfinex_eth_levels_report_with_focus_prices()

        self.assertIn("위에:\n1. 2484 (100 ETH)\n2. 2444 (122 ETH)", report)
        self.assertIn("밑에:\n1. 2106 (101 ETH)\n2. 2055 (106 ETH)", report)
        self.assertNotIn("2354", report)
        self.assertEqual(focus_prices, (2275.0, 2484.0, 2444.0, 2106.0, 2055.0))


if __name__ == "__main__":
    unittest.main()
