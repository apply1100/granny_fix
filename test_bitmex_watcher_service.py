import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from services import bitmex_watcher_service


class BitmexWatcherServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_path = Path("memory") / "test_bitmex_watcher_service_state.json"
        if self.state_path.exists():
            self.state_path.unlink()
        self.watch_state_patcher = patch.object(bitmex_watcher_service, "WATCH_STATE_PATH", self.state_path)
        self.watch_state_patcher.start()
        self.addCleanup(self.watch_state_patcher.stop)
        self.addCleanup(self._cleanup_state_file)

    def _cleanup_state_file(self) -> None:
        if self.state_path.exists():
            self.state_path.unlink()

    def test_auto_register_on_market_interaction_enabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            self.assertTrue(bitmex_watcher_service.auto_register_on_market_interaction_enabled())

    def test_auto_register_on_market_interaction_respects_falsey_env_value(self) -> None:
        with patch.dict(
            os.environ,
            {"BITMEX_AUTO_REGISTER_ON_MARKET_INTERACTION": "0"},
            clear=False,
        ):
            self.assertFalse(bitmex_watcher_service.auto_register_on_market_interaction_enabled())

    def test_ensure_subscription_for_market_interaction_adds_runtime_chat(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BITMEX_AUTO_REGISTER_ON_MARKET_INTERACTION": "1",
                "BITMEX_ALERT_CHAT_IDS": "",
            },
            clear=False,
        ):
            added = bitmex_watcher_service.ensure_subscription_for_market_interaction(-1001234567890)

        self.assertTrue(added)
        self.assertEqual(
            bitmex_watcher_service.get_runtime_subscription_chat_ids(),
            [-1001234567890],
        )

    def test_ensure_subscription_for_market_interaction_skips_configured_chat(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BITMEX_AUTO_REGISTER_ON_MARKET_INTERACTION": "1",
                "BITMEX_ALERT_CHAT_IDS": "-1001234567890",
            },
            clear=False,
        ):
            added = bitmex_watcher_service.ensure_subscription_for_market_interaction(-1001234567890)

        self.assertFalse(added)
        self.assertEqual(bitmex_watcher_service.get_runtime_subscription_chat_ids(), [])

    def test_delayed_trade_alert_header_mentions_delay(self) -> None:
        trade = bitmex_watcher_service.BitmexWhaleTrade(
            trade_id="late-1",
            timestamp="2026-04-09T03:00:00Z",
            side="Buy",
            size=1_500_000,
            price=70000.0,
            symbol="XBTUSD",
        )

        with patch.dict(
            os.environ,
            {"BITMEX_WHALE_POLL_INTERVAL_SECONDS": "15"},
            clear=False,
        ):
            header = bitmex_watcher_service.format_trade_alert_header(
                trade,
                now_utc=datetime(2026, 4, 9, 3, 1, 0, tzinfo=timezone.utc),
            )

        self.assertIn("딜레이 된 알람", header)
        self.assertIn("지연 감지: 60초 늦게 잡힘", header)

    def test_recent_trade_alert_header_stays_normal(self) -> None:
        trade = bitmex_watcher_service.BitmexWhaleTrade(
            trade_id="recent-1",
            timestamp="2026-04-09T03:00:00Z",
            side="Sell",
            size=1_200_000,
            price=69950.0,
            symbol="XBTUSD",
        )

        with patch.dict(
            os.environ,
            {"BITMEX_WHALE_POLL_INTERVAL_SECONDS": "15"},
            clear=False,
        ):
            header = bitmex_watcher_service.format_trade_alert_header(
                trade,
                now_utc=datetime(2026, 4, 9, 3, 0, 20, tzinfo=timezone.utc),
            )

        self.assertIn("자동 알림", header)
        self.assertNotIn("딜레이 된 알람", header)

    def test_recent_whale_trades_report_lists_latest_whales(self) -> None:
        trades = [
            bitmex_watcher_service.BitmexWhaleTrade(
                trade_id="latest-buy",
                timestamp="2026-04-11T00:05:00Z",
                side="Buy",
                size=1_700_000,
                price=71234.5,
                symbol="XBTUSD",
            ),
            bitmex_watcher_service.BitmexWhaleTrade(
                trade_id="older-sell",
                timestamp="2026-04-11T00:03:00Z",
                side="Sell",
                size=1_250_000,
                price=71100.0,
                symbol="XBTUSD",
            ),
            bitmex_watcher_service.BitmexWhaleTrade(
                trade_id="small-trade",
                timestamp="2026-04-11T00:01:00Z",
                side="Buy",
                size=900_000,
                price=71050.0,
                symbol="XBTUSD",
            ),
        ]

        with patch.object(bitmex_watcher_service, "_fetch_recent_trades", return_value=trades):
            with patch.dict(
                os.environ,
                {
                    "BITMEX_WHALE_TRADE_THRESHOLD": "1000000",
                    "BITMEX_WHALE_FETCH_COUNT": "50",
                    "BITMEX_WHALE_REPORT_LIMIT": "2",
                },
                clear=False,
            ):
                report = bitmex_watcher_service.get_recent_whale_trades_report()

        self.assertIn("BitMEX 1M+ 최근 고래 체결 내역", report)
        self.assertIn("1. 2026-04-11 09:05:00 KST | 매수 | 1,700,000 contracts | $71,234.50", report)
        self.assertIn("2. 2026-04-11 09:03:00 KST | 매도 | 1,250,000 contracts | $71,100.00", report)
        self.assertNotIn("900,000 contracts", report)


if __name__ == "__main__":
    unittest.main()
