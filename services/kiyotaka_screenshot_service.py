from __future__ import annotations

import asyncio
import importlib.util
import os
import re
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
import struct
import zlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.kiyotaka_shortcut_service import KiyotakaShortcutSpec


class KiyotakaScreenshotError(RuntimeError):
    pass


class KiyotakaHeatmapUnavailableError(KiyotakaScreenshotError):
    pass


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


async def capture_kiyotaka_screenshot(
    spec: "KiyotakaShortcutSpec",
    *,
    timeout_ms: int = 45000,
    debug_path: str | None = None,
    focus_prices: Sequence[float] = (),
) -> bytes:
    candidates = _build_capture_candidates(spec)
    last_error: KiyotakaScreenshotError | None = None
    heatmap_unavailable_errors: list[KiyotakaScreenshotError] = []
    for candidate in candidates:
        try:
            return await _capture_kiyotaka_screenshot_single(
                candidate,
                timeout_ms=timeout_ms,
                debug_path=debug_path,
                focus_prices=focus_prices,
            )
        except KiyotakaHeatmapUnavailableError as exc:
            heatmap_unavailable_errors.append(exc)
            last_error = exc
            if len(candidates) == 1:
                raise
            continue
        except KiyotakaScreenshotError as exc:
            last_error = exc
            if len(candidates) == 1:
                raise
            continue

    if len(candidates) > 1:
        labels = ", ".join(f"{item.result_symbol}/{item.result_exchange}" for item in candidates)
        raise KiyotakaHeatmapUnavailableError(f"BITFINEX 후보 페어({labels})에서 히트맵 캡처를 만들지 못해 텍스트만 보냅니다.")
    raise last_error or KiyotakaScreenshotError("Kiyotaka 히트맵을 지원하는 BITFINEX 후보 페어를 찾지 못했습니다.")


def _build_capture_candidates(spec: "KiyotakaShortcutSpec") -> tuple["KiyotakaShortcutSpec", ...]:
    candidates = [spec]
    for search_query, result_symbol, result_exchange in spec.capture_fallback_targets:
        candidates.append(
            replace(
                spec,
                search_query=search_query,
                result_symbol=result_symbol,
                result_exchange=result_exchange,
            )
        )
    return tuple(candidates)


async def _get_reusable_kiyotaka_page(context, spec: "KiyotakaShortcutSpec"):
    best_page = None
    best_score = -1
    for index, candidate in enumerate(list(context.pages)):
        try:
            if candidate.is_closed() or not _is_kiyotaka_chart_url(candidate.url):
                continue
            score = 1
            if await _page_matches_capture_state(candidate, spec, timeout_ms=1200):
                score += 10
            score -= index * 0.01
            if score > best_score:
                best_score = score
                best_page = candidate
        except Exception:
            continue
    return best_page


async def _close_extra_kiyotaka_pages(context, *, keep_page) -> None:
    for candidate in list(context.pages):
        if candidate is keep_page:
            continue
        try:
            if candidate.is_closed() or not _is_kiyotaka_chart_url(candidate.url):
                continue
            await candidate.close()
        except Exception:
            continue


def _is_kiyotaka_chart_url(url: str) -> bool:
    return "chart.kiyotaka.ai" in (url or "").lower()


async def _page_matches_capture_state(
    page,
    spec: "KiyotakaShortcutSpec",
    *,
    timeout_ms: int = 2500,
) -> bool:
    try:
        text = await page.locator("body").inner_text(timeout=timeout_ms)
    except Exception:
        return False
    if not _chart_text_matches_symbol(text, spec.result_symbol):
        return False
    if not _chart_text_matches_exchange(text, spec.result_exchange):
        return False
    if spec.timeframe and spec.timeframe.upper() not in (text or "").upper():
        return False
    if spec.view and spec.view.upper() not in (text or "").upper():
        return False
    return True


async def _wait_for_heatmap_render(page, spec: "KiyotakaShortcutSpec") -> bool:
    if not _should_require_visible_heatmap(spec):
        await page.wait_for_timeout(800)
        return True

    timeout_ms = max(2500, int(os.getenv("KIYOTAKA_HEATMAP_RENDER_TIMEOUT_MS", "9000")))
    poll_ms = max(400, int(os.getenv("KIYOTAKA_HEATMAP_RENDER_POLL_MS", "900")))
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    while asyncio.get_running_loop().time() < deadline:
        await page.wait_for_timeout(poll_ms)
        try:
            probe = await page.screenshot(type="png")
        except Exception:
            continue
        if _png_has_heatmap_layer(probe):
            return True
    return False


