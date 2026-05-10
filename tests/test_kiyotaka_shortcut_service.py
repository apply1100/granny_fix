import unittest

from services.kiyotaka_shortcut_service import (
    build_kiyotaka_shortcut_reply,
    get_kiyotaka_shortcut_spec,
)


class KiyotakaShortcutServiceTests(unittest.TestCase):
    def test_exact_shortcut_returns_spec(self) -> None:
        spec = get_kiyotaka_shortcut_spec("okxbtcusdtp")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_url, "https://chart.kiyotaka.ai/")
        self.assertEqual(spec.search_query, "BTC-USDT")
        self.assertEqual(spec.result_symbol, "BTCUSDT")
        self.assertEqual(spec.result_exchange, "OKX.F")
        self.assertEqual(spec.result_index, 1)
        self.assertEqual(spec.timeframe, "1m")
        self.assertEqual(spec.view, "Heatmap")
        self.assertEqual(spec.chart_drag_y, 260)
        self.assertEqual(spec.api_asset, "btc")
        self.assertTrue(spec.capture_with_api)
        self.assertTrue(spec.split_capture_with_api)

    def test_slash_command_shortcut_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("/okxbtcusdtp")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "okxbtcusdtp")

    def test_wide_shortcut_returns_wider_drag_spec(self) -> None:
        spec = get_kiyotaka_shortcut_spec("/okxbtcusdtpwide")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "okxbtcusdtpwide")
        self.assertEqual(spec.result_exchange, "OKX.F")
        self.assertEqual(spec.chart_drag_y, 420)

    def test_common_typo_alias_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("/okxbtcusdp")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "okxbtcusdtp")

    def test_command_with_extra_instruction_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("/okxbtcusdtp 텍스트로만")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "okxbtcusdtp")

    def test_wide_typo_alias_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("/okxbtcusdpwide")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "okxbtcusdtpwide")

    def test_bitfinex_eth_korean_alias_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("비파 이더")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "bitfinexethusdt")
        self.assertEqual(spec.search_query, "ETHUSDT")
        self.assertEqual(spec.result_symbol, "ETHUSDT")
        self.assertEqual(spec.result_exchange, "BITFINEX")
        self.assertEqual(spec.timeframe, "5m")
        self.assertEqual(spec.api_asset, "bitfinex_eth")
        self.assertTrue(spec.capture_with_api)
        self.assertEqual(spec.capture_fallback_targets, ())

    def test_korean_alias_with_extra_instruction_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("비파 이더 사진 말고 텍스트로")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "bitfinexethusdt")

    def test_bitfinex_eth_slash_command_alias_is_supported(self) -> None:
        spec = get_kiyotaka_shortcut_spec("/bipaeth")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "bitfinexethusdt")

    def test_reply_builder_can_append_note(self) -> None:
        spec = get_kiyotaka_shortcut_spec("okxbtcusdtp")

        assert spec is not None
        reply = build_kiyotaka_shortcut_reply(spec, note="스크린샷 실패")

        self.assertIn("https://chart.kiyotaka.ai/", reply)
        self.assertIn("검색: BTC-USDT -> BTCUSDT / OKX.F", reply)
        self.assertIn("설정: 1m / Heatmap", reply)
        self.assertIn("메모: 스크린샷 실패", reply)

    def test_unknown_shortcut_returns_none(self) -> None:
        self.assertIsNone(get_kiyotaka_shortcut_spec("okxethusd"))


if __name__ == "__main__":
    unittest.main()
