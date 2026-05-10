import os
import unittest
from unittest.mock import patch

from services.kiyotaka_screenshot_service import (
    _adjust_chart_range_to_focus_prices,
    _chart_text_matches_exchange,
    _chart_text_matches_symbol,
    _extract_visible_price_bounds,
    _get_bitfinex_price_scale_drag_count,
    _get_bitfinex_price_scale_drag_pixels,
    _get_bitfinex_price_scale_drag_steps,
    _get_clean_heatmap_capture_clip,
    _get_kiyotaka_price_scale_zoom_drag_pixels,
    _get_overlay_price_bounds,
    _get_symbol_search_queries,
    _get_visual_focus_prices,
    _indicator_cleanup_succeeded,
    _is_kiyotaka_chart_url,
    _kiyotaka_clean_capture_enabled,
    _kiyotaka_indicator_cleanup_enabled,
    _main_price_scale_looks_clean,
    _png_has_heatmap_layer,
    _price_bounds_include_focus,
    _read_main_price_scale_bounds,
    _search_result_matches,
    _should_tune_bitfinex_heatmap,
    _symbol_matches_text,
)
from services.kiyotaka_shortcut_service import get_kiyotaka_shortcut_spec


class KiyotakaScreenshotServiceTests(unittest.TestCase):
    def test_search_result_matches_okx_btc_with_hyphenated_symbol(self) -> None:
        self.assertTrue(
            _search_result_matches(
                "BTC-USDT-SWAP\nPerp\nOKX",
                symbol="BTCUSDT",
                exchange="OKX.F",
            )
        )

    def test_search_result_matches_okx_btc_swap_storage_label(self) -> None:
        self.assertTrue(
            _search_result_matches(
                "BTCUSDT\nOKEX_SWAP\nPERPETUAL",
                symbol="BTCUSDT",
                exchange="OKX.F",
            )
        )

    def test_okx_btc_search_queries_try_kiyotaka_swap_variants(self) -> None:
        spec = get_kiyotaka_shortcut_spec("okxbtcusdtp")

        assert spec is not None
        self.assertEqual(
            _get_symbol_search_queries(spec),
            ("BTC-USDT", "BTCUSDT", "BTC-USDT-SWAP"),
        )

    def test_search_result_rejects_spy_chart(self) -> None:
        self.assertFalse(
            _search_result_matches(
                "SPY/USD\nStocks\nNASDAQ",
                symbol="BTCUSDT",
                exchange="OKX.F",
            )
        )

    def test_search_result_matches_bitfinex_spot_not_derivative(self) -> None:
        self.assertTrue(
            _search_result_matches(
                "ETHUSDT\nBITFINEX\n-1.38%",
                symbol="ETHUSDT",
                exchange="BITFINEX",
            )
        )
        self.assertFalse(
            _search_result_matches(
                "ETHUSDT\nBITFINEX.F\n-1.39%",
                symbol="ETHUSDT",
                exchange="BITFINEX",
            )
        )

    def test_search_result_matches_bitfinex_derivative_tether_label(self) -> None:
        self.assertTrue(
            _search_result_matches(
                "BITFINEX.F\nETHTether\nEthereum / Tether\nPERP\n$2,282.30",
                symbol="ETHUSDT",
                exchange="BITFINEX.F",
            )
        )
        self.assertFalse(
            _search_result_matches(
                "BITFINEX\nETHTether\nEthereum / Tether\nSPOT\n$2,281.50",
                symbol="ETHUSDT",
                exchange="BITFINEX.F",
            )
        )

    def test_symbol_group_header_does_not_match_specific_market(self) -> None:
        self.assertFalse(_symbol_matches_text("ETH\nEthereum\n+6\n13 markets", "ETHUSDT"))

    def test_chart_text_matches_expected_btc_symbol(self) -> None:
        self.assertTrue(_chart_text_matches_symbol("BTC-USDT-SWAP 1m Heatmap", "BTCUSDT"))

    def test_chart_text_matches_bitfinex_tether_symbol(self) -> None:
        self.assertTrue(_chart_text_matches_symbol("BITFINEX\nETHUST\nHeatmap", "ETHUSDT"))
        self.assertTrue(_chart_text_matches_symbol("BITFINEX\nETHUST\nHeatmap", "ETHUST"))

    def test_chart_exchange_matches_bitfinex_spot_not_derivative(self) -> None:
        self.assertTrue(_chart_text_matches_exchange("BITFINEX\nETHUST\n5m", "BITFINEX"))
        self.assertFalse(_chart_text_matches_exchange("BITFINEX.F\nETHF0:USTF0\n5m", "BITFINEX"))
        self.assertFalse(_chart_text_matches_exchange("BITFINEX.D\nETHF0:USTF0\n5m", "BITFINEX"))

    def test_chart_text_matches_bitfinex_futures_tether_symbol(self) -> None:
        self.assertTrue(_chart_text_matches_symbol("BITFINEX.D\nETHF0:USTF0\nHeatmap", "ETHUSDT"))

    def test_chart_text_rejects_spy_symbol(self) -> None:
        self.assertFalse(_chart_text_matches_symbol("SPY/USD 1m Heatmap", "BTCUSDT"))

    def test_extract_visible_price_bounds_filters_around_focus_prices(self) -> None:
        text = "1m\n15m\nVOL 3.7M\n2550.00\n2500.00\n2291.50\n2200.00\n-1.31%"

        bounds = _extract_visible_price_bounds(text, (2500, 2200))

        self.assertEqual(bounds, (2200.0, 2550.0))

    def test_extract_visible_price_bounds_rebuilds_split_chart_digits(self) -> None:
        text = "Heatmap\n2\n5\n0\n0\n.\n0\n0\n2\n2\n0\n0\n.\n0\n0\n-1\n.\n31\n%"

        bounds = _extract_visible_price_bounds(text, (2500, 2200))

        self.assertEqual(bounds, (2200.0, 2500.0))

    def test_price_bounds_include_focus_requires_all_target_prices(self) -> None:
        self.assertTrue(_price_bounds_include_focus((2190, 2510), (2200, 2500)))
        self.assertFalse(_price_bounds_include_focus((2250, 2320), (2200, 2500)))

    def test_bitfinex_visual_focus_keeps_far_api_walls_visible(self) -> None:
        spec = get_kiyotaka_shortcut_spec("bipaeth")

        assert spec is not None
        self.assertEqual(_get_visual_focus_prices(spec, (2282.5, 2630, 2655, 2055)), (2282.5, 2630.0, 2655.0, 2055.0))

    def test_bitfinex_visual_focus_keeps_nearby_api_walls(self) -> None:
        spec = get_kiyotaka_shortcut_spec("bipaeth")

        assert spec is not None
        self.assertEqual(_get_visual_focus_prices(spec, (2282.5, 2300, 2270)), (2282.5, 2300.0, 2270.0))

    def test_bitfinex_heatmap_capture_is_tuned_for_visible_order_walls(self) -> None:
        spec = get_kiyotaka_shortcut_spec("bipaeth")

        assert spec is not None
        self.assertTrue(_should_tune_bitfinex_heatmap(spec))

    def test_bitfinex_price_scale_gesture_defaults_are_bounded(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BITFINEX_ETH_PRICE_SCALE_DRAGS": "9",
                "BITFINEX_ETH_PRICE_SCALE_DRAG_PIXELS": "999",
                "BITFINEX_ETH_PRICE_SCALE_DRAG_STEPS": "99",
            },
        ):
            self.assertEqual(_get_bitfinex_price_scale_drag_count(), 6)
            self.assertEqual(_get_bitfinex_price_scale_drag_pixels(), 600)
            self.assertEqual(_get_bitfinex_price_scale_drag_steps(), 12)

        with patch.dict(
            os.environ,
            {
                "BITFINEX_ETH_PRICE_SCALE_DRAGS": "bad",
                "BITFINEX_ETH_PRICE_SCALE_DRAG_PIXELS": "bad",
                "BITFINEX_ETH_PRICE_SCALE_DRAG_STEPS": "bad",
            },
        ):
            self.assertEqual(_get_bitfinex_price_scale_drag_count(), 3)
            self.assertEqual(_get_bitfinex_price_scale_drag_pixels(), 350)
            self.assertEqual(_get_bitfinex_price_scale_drag_steps(), 2)

    def test_kiyotaka_chart_url_detection(self) -> None:
        self.assertTrue(_is_kiyotaka_chart_url("https://chart.kiyotaka.ai/e08ZIIOu"))
        self.assertFalse(_is_kiyotaka_chart_url("https://auth.privy.io/apps/example"))

    def test_overlay_price_bounds_falls_back_when_dom_bounds_are_too_narrow(self) -> None:
        bounds = _get_overlay_price_bounds((2284.6, 2285.2), (2282.5, 2630, 2655, 2055))

        assert bounds is not None
        self.assertLess(bounds[0], 2055)
        self.assertGreater(bounds[1], 2655)

    def test_png_heatmap_layer_detects_long_yellow_rows(self) -> None:
        png_bytes = _make_test_png(420, 300, yellow_rows=(120, 160))

        self.assertTrue(_png_has_heatmap_layer(png_bytes))

    def test_png_heatmap_layer_rejects_short_yellow_marks(self) -> None:
        png_bytes = _make_test_png(420, 300, short_marks=True)

        self.assertFalse(_png_has_heatmap_layer(png_bytes))

    def test_png_heatmap_layer_detects_diffuse_heatmap_pixels(self) -> None:
        png_bytes = _make_test_png(420, 300, diffuse_heatmap=True)

        self.assertTrue(_png_has_heatmap_layer(png_bytes))


class KiyotakaScreenshotRangeAdjustmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_far_api_focus_zooms_out_until_target_prices_are_visible(self) -> None:
        page = _FakeKiyotakaPage(
            [
                "BTC-USDT-SWAP\n75918.0\n75780.00\n75750.00\n75690.00",
                "BTC-USDT-SWAP\n53200.00\n53000.00\n50900.00\n50800.00",
            ]
        )

        await _adjust_chart_range_to_focus_prices(page, (50900.0, 53000.0), max_attempts=3)

        self.assertEqual(page.mouse.drag_count, 1)
        self.assertGreater(page.mouse.moves[-1][1], page.mouse.moves[0][1])

    async def test_indicator_values_do_not_make_far_focus_look_visible(self) -> None:
        page = _FakeKiyotakaPage(
            [
                "BTC-USDT-SWAP\n76244.50\n78250.00\n74250.00\nCVD (BTC)\n150.00M\n125.00M\n75.00M",
                "BTC-USDT-SWAP\n76244.50\n78250.00\n74250.00\nCVD (BTC)\n150.00M\n125.00M\n75.00M",
            ]
        )

        await _adjust_chart_range_to_focus_prices(page, (50900.0, 53000.0), max_attempts=2)

        self.assertEqual(page.mouse.drag_count, 2)

    async def test_price_scale_bounds_stop_far_focus_before_axis_overshoots(self) -> None:
        page = _FakeKiyotakaPage(
            [
                "BTC-USDT-SWAP\n76244.50\n78250.00\n74250.00",
            ],
            scale_texts=[
                "78250.00\n77500.00\n76250.00\n74250.00",
                "80000.00\n70000.00\n60000.00\n50000.00",
            ],
        )

        await _adjust_chart_range_to_focus_prices(page, (50900.0, 53000.0), max_attempts=5)

        self.assertEqual(page.mouse.drag_count, 1)

    async def test_read_main_price_scale_bounds_uses_scale_text_only(self) -> None:
        page = _FakeKiyotakaPage(
            ["CVD (BTC)\n150.00M\n75.00M"],
            scale_texts=["80000.00\n70000.00\n60000.00\n50000.00"],
        )

        bounds = await _read_main_price_scale_bounds(page)

        self.assertEqual(bounds, (50000.0, 80000.0))

    async def test_clean_heatmap_capture_clip_removes_lower_indicator_panel(self) -> None:
        page = _FakeKiyotakaPage([])

        clip = await _get_clean_heatmap_capture_clip(page)

        self.assertEqual(clip, {"x": 0, "y": 0, "width": 2048, "height": 868})

    async def test_clean_heatmap_capture_clip_can_be_disabled(self) -> None:
        page = _FakeKiyotakaPage([])

        with patch.dict(os.environ, {"KIYOTAKA_CLEAN_CAPTURE": "0"}):
            clip = await _get_clean_heatmap_capture_clip(page)

        self.assertIsNone(clip)

    def test_clean_heatmap_capture_defaults_on(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(_kiyotaka_clean_capture_enabled())

    def test_indicator_cleanup_defaults_on_and_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(_kiyotaka_indicator_cleanup_enabled())

        with patch.dict(os.environ, {"KIYOTAKA_INDICATOR_CLEANUP": "off"}):
            self.assertFalse(_kiyotaka_indicator_cleanup_enabled())

    def test_indicator_cleanup_succeeds_when_price_scale_expands(self) -> None:
        before = {"x": 1906.0, "y": 86.0, "width": 90.0, "height": 560.0}
        after = {"x": 1906.0, "y": 86.0, "width": 90.0, "height": 720.0}

        self.assertTrue(_indicator_cleanup_succeeded(before, after, 900))

    def test_indicator_cleanup_rejects_unchanged_price_scale(self) -> None:
        before = {"x": 1906.0, "y": 86.0, "width": 90.0, "height": 560.0}
        after = {"x": 1906.0, "y": 86.0, "width": 90.0, "height": 570.0}

        self.assertFalse(_indicator_cleanup_succeeded(before, after, 900))

    def test_main_price_scale_looks_clean_near_bottom(self) -> None:
        self.assertTrue(_main_price_scale_looks_clean({"x": 1906.0, "y": 86.0, "width": 90.0, "height": 720.0}, 900))
        self.assertFalse(_main_price_scale_looks_clean({"x": 1906.0, "y": 86.0, "width": 90.0, "height": 560.0}, 900))

    def test_price_scale_zoom_drag_pixels_are_bounded(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_get_kiyotaka_price_scale_zoom_drag_pixels(), 120)

        with patch.dict(os.environ, {"KIYOTAKA_PRICE_SCALE_ZOOM_DRAG_PIXELS": "999"}):
            self.assertEqual(_get_kiyotaka_price_scale_zoom_drag_pixels(), 360)

        with patch.dict(os.environ, {"KIYOTAKA_PRICE_SCALE_ZOOM_DRAG_PIXELS": "bad"}):
            self.assertEqual(_get_kiyotaka_price_scale_zoom_drag_pixels(), 120)


class _FakeLocator:
    def __init__(self, page: "_FakeKiyotakaPage") -> None:
        self._page = page

    async def inner_text(self, timeout: int = 2500) -> str:
        index = min(self._page.read_count, len(self._page.texts) - 1)
        self._page.read_count += 1
        return self._page.texts[index]


class _FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []
        self.drag_count = 0

    async def move(self, x: int, y: int, steps: int | None = None) -> None:
        _ = steps
        self.moves.append((x, y))

    async def down(self) -> None:
        pass

    async def up(self) -> None:
        self.drag_count += 1


class _FakeKiyotakaPage:
    viewport_size = {"width": 2048, "height": 900}

    def __init__(self, texts: list[str], *, scale_texts: list[str] | None = None) -> None:
        self.texts = texts
        self.scale_texts = scale_texts or []
        self.read_count = 0
        self.scale_read_count = 0
        self.mouse = _FakeMouse()

    def locator(self, selector: str) -> _FakeLocator:
        self.assert_selector = selector
        return _FakeLocator(self)

    async def evaluate(self, script: str):
        if "innerText" in script:
            if not self.scale_texts:
                return ""
            index = min(self.scale_read_count, len(self.scale_texts) - 1)
            self.scale_read_count += 1
            return self.scale_texts[index]
        return {"x": 1906, "y": 86, "width": 90, "height": 560}

    async def wait_for_timeout(self, timeout: int) -> None:
        _ = timeout


def _make_test_png(
    width: int,
    height: int,
    *,
    yellow_rows: tuple[int, ...] = (),
    short_marks: bool = False,
    diffuse_heatmap: bool = False,
) -> bytes:
    import struct
    import zlib

    rows = []
    for y in range(height):
        row = bytearray([0, 0, 0] * width)
        if y in yellow_rows:
            for x in range(90, 310):
                offset = x * 3
                row[offset : offset + 3] = bytes([245, 245, 0])
        if short_marks and y == 120:
            for x in range(90, 140):
                offset = x * 3
                row[offset : offset + 3] = bytes([245, 245, 0])
        if diffuse_heatmap and 90 <= y < 180:
            for x in range(90, 310, 6):
                offset = x * 3
                row[offset : offset + 3] = bytes([215, 245, 0])
            for x in range(95, 315, 5):
                offset = x * 3
                row[offset : offset + 3] = bytes([90, 20, 135])
        rows.append(b"\x00" + bytes(row))

    def chunk(name: bytes, payload: bytes) -> bytes:
        body = name + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk("IHDR".encode(), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk("IDAT".encode(), zlib.compress(b"".join(rows)))
        + chunk("IEND".encode(), b"")
    )


if __name__ == "__main__":
    unittest.main()