async def _capture_kiyotaka_screenshot_single(
    spec: "KiyotakaShortcutSpec",
    *,
    timeout_ms: int = 45000,
    debug_path: str | None = None,
    focus_prices: Sequence[float] = (),
) -> bytes:
    if not playwright_available():
        raise KiyotakaScreenshotError("Playwright 패키지가 아직 설치되지 않았습니다.")

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - import path depends on runtime
        raise KiyotakaScreenshotError(f"Playwright import 실패: {exc}") from exc

    page = None
    try:
        async with async_playwright() as playwright:
            context_kwargs = {
                "viewport": {"width": 2048, "height": 900},
                "color_scheme": "dark",
                "locale": "en-US",
            }
            cdp_url = os.getenv("KIYOTAKA_CDP_URL", "").strip()
            close_context = True
            close_browser = True
            if cdp_url:
                browser = await playwright.chromium.connect_over_cdp(cdp_url)
                if not browser.contexts:
                    raise KiyotakaScreenshotError("Kiyotaka 로그인 브라우저에 연결했지만 열린 컨텍스트가 없습니다.")
                context = browser.contexts[0]
                close_context = False
                close_browser = False
                page = await _get_reusable_kiyotaka_page(context, spec)
            else:
                browser = await playwright.chromium.launch(
                    channel="chromium",
                    headless=True,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--ignore-gpu-blocklist",
                        "--enable-unsafe-swiftshader",
                        "--use-gl=angle",
                        "--use-angle=swiftshader",
                    ],
                )
                storage_state_path = os.getenv("KIYOTAKA_STORAGE_STATE_PATH", "").strip()
                if storage_state_path and os.path.exists(storage_state_path):
                    context_kwargs["storage_state"] = storage_state_path
                context = await browser.new_context(**context_kwargs)
            if page is None:
                page = await context.new_page()
            with suppress(Exception):
                await page.set_viewport_size(context_kwargs["viewport"])
            page.set_default_timeout(timeout_ms)
            await _close_extra_kiyotaka_pages(context, keep_page=page)

            reused_page_reloaded = False
            if _is_kiyotaka_chart_url(page.url):
                with suppress(Exception):
                    await page.bring_to_front()
                _maybe_write_debug_reload_marker("before_reload", page.url)
                # Reused pages can stay scrolled/paused on an old time window.
                # Reloading is the most reliable way to return to the latest candles.
                await page.reload(wait_until="commit", timeout=timeout_ms)
                reused_page_reloaded = True
                _maybe_write_debug_reload_marker("after_reload", page.url)
            else:
                await page.goto(spec.chart_url, wait_until="commit", timeout=timeout_ms)
            await _wait_for_kiyotaka_app_ready(page)

            await _dismiss_optional_ui(page)
            await _close_optional_terminal_panels(page)
            if reused_page_reloaded or not await _page_matches_capture_state(page, spec):
                await _select_symbol(page, spec)
                await _select_timeframe(page, spec.timeframe)
                await _select_view(page, spec.view)
            heatmap_enabled = await _enable_heatmap_if_needed(page)
            await _configure_heatmap_for_bitfinex_orders(page, spec)
            heatmap_visible = await _wait_for_heatmap_render(page, spec)
            await _verify_selected_symbol(page, spec)
            await _align_chart_to_latest(page)
            if _should_require_visible_heatmap(spec):
                if not heatmap_enabled:
                    raise KiyotakaHeatmapUnavailableError(f"{spec.result_symbol} / {spec.result_exchange} 히트맵을 켤 수 없습니다.")
                if not heatmap_visible:
                    raise KiyotakaHeatmapUnavailableError(f"{spec.result_symbol} / {spec.result_exchange} 히트맵 레이어가 보이지 않습니다.")
            indicators_cleaned = await _try_show_heatmap_only_indicators(page)
            await _adjust_chart_range(page, spec, focus_prices=focus_prices)
            await _verify_selected_symbol(page, spec)
            await _close_optional_terminal_panels(page)
            await _park_mouse_away_from_chart(page)

            capture_clip = None if indicators_cleaned else await _get_clean_heatmap_capture_clip(page)
            if capture_clip is None:
                screenshot = await page.screenshot(type="png")
            else:
                screenshot = await page.screenshot(type="png", clip=capture_clip)
            if close_browser:
                await page.close()
            else:
                await _close_extra_kiyotaka_pages(context, keep_page=page)
            if close_context:
                await context.close()
            if close_browser:
                await browser.close()
            return screenshot
    except PlaywrightTimeoutError as exc:
        if page is not None and debug_path:
            await _try_write_debug_screenshot(page, debug_path)
        raise KiyotakaScreenshotError("차트 로딩 시간이 너무 오래 걸렸습니다.") from exc
    except KiyotakaScreenshotError:
        if page is not None and debug_path:
            await _try_write_debug_screenshot(page, debug_path)
        raise
    except Exception as exc:
        if page is not None and debug_path:
            await _try_write_debug_screenshot(page, debug_path)
        message = str(exc)
        if "Executable doesn't exist" in message:
            raise KiyotakaScreenshotError("Chromium 런타임이 아직 설치되지 않았습니다.") from exc
        raise KiyotakaScreenshotError(f"스크린샷 생성 실패: {message}") from exc


async def _dismiss_optional_ui(page) -> None:
    for label in ("Accept", "I understand", "Not now", "Close", "Skip"):
        locator = page.get_by_role("button", name=label)
        try:
            if await locator.count() and await locator.first.is_visible():
                await locator.first.click()
                await page.wait_for_timeout(500)
        except Exception:
            continue


def _maybe_write_debug_reload_marker(phase: str, url: str) -> None:
    path = os.getenv("KIYOTAKA_DEBUG_RELOAD_MARKER_PATH", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{phase}\t{url}\n")
    except Exception:
        return


async def _align_chart_to_latest(page) -> None:
    """
    Best-effort: align the chart viewport to the right edge (latest time).

    Heatmap UIs can remain panned into the past; this tries to bring the view back to "now".
    """

    realtime_patterns = [
        re.compile(r"(go to|jump to).*(real\s*time|realtime)|real\s*time", re.I),
        re.compile(r"(latest|now|live)$", re.I),
    ]
    for pattern in realtime_patterns:
        with suppress(Exception):
            candidates = [
                page.get_by_role("button", name=pattern),
                page.get_by_text(pattern).first,
            ]
            if await _click_first_visible(candidates, force=True):
                await page.wait_for_timeout(650)
                break

    with suppress(Exception):
        await _click_first_visible(
            [
                page.locator(
                    '[aria-label*="real" i], [title*="real" i], [data-testid*="real" i], '
                    '[aria-label*="latest" i], [title*="latest" i], [data-testid*="latest" i], '
                    '[aria-label*="now" i], [title*="now" i], [data-testid*="now" i]'
                ),
            ],
            force=True,
        )
        await page.wait_for_timeout(250)

    viewport = page.viewport_size or {"width": 2048, "height": 900}
    width = int(viewport.get("width") or 2048)
    height = int(viewport.get("height") or 900)

    with suppress(Exception):
        await page.mouse.click(int(width * 0.62), int(height * 0.38))
        await page.wait_for_timeout(80)

    for key in ("End", "Shift+End", "Control+End", "Meta+End"):
        with suppress(Exception):
            await page.keyboard.press(key)
            await page.wait_for_timeout(120)

    await _pad_chart_slightly_into_future(page, width=width, height=height)

    with suppress(Exception):
        await page.wait_for_timeout(450)


async def _pad_chart_slightly_into_future(page, *, width: int, height: int) -> None:
    pixels = _get_kiyotaka_latest_future_pad_pixels()
    if pixels <= 0:
        return

    start_x = min(width - 90, max(220, int(width * 0.84)))
    end_x = max(90, start_x - pixels)
    y = min(height - 140, max(130, int(height * 0.48)))
    with suppress(Exception):
        await page.mouse.move(start_x, y)
        await page.mouse.down()
        await page.mouse.move(end_x, y, steps=10)
        await page.mouse.up()
        await page.wait_for_timeout(300)


def _get_kiyotaka_latest_future_pad_pixels() -> int:
    raw = os.getenv("KIYOTAKA_LATEST_FUTURE_PAD_PIXELS", "96").strip()
    try:
        value = int(raw)
    except ValueError:
        return 96
    return min(260, max(0, value))


async def _park_mouse_away_from_chart(page) -> None:
    viewport = page.viewport_size or {"width": 2048, "height": 900}
    width = int(viewport.get("width") or 2048)
    with suppress(Exception):
        await page.mouse.move(max(16, width - 22), 22)
        await page.wait_for_timeout(150)


async def _wait_for_kiyotaka_app_ready(page, *, timeout_ms: int = 60000) -> None:
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    while asyncio.get_running_loop().time() < deadline:
        try:
            text = await page.locator("body").inner_text(timeout=5000)
        except Exception:
            text = ""
        if "KIYOTAKA" in text and ("Heatmap" in text or "Indicators" in text):
            return
        await page.wait_for_timeout(2500)
    raise KiyotakaScreenshotError("Kiyotaka 앱 화면이 준비되지 않았습니다.")


async def _select_symbol(page, spec: "KiyotakaShortcutSpec") -> None:
    search_input = await _find_search_input(page)
    if search_input is None:
        await page.keyboard.press("Control+K")
        await page.wait_for_timeout(900)
        search_input = await _find_search_input(page)

    if search_input is None:
        await _try_open_symbol_picker(page)
        await page.wait_for_timeout(1200)
        search_input = await _find_search_input(page)

    if search_input is None:
        raise KiyotakaScreenshotError("심볼 검색창을 찾지 못했습니다.")

    field = search_input
    for query in _get_symbol_search_queries(spec):
        await field.click(force=True)
        await field.press("Control+A")
        await field.type(query, delay=40)
        await page.wait_for_timeout(1800)
        await _select_search_market_type_if_needed(page, spec.result_exchange)
        if await _pick_search_result(page, symbol=spec.result_symbol, exchange=spec.result_exchange):
            break
    else:
        await _close_search_overlay(page)
        raise KiyotakaScreenshotError(f"{spec.result_symbol} / {spec.result_exchange} 검색 결과를 찾지 못했습니다.")
    await page.wait_for_timeout(1500)
    await _close_search_overlay(page)


async def _select_timeframe(page, timeframe: str) -> None:
    if not timeframe:
        return

    visible_button = page.locator("button").filter(has_text=re.compile(rf"^\s*{re.escape(timeframe)}\s*$"))
    if await _click_first_visible([visible_button], force=True):
        await page.wait_for_timeout(800)
        return

    dropdown_triggers = [
        page.locator(".chevron-btn").first,
        page.locator(".tb-interval-selector").first,
        page.locator(".pill-container").first,
    ]
    if not await _click_first_visible(dropdown_triggers, force=True):
        return
    await page.wait_for_timeout(800)

    rows = [
        page.locator(".tb-interval-dropdown .dropdown-row").filter(has_text=re.compile(rf"^\s*{re.escape(timeframe)}\s*$")),
        page.get_by_text(timeframe, exact=True),
    ]
    if await _click_first_visible(rows, force=True):
        await page.wait_for_timeout(1600)


async def _select_view(page, view_name: str) -> None:
    button = page.get_by_role("button", name=view_name)
    if await button.count():
        await button.first.click()
        await page.wait_for_timeout(1200)
        return

    text = page.get_by_text(view_name, exact=True)
    if await text.count():
        await text.first.click()
        await page.wait_for_timeout(1200)
        return

    raise KiyotakaScreenshotError(f"{view_name} 버튼을 찾지 못했습니다.")


async def _try_write_debug_screenshot(page, debug_path: str) -> None:
    try:
        await page.screenshot(path=debug_path, type="png")
    except Exception:
        return


async def _find_search_input(page):
    candidates = [
        page.get_by_test_id("quick-search-input"),
        page.get_by_test_id("symbol-selection-search-input"),
        page.get_by_placeholder("Search symbols..."),
        page.get_by_placeholder("Search..."),
        page.locator('input[placeholder*="Search"]'),
    ]
    for locator in candidates:
        try:
            count = await locator.count()
            for index in range(count):
                item = locator.nth(index)
                if await item.is_visible():
                    return item
        except Exception:
            continue
    return None


def _get_symbol_search_queries(spec: "KiyotakaShortcutSpec") -> tuple[str, ...]:
    queries: list[str] = []

    def add(query: str) -> None:
        normalized = (query or "").strip()
        if normalized and normalized not in queries:
            queries.append(normalized)

    add(spec.search_query)
    add(spec.result_symbol)

    base, quote = _split_symbol(spec.result_symbol)
    if base and quote:
        add(f"{base}-{quote}")
        if quote == "USDT" and _compact_token(spec.result_exchange) in {"OKXF", "OKEXF"}:
            add(f"{base}-{quote}-SWAP")

    return tuple(queries)


async def _try_open_symbol_picker(page) -> None:
    symbol_candidates = (
        "BTCUSDT",
        "BTC-USDT",
        "ETHUSDT",
        "ETH-USDT",
        "ETHUST",
        "ETHF0:USTF0",
    )
    for label in symbol_candidates:
        locator = page.get_by_text(label, exact=True)
        try:
            if await locator.count() and await locator.first.is_visible():
                await locator.first.click()
                return
        except Exception:
            continue

    try:
        await page.mouse.click(100, 60)
    except Exception:
        return


async def _pick_search_result(page, *, symbol: str, exchange: str) -> bool:
    if await _pick_visible_search_result(page, symbol=symbol, exchange=exchange):
        return True
    for _attempt in range(2):
        if not await _expand_matching_symbol_group(page, symbol=symbol, exchange=exchange):
            return False
        if await _pick_visible_search_result(page, symbol=symbol, exchange=exchange):
            return True
    return False


async def _pick_visible_search_result(page, *, symbol: str, exchange: str) -> bool:
    candidates = [
        page.get_by_test_id("quick-search-result-item"),
        page.locator('[data-testid="quick-search-result-item"]'),
        page.locator(".venue-row"),
        page.locator(".asset-list__row-wrapper"),
    ]
    for locator in candidates:
        try:
            count = await locator.count()
            for index in range(min(count, 80)):
                item = locator.nth(index)
                text = (await item.inner_text()).upper()
                if _search_result_matches(text, symbol=symbol, exchange=exchange):
                    await item.scroll_into_view_if_needed()
                    await item.click(force=True)
                    return True
        except Exception:
            continue
    return False


async def _select_search_market_type_if_needed(page, exchange: str) -> None:
    compact_exchange = _compact_token(exchange)
    if not compact_exchange.endswith("F"):
        all_buttons = [
            page.locator("button.intent-filter__sp-btn").filter(has_text=re.compile(r"^\s*All\s*$", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"^\s*All\s*$", re.IGNORECASE)),
        ]
        if await _click_first_visible(all_buttons, force=True):
            await page.wait_for_timeout(1500)
        return
    perps_buttons = [
        page.locator("button.intent-filter__sp-btn").filter(has_text=re.compile(r"^\s*Perps\s*$", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"^\s*Perps\s*$", re.IGNORECASE)),
    ]
    if await _click_first_visible(perps_buttons, force=True):
        await page.wait_for_timeout(1500)


async def _expand_matching_symbol_group(page, *, symbol: str, exchange: str = "") -> bool:
    base, _quote = _split_symbol(symbol)
    if not base:
        return False
    candidates = [
        page.locator(".asset-list__row-wrapper"),
        page.locator(".asset-row"),
        page.locator(".symbol-list-container div"),
    ]
    for locator in candidates:
        try:
            count = await locator.count()
            for index in range(min(count, 40)):
                item = locator.nth(index)
                text = await item.inner_text()
                compact = _compact_token(text)
                if base not in compact or not ("MARKETS" in compact or compact.startswith(base)):
                    continue
                if "BITFINEX" in compact:
                    continue
                await item.scroll_into_view_if_needed()
                for action in ("row", "market_count", "left", "middle", "double", "enter"):
                    try:
                        box = await item.bounding_box()
                        if action == "row":
                            await item.click(force=True)
                        elif action == "market_count":
                            market_count = item.locator(".asset-row__market-count")
                            if await market_count.count() and await market_count.first.is_visible():
                                await market_count.first.click(force=True)
                            else:
                                continue
                        elif box and action == "left":
                            await page.mouse.click(box["x"] + 20, box["y"] + (box["height"] / 2))
                        elif box and action == "middle":
                            await page.mouse.click(box["x"] + min(box["width"] * 0.55, 300), box["y"] + (box["height"] / 2))
                        elif box and action == "double":
                            await page.mouse.dblclick(box["x"] + (box["width"] / 2), box["y"] + (box["height"] / 2))
                        elif action == "enter":
                            await item.click(force=True)
                            await page.wait_for_timeout(250)
                            await page.keyboard.press("Enter")
                        else:
                            continue
                        await page.wait_for_timeout(1200)
                        if await _search_results_include_exchange(page, exchange):
                            return True
                    except Exception:
                        continue
                return True
        except Exception:
            continue
    return False


async def _search_results_include_exchange(page, exchange: str) -> bool:
    if not exchange:
        return True
    locators = [
        page.get_by_test_id("quick-search-result-item"),
        page.locator('[data-testid="quick-search-result-item"]'),
        page.locator(".venue-row"),
        page.locator(".asset-list__row-wrapper"),
        page.locator(".asset-row"),
    ]
    for locator in locators:
        try:
            count = await locator.count()
            for index in range(min(count, 80)):
                text = (await locator.nth(index).inner_text()).upper()
                if _exchange_matches(text, exchange):
                    return True
        except Exception:
            continue
    return False


async def _enable_heatmap_if_needed(page) -> bool:
    for _ in range(4):
        await _open_heatmap_menu(page)
        state = await _read_heatmap_menu_state(page)
        if state is True:
            await _close_heatmap_menu(page)
            return True
        if state is False:
            toggles = [
                page.locator(".heatmap-dropdown .app-toggle"),
                page.locator(".app-toggle").filter(has_text="OFF"),
                page.get_by_role("button", name="OFF"),
            ]
            await _click_first_visible(toggles, force=True)
            await page.wait_for_timeout(2500)
            if await _accept_heatmap_guest_if_present(page):
                await page.wait_for_timeout(2500)
            continue
        await page.wait_for_timeout(1200)

    await _close_heatmap_menu(page)
    return False


async def _open_heatmap_menu(page) -> None:
    try:
        if await page.locator(".heatmap-dropdown").count():
            return
    except Exception:
        return

    candidates = [
        page.locator(".heatmap-trigger"),
        page.get_by_test_id("tb-heatmap-trigger-btn"),
        page.locator('[data-testid="tb-heatmap-trigger-btn"]'),
        page.get_by_role("button", name=re.compile(r"heatmap", re.IGNORECASE)),
        page.get_by_text("Heatmap", exact=True),
    ]
    await _click_first_visible(candidates, force=True)
    await page.wait_for_timeout(700)


async def _read_heatmap_menu_state(page) -> bool | None:
    try:
        dropdown = page.locator(".heatmap-dropdown").first
        if not await dropdown.count():
            return None
        text = (await dropdown.inner_text(timeout=2500)).upper()
    except Exception:
        return None
    if "ON" in text:
        return True
    if "OFF" in text:
        return False
    return None


async def _close_heatmap_menu(page) -> None:
    try:
        if await page.locator(".heatmap-dropdown").count():
            await page.mouse.click(700, 180)
            await page.wait_for_timeout(700)
    except Exception:
        return


async def _accept_heatmap_guest_if_present(page) -> bool:
    guest = page.get_by_text("Continue as Guest", exact=True)
    try:
        if await guest.count() and await guest.first.is_visible():
            await guest.first.click(force=True)
            await page.wait_for_timeout(10000)
            return True
    except Exception:
        return False
    return False


async def _configure_heatmap_for_bitfinex_orders(page, spec: "KiyotakaShortcutSpec") -> None:
    if not _should_tune_bitfinex_heatmap(spec):
        return

    await _open_heatmap_menu(page)
    if await _read_heatmap_menu_state(page) is not True:
        await _close_heatmap_menu(page)
        return

    await _click_heatmap_testid(page, "tb-heatmap-denomination-coin-btn")
    await _click_heatmap_testid(page, "tb-heatmap-resolution-hd-btn")
    await _click_heatmap_testid(page, "tb-heatmap-scheme-mono-btn")
    await _click_heatmap_testid(page, "tb-heatmap-noise-preset-more-btn")
    await _set_heatmap_stepper_value(page, 0, _get_bitfinex_heatmap_threshold())
    await _set_heatmap_stepper_value(page, 1, _get_bitfinex_heatmap_ceiling())
    await _click_heatmap_testid(page, "tb-heatmap-view-magnifier-btn")
    await page.wait_for_timeout(1200)
    await _close_heatmap_menu(page)


def _should_tune_bitfinex_heatmap(spec: "KiyotakaShortcutSpec") -> bool:
    exchange = (spec.result_exchange or "").upper()
    symbol = (spec.result_symbol or "").upper()
    return "HEATMAP" in (spec.view or "").upper() and "BITFINEX" in exchange and "ETH" in symbol


def _get_bitfinex_heatmap_threshold() -> str:
    return os.getenv("BITFINEX_ETH_HEATMAP_THRESHOLD", "0").strip() or "0"


def _get_bitfinex_heatmap_ceiling() -> str:
    return os.getenv("BITFINEX_ETH_HEATMAP_CEILING", "105").strip() or "105"


async def _click_heatmap_testid(page, testid: str) -> bool:
    return await _click_first_visible([page.locator(f'[data-testid="{testid}"]')], force=True)


async def _set_heatmap_stepper_value(page, index: int, value: str) -> bool:
    try:
        inputs = page.locator(".heatmap-dropdown input.stepper-input")
        if await inputs.count() <= index:
            return False
        item = inputs.nth(index)
        if not await item.is_visible():
            return False
        await item.click(force=True)
        await item.press("Control+A")
        await item.type(str(value), delay=20)
        await item.press("Enter")
        await page.wait_for_timeout(800)
        return True
    except Exception:
        return False


async def _has_visible_text(page, text: str) -> bool:
    locator = page.get_by_text(text, exact=True)
    try:
        count = await locator.count()
        for index in range(min(count, 4)):
            if await locator.nth(index).is_visible():
                return True
    except Exception:
        return False
    return False


async def _click_first_visible(locators, *, force: bool = False) -> bool:
    for locator in locators:
        try:
            count = await locator.count()
            for index in range(min(count, 4)):
                item = locator.nth(index)
                if await item.is_visible():
                    await item.click(force=force)
                    return True
        except Exception:
            continue
    return False


async def _close_optional_terminal_panels(page) -> None:
    for _ in range(2):
        clicked = await _click_first_visible(
            [
                page.locator('[data-testid="terminal-close-btn"]'),
                page.locator(".terminal-close-btn"),
            ],
            force=True,
        )
        if not clicked:
            return
        await page.wait_for_timeout(500)


async def _try_show_heatmap_only_indicators(page) -> bool:
    if not _kiyotaka_indicator_cleanup_enabled():
        return False

    viewport = page.viewport_size or {"width": 2048, "height": 900}
    viewport_height = int(viewport.get("height") or 900)
    before_box = await _get_main_price_scale_box(page)
    if _main_price_scale_looks_clean(before_box, viewport_height):
        return True

    if not await _open_indicators_menu(page):
        return False

    changed_count = await _click_non_heatmap_indicator_controls(page)
    await _close_indicators_menu(page)
    if changed_count <= 0:
        return False

    await page.wait_for_timeout(1500)
    after_box = await _get_main_price_scale_box(page)
    return _indicator_cleanup_succeeded(before_box, after_box, viewport_height)


async def _open_indicators_menu(page) -> bool:
    return await _click_first_visible(
        [
            page.get_by_role("button", name=re.compile(r"Indicators?", re.IGNORECASE)),
            page.locator('[data-testid="tb-indicators-btn"]'),
            page.locator('[data-testid*="indicator" i]'),
            page.get_by_text(re.compile(r"Indicators?\s*(?:\(\d+\))?", re.IGNORECASE)),
        ],
        force=True,
    )


async def _click_non_heatmap_indicator_controls(page) -> int:
    try:
        result = await page.evaluate(
            """
            () => {
              const blockedPatterns = [
                /\\bCVD\\b/i,
                /\\bVRVP\\b/i,
                /\\bVol(?:ume)?\\b/i,
              ];
              const heatmapPattern = /heatmap|order\\s*book/i;
              const controlPattern = /hide|remove|delete|close|visible|visibility|eye|trash|toggle|off/i;
              const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const visibleText = (el) => (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
              const roots = Array.from(
                document.querySelectorAll('[role="dialog"], [role="menu"], [class*="dropdown" i], [class*="popover" i], [class*="modal" i], [class*="menu" i]')
              ).filter(isVisible);
              if (!roots.length) return 0;

              const rows = [];
              const seen = new Set();
              for (const root of roots) {
                const nodes = Array.from(root.querySelectorAll("*"));
                for (const node of nodes) {
                  const text = visibleText(node);
                  if (!text || heatmapPattern.test(text) || !blockedPatterns.some((pattern) => pattern.test(text))) continue;
                  let row = node;
                  for (let depth = 0; depth < 8 && row && row !== root.parentElement; depth += 1) {
                    const rect = row.getBoundingClientRect();
                    const rowText = visibleText(row);
                    if (
                      rowText &&
                      !heatmapPattern.test(rowText) &&
                      blockedPatterns.some((pattern) => pattern.test(rowText)) &&
                      rect.width >= 120 &&
                      rect.height >= 18 &&
                      rect.height <= 96
                    ) {
                      break;
                    }
                    row = row.parentElement;
                  }
                  if (!row || row === document.body || seen.has(row)) continue;
                  seen.add(row);
                  rows.push(row);
                }
              }

              let clicked = 0;
              for (const row of rows) {
                const controls = Array.from(row.querySelectorAll('button, [role="button"], input[type="checkbox"], input[type="radio"]')).filter(isVisible);
                if (!controls.length) continue;
                const preferred = controls.find((control) => {
                  const label = [
                    control.getAttribute("aria-label"),
                    control.getAttribute("title"),
                    control.getAttribute("data-testid"),
                    control.className,
                    visibleText(control),
                  ].filter(Boolean).join(" ");
                  return controlPattern.test(String(label));
                }) || controls[controls.length - 1];
                preferred.click();
                clicked += 1;
              }
              return clicked;
            }
            """
        )
    except Exception:
        return 0

    try:
        return int(result or 0)
    except (TypeError, ValueError):
        return 0


async def _close_indicators_menu(page) -> None:
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
    except Exception:
        return


def _kiyotaka_indicator_cleanup_enabled() -> bool:
    raw = os.getenv("KIYOTAKA_INDICATOR_CLEANUP", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _indicator_cleanup_succeeded(
    before_box: dict[str, float] | None,
    after_box: dict[str, float] | None,
    viewport_height: int,
) -> bool:
    if _main_price_scale_looks_clean(after_box, viewport_height):
        return True
    if before_box is None or after_box is None:
        return False
    try:
        return float(after_box["height"]) >= float(before_box["height"]) + 80
    except (KeyError, TypeError, ValueError):
        return False


def _main_price_scale_looks_clean(box: dict[str, float] | None, viewport_height: int) -> bool:
    if not box:
        return False
    try:
        bottom = float(box["y"]) + float(box["height"])
        height = float(box["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return height >= 500 and bottom >= max(0, viewport_height - 160)


async def _get_clean_heatmap_capture_clip(page) -> dict[str, int] | None:
    if not _kiyotaka_clean_capture_enabled():
        return None

    box = await _get_main_price_scale_box(page)
    if box is None:
        return None

    viewport = page.viewport_size or {"width": 2048, "height": 900}
    width = int(viewport.get("width") or 2048)
    height = int(viewport.get("height") or 900)
    price_bottom = int(float(box.get("y", 0)) + float(box.get("height", 0)) + 24)
    time_axis_bottom = height - _get_kiyotaka_clean_capture_bottom_margin()
    clip_height = min(height, max(min(height, 540), price_bottom, time_axis_bottom))
    if clip_height >= height - 24:
        return None
    return {"x": 0, "y": 0, "width": width, "height": clip_height}


def _kiyotaka_clean_capture_enabled() -> bool:
    raw = os.getenv("KIYOTAKA_CLEAN_CAPTURE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _get_kiyotaka_clean_capture_bottom_margin() -> int:
    raw = os.getenv("KIYOTAKA_CLEAN_CAPTURE_BOTTOM_MARGIN", "32").strip()
    try:
        value = int(raw)
    except ValueError:
        return 32
    return min(180, max(0, value))


async def _adjust_chart_range(page, spec: "KiyotakaShortcutSpec", *, focus_prices: Sequence[float] = ()) -> None:
    normalized_focus_prices = _get_visual_focus_prices(spec, focus_prices)
    if normalized_focus_prices:
        if _should_tune_bitfinex_heatmap(spec):
            await _fit_bitfinex_eth_price_range(page)
            return
        await _adjust_chart_range_to_focus_prices(page, normalized_focus_prices)
        return

    if spec.chart_drag_y == 0:
        return

    start_x = 1180
    start_y = 410
    end_y = start_y + spec.chart_drag_y
    try:
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.mouse.move(start_x, end_y, steps=24)
        await page.mouse.up()
    except Exception:
        return


async def _fit_bitfinex_eth_price_range(page) -> None:
    await _close_optional_terminal_panels(page)
    box = await _get_main_price_scale_box(page)
    viewport = page.viewport_size or {"width": 2048, "height": 900}
    width = int(viewport.get("width") or 2048)
    height = int(viewport.get("height") or 900)
    if box is None:
        scale_x = max(1200, width - 73)
        reset_y = 360
        start_y = 450
    else:
        scale_x = int(box["x"] + (box["width"] * 0.5))
        reset_y = int(box["y"] + (box["height"] * 0.5))
        start_y = int(box["y"] + (box["height"] * 0.65))

    drag_pixels = _get_bitfinex_price_scale_drag_pixels()
    drag_count = _get_bitfinex_price_scale_drag_count()
    drag_steps = _get_bitfinex_price_scale_drag_steps()
    end_y = min(height - 95, start_y + drag_pixels)

    try:
        await page.mouse.dblclick(scale_x, reset_y)
        await page.wait_for_timeout(500)
        for _ in range(drag_count):
            await page.mouse.move(scale_x, start_y)
            await page.mouse.down()
            await page.mouse.move(scale_x, end_y, steps=drag_steps)
            await page.mouse.up()
            await page.wait_for_timeout(250)
    except Exception:
        return


async def _get_main_price_scale_box(page) -> dict[str, float] | None:
    try:
        box = await page.evaluate(
            """
            () => {
              const candidates = Array.from(document.querySelectorAll(".titan-charts-scale-section"));
              const item = candidates.find((el) => {
                const rect = el.getBoundingClientRect();
                return rect.width > 30 && rect.height > 250 && rect.y < window.innerHeight * 0.75;
              });
              if (!item) return null;
              const rect = item.getBoundingClientRect();
              return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }
            """
        )
    except Exception:
        return None
    if not box:
        return None
    try:
        return {
            "x": float(box["x"]),
            "y": float(box["y"]),
            "width": float(box["width"]),
            "height": float(box["height"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _get_bitfinex_price_scale_drag_count() -> int:
    raw = os.getenv("BITFINEX_ETH_PRICE_SCALE_DRAGS", "3").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 3
    return min(6, max(0, value))


def _get_bitfinex_price_scale_drag_pixels() -> int:
    raw = os.getenv("BITFINEX_ETH_PRICE_SCALE_DRAG_PIXELS", "350").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 350
    return min(600, max(80, value))


def _get_bitfinex_price_scale_drag_steps() -> int:
    raw = os.getenv("BITFINEX_ETH_PRICE_SCALE_DRAG_STEPS", "2").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 2
    return min(12, max(1, value))


async def _adjust_chart_range_to_focus_prices(
    page,
    focus_prices: Sequence[float],
    *,
    max_attempts: int = 14,
) -> None:
    normalized_focus_prices = _normalize_focus_prices(focus_prices)

    for _attempt in range(max(1, max_attempts)):
        price_scale_bounds = await _read_main_price_scale_bounds(page)
        if _price_bounds_include_focus(price_scale_bounds, normalized_focus_prices):
            return

        bounds = await _read_visible_price_bounds(page, normalized_focus_prices)
        if _price_bounds_include_focus(bounds, normalized_focus_prices):
            return

        if not await _zoom_out_main_price_scale(page):
            return


async def _read_visible_price_bounds(page, focus_prices: Sequence[float]) -> tuple[float, float] | None:
    try:
        text = await page.locator("body").inner_text(timeout=2500)
    except Exception:
        return None
    return _extract_visible_price_bounds(text, focus_prices)


async def _read_main_price_scale_bounds(page) -> tuple[float, float] | None:
    try:
        text = await page.evaluate(
            """
            () => {
              const candidates = Array.from(document.querySelectorAll(".titan-charts-scale-section"));
              const item = candidates.find((el) => {
                const rect = el.getBoundingClientRect();
                return rect.width > 30 && rect.height > 250 && rect.y < window.innerHeight * 0.75;
              });
              return item ? (item.innerText || item.textContent || "") : "";
            }
            """
        )
    except Exception:
        return None
    if not isinstance(text, str):
        return None
    return _extract_visible_price_bounds(text, ())


async def _zoom_out_main_price_scale(page) -> bool:
    box = await _get_main_price_scale_box(page)
    viewport = page.viewport_size or {"width": 2048, "height": 900}
    width = int(viewport.get("width") or 2048)
    height = int(viewport.get("height") or 900)
    if box is None:
        scale_x = max(1200, width - 73)
        start_y = 450
    else:
        scale_x = int(box["x"] + (box["width"] * 0.5))
        start_y = int(box["y"] + (box["height"] * 0.65))
    end_y = min(height - 95, start_y + _get_kiyotaka_price_scale_zoom_drag_pixels())

    try:
        await page.mouse.move(scale_x, start_y)
        await page.mouse.down()
        await page.mouse.move(scale_x, end_y, steps=8)
        await page.mouse.up()
        await page.wait_for_timeout(650)
    except Exception:
        return False
    return True


def _get_kiyotaka_price_scale_zoom_drag_pixels() -> int:
    raw = os.getenv("KIYOTAKA_PRICE_SCALE_ZOOM_DRAG_PIXELS", "120").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 120
    return min(360, max(60, value))


def _normalize_focus_prices(focus_prices: Sequence[float]) -> tuple[float, ...]:
    normalized: list[float] = []
    for price in focus_prices:
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if not any(abs(value - existing) <= 0.01 for existing in normalized):
            normalized.append(value)
    return tuple(normalized)


def _get_visual_focus_prices(spec: "KiyotakaShortcutSpec", focus_prices: Sequence[float]) -> tuple[float, ...]:
    normalized_focus_prices = _normalize_focus_prices(focus_prices)
    if not normalized_focus_prices:
        return ()

    return normalized_focus_prices


def _price_bounds_include_focus(bounds: tuple[float, float] | None, focus_prices: Sequence[float]) -> bool:
    normalized_focus_prices = _normalize_focus_prices(focus_prices)
    if not normalized_focus_prices:
        return True
    if bounds is None:
        return False

    target_min = min(normalized_focus_prices)
    target_max = max(normalized_focus_prices)
    target_span = max(target_max - target_min, target_max * 0.01, 1.0)
    padding = max(target_span * 0.02, 1.0)
    return bounds[0] <= target_min - padding and bounds[1] >= target_max + padding


def _extract_visible_price_bounds(text: str, focus_prices: Sequence[float]) -> tuple[float, float] | None:
    values: list[float] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])\$?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{3,6}(?:\.\d+)?)(?![A-Za-z0-9%])", text or ""):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if 0 < value < 1_000_000:
            values.append(value)
    values.extend(_extract_split_digit_prices(text or ""))

    normalized_focus_prices = _normalize_focus_prices(focus_prices)
    if normalized_focus_prices:
        target_min = min(normalized_focus_prices)
        target_max = max(normalized_focus_prices)
        values = [value for value in values if target_min * 0.75 <= value <= target_max * 1.25]

    unique_values = sorted({round(value, 2) for value in values})
    if len(unique_values) < 2:
        return None
    return unique_values[0], unique_values[-1]


def _extract_split_digit_prices(text: str) -> list[float]:
    values: list[float] = []
    token_parts: list[str] = []

    def flush() -> None:
        if len(token_parts) < 3:
            token_parts.clear()
            return
        token = "".join(token_parts)
        token_parts.clear()
        if not re.fullmatch(r"\d{3,6}(?:\.\d+)?", token):
            return
        try:
            values.append(float(token))
        except ValueError:
            return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"\d|\.", line):
            if re.fullmatch(r"\d", line) and re.fullmatch(r"\d{3,6}\.\d{2}", "".join(token_parts)):
                flush()
            token_parts.append(line)
            continue
        flush()
    flush()
    return values


def _should_require_visible_heatmap(spec: "KiyotakaShortcutSpec") -> bool:
    exchange = (spec.result_exchange or "").upper()
    return "HEATMAP" in (spec.view or "").upper() and "BITFINEX" in exchange


def _png_has_heatmap_layer(png_bytes: bytes) -> bool:
    decoded = _decode_png_rgb_rows(png_bytes)
    if decoded is None:
        return False

    width, height, rows = decoded
    left = min(60, width)
    right = max(left, width - 110)
    top = min(90, height)
    bottom = max(top, height - 70)
    long_yellow_rows = 0
    yellow_pixels = 0
    purple_pixels = 0
    for y in range(top, bottom):
        row = rows[y]
        run = 0
        for x in range(left, right):
            offset = x * 3
            red, green, blue = row[offset], row[offset + 1], row[offset + 2]
            if red >= 150 and green >= 150 and blue <= 95:
                yellow_pixels += 1
                run += 1
                if run >= 180:
                    long_yellow_rows += 1
                    break
            else:
                run = 0
            if red >= 55 and blue >= 90 and red >= green * 1.25 and blue >= green * 1.25:
                purple_pixels += 1
        if long_yellow_rows >= 2:
            return True
    return yellow_pixels >= 350 and purple_pixels >= 250


def _decode_png_rgb_rows(png_bytes: bytes) -> tuple[int, int, list[bytes]] | None:
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    offset = 8
    width = height = bit_depth = color_type = interlace = None
    idat_parts: list[bytes] = []
    while offset + 8 <= len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        chunk_data = png_bytes[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not width or not height or bit_depth != 8 or interlace != 0 or color_type not in {2, 6}:
        return None

    bytes_per_pixel = 3 if color_type == 2 else 4
    stride = width * bytes_per_pixel
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error:
        return None

    rows: list[bytes] = []
    previous = bytearray(stride)
    raw_offset = 0
    for _y in range(height):
        if raw_offset + 1 + stride > len(raw):
            return None
        filter_type = raw[raw_offset]
        scanline = bytearray(raw[raw_offset + 1 : raw_offset + 1 + stride])
        raw_offset += 1 + stride
        _unfilter_png_scanline(scanline, previous, filter_type, bytes_per_pixel)
        if color_type == 6:
            rgb = bytearray(width * 3)
            for x in range(width):
                source = x * 4
                target = x * 3
                rgb[target : target + 3] = scanline[source : source + 3]
            rows.append(bytes(rgb))
        else:
            rows.append(bytes(scanline))
        previous = scanline
    return width, height, rows


def _unfilter_png_scanline(scanline: bytearray, previous: bytearray, filter_type: int, bytes_per_pixel: int) -> None:
    for index in range(len(scanline)):
        left = scanline[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index]
        up_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        if filter_type == 1:
            scanline[index] = (scanline[index] + left) & 0xFF
        elif filter_type == 2:
            scanline[index] = (scanline[index] + up) & 0xFF
        elif filter_type == 3:
            scanline[index] = (scanline[index] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            scanline[index] = (scanline[index] + _png_paeth(left, up, up_left)) & 0xFF


def _png_paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    up_left_distance = abs(estimate - up_left)
    if left_distance <= up_distance and left_distance <= up_left_distance:
        return left
    if up_distance <= up_left_distance:
        return up
    return up_left


async def _draw_focus_price_overlays(page, focus_prices: Sequence[float]) -> None:
    normalized_focus_prices = _normalize_focus_prices(focus_prices)
    if len(normalized_focus_prices) <= 1:
        return

    overlay_prices = normalized_focus_prices[1:]
    bounds = _get_overlay_price_bounds(await _read_visible_price_bounds(page, normalized_focus_prices), normalized_focus_prices)
    if bounds is None:
        return

    await page.evaluate(
        """
        ({ prices, bounds }) => {
          const existing = document.getElementById("codex-focus-price-overlay");
          if (existing) existing.remove();
          const [low, high] = bounds;
          if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return;

          const top = 90;
          let bottom = Math.min(window.innerHeight - 255, 650);
          if (!Number.isFinite(bottom) || bottom <= top + 120) bottom = window.innerHeight * 0.72;
          const left = 54;
          let right = Math.min(Math.round(window.innerWidth * 0.48), window.innerWidth - 580);
          if (!Number.isFinite(right) || right <= left + 180) right = Math.round(window.innerWidth * 0.50);
          const labelLeft = Math.min(right + 86, window.innerWidth - 420);
          const overlay = document.createElement("div");
          overlay.id = "codex-focus-price-overlay";
          overlay.style.position = "fixed";
          overlay.style.inset = "0";
          overlay.style.pointerEvents = "none";
          overlay.style.zIndex = "2147483647";
          document.body.appendChild(overlay);

          const seen = new Set();
          const labeledY = [];
          const formatPrice = (price) => {
            if (Math.abs(price - Math.round(price)) < 0.01) return String(Math.round(price));
            return price.toLocaleString("en-US", { maximumFractionDigits: 1 });
          };
          for (const rawPrice of prices) {
            const price = Number(rawPrice);
            if (!Number.isFinite(price) || price < low || price > high) continue;
            const key = price.toFixed(2);
            if (seen.has(key)) continue;
            seen.add(key);

            const y = top + ((high - price) / (high - low)) * (bottom - top);
            const line = document.createElement("div");
            line.style.position = "fixed";
            line.style.left = `${left}px`;
            line.style.width = `${Math.max(right - left, 120)}px`;
            line.style.top = `${Math.round(y)}px`;
            line.style.height = "2px";
            line.style.background = "rgba(235, 240, 245, 0.92)";
            line.style.boxShadow = "0 0 4px rgba(255, 255, 255, 0.45)";
            overlay.appendChild(line);

            if (labeledY.some((usedY) => Math.abs(usedY - y) < 18)) continue;
            labeledY.push(y);
            const label = document.createElement("div");
            label.textContent = formatPrice(price);
            label.style.position = "fixed";
            label.style.left = `${Math.round(labelLeft)}px`;
            label.style.top = `${Math.round(y - 11)}px`;
            label.style.color = "#56a8ff";
            label.style.font = "700 18px Arial, sans-serif";
            label.style.letterSpacing = "0";
            label.style.textShadow = "0 0 6px rgba(0, 0, 0, 0.95)";
            overlay.appendChild(label);
          }
        }
        """,
        {"prices": list(overlay_prices), "bounds": list(bounds) if bounds is not None else None},
    )


def _get_overlay_price_bounds(
    visible_bounds: tuple[float, float] | None,
    focus_prices: Sequence[float],
) -> tuple[float, float] | None:
    normalized_focus_prices = _normalize_focus_prices(focus_prices)
    if len(normalized_focus_prices) <= 1:
        return visible_bounds

    target_min = min(normalized_focus_prices)
    target_max = max(normalized_focus_prices)
    target_span = max(target_max - target_min, target_max * 0.01, 1.0)
    if (
        visible_bounds is not None
        and visible_bounds[1] > visible_bounds[0]
        and visible_bounds[1] - visible_bounds[0] >= target_span * 0.5
    ):
        return visible_bounds

    padding = max(target_span * 0.05, target_max * 0.01, 1.0)
    return target_min - padding, target_max + padding


async def _close_search_overlay(page) -> None:
    for _ in range(2):
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(250)

    for x, y in ((1200, 240), (1400, 280), (1200, 360)):
        try:
            await page.mouse.click(x, y)
        except Exception:
            continue
        await page.wait_for_timeout(250)


async def _verify_selected_symbol(page, spec: "KiyotakaShortcutSpec") -> None:
    for _ in range(6):
        try:
            text = await page.locator("body").inner_text(timeout=2500)
            if _chart_text_matches_symbol(text, spec.result_symbol):
                return
        except Exception:
            pass
        await page.wait_for_timeout(1000)

    raise KiyotakaScreenshotError(f"선택된 차트가 {spec.result_symbol}이 아닙니다.")


def _search_result_matches(text: str, *, symbol: str, exchange: str) -> bool:
    return _symbol_matches_text(text, symbol) and _exchange_matches(text, exchange)


def _exchange_matches(text: str, exchange: str) -> bool:
    compact_text = _compact_token(text)
    compact_exchange = _compact_token(exchange)
    line_tokens = {_compact_token(line) for line in (text or "").splitlines()}
    if compact_exchange and compact_exchange in line_tokens:
        return True
    if compact_exchange.endswith("F") and compact_exchange in compact_text:
        return True
    if compact_exchange in {"OKXF", "OKEXF"}:
        return "OKX" in compact_text or "OKEX" in compact_text
    return False


def _symbol_matches_text(text: str, symbol: str) -> bool:
    compact_text = _compact_token(text)
    compact_symbol = _compact_token(symbol)
    if compact_symbol in compact_text:
        return True
    if compact_symbol.endswith("USDT"):
        bitfinex_tether_symbol = compact_symbol[:-2]
        if bitfinex_tether_symbol in compact_text:
            return True
    base, quote = _split_symbol(symbol)
    if base and quote == "USDT" and base in compact_text and "TETHER" in compact_text:
        return True
    if base and quote:
        return base in compact_text and quote in compact_text
    return False


def _chart_text_matches_symbol(text: str, symbol: str) -> bool:
    compact_text = _compact_token(text)
    compact_text_without_bitfinex_f0 = compact_text.replace("F0", "")
    compact_symbol = _compact_token(symbol)
    if compact_symbol in compact_text or compact_symbol in compact_text_without_bitfinex_f0:
        return True
    if compact_symbol.endswith("USDT"):
        bitfinex_tether_symbol = compact_symbol[:-2]
        if bitfinex_tether_symbol in compact_text or bitfinex_tether_symbol in compact_text_without_bitfinex_f0:
            return True

    base, quote = _split_symbol(symbol)
    if base and quote:
        return base in compact_text and quote in compact_text
    return False


def _chart_text_matches_exchange(text: str, exchange: str) -> bool:
    compact_text = _compact_token(text)
    compact_exchange = _compact_token(exchange)
    if not compact_exchange:
        return True
    if compact_exchange == "BITFINEX":
        return "BITFINEX" in compact_text and "BITFINEXF" not in compact_text and "BITFINEXD" not in compact_text
    return _exchange_matches(text, exchange)


def _split_symbol(symbol: str) -> tuple[str, str]:
    compact = _compact_token(symbol)
    for quote in ("USDT", "USD"):
        if compact.endswith(quote) and len(compact) > len(quote):
            return compact[: -len(quote)], quote
    return compact, ""


def _compact_token(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (text or "").upper())
