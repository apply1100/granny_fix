import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import bot


class DummyBadRequest(TelegramBadRequest):
    def __init__(self, message: str) -> None:
        self.message = message
        self.method = None


class DummyForbidden(TelegramForbiddenError):
    def __init__(self, message: str) -> None:
        self.message = message
        self.method = None


class RuntimeGuardTests(unittest.TestCase):
    def test_railway_runtime_skips_polling_by_default(self) -> None:
        with patch.dict("os.environ", {"RAILWAY_PROJECT_ID": "project"}, clear=True):
            self.assertTrue(bot._should_skip_polling_for_runtime())

    def test_railway_runtime_can_be_overridden(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAILWAY_PROJECT_ID": "project",
                "ALLOW_RAILWAY_POLLING_BOT": "1",
            },
            clear=True,
        ):
            self.assertFalse(bot._should_skip_polling_for_runtime())


class SafeAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_answer_returns_true_on_success(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer=AsyncMock(return_value=None),
        )

        result = await bot._safe_answer(message, "hello")

        self.assertTrue(result)
        message.answer.assert_awaited_once_with("hello")

    async def test_safe_answer_replies_to_questioner_in_group(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123, type="supergroup"),
            message_id=77,
            from_user=SimpleNamespace(username="pirarucu", full_name="Pirarucu", is_bot=False),
            answer=AsyncMock(return_value=None),
        )

        result = await bot._safe_answer(message, "hello")

        self.assertTrue(result)
        message.answer.assert_awaited_once()
        self.assertEqual(message.answer.await_args.args[0], "hello")
        self.assertEqual(message.answer.await_args.kwargs["reply_parameters"].message_id, 77)

    async def test_safe_answer_uses_plain_text_when_questioner_has_no_username(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123, type="group"),
            message_id=88,
            from_user=SimpleNamespace(username=None, full_name="질문한 사람", is_bot=False),
            answer=AsyncMock(return_value=None),
        )

        result = await bot._safe_answer(message, "hello")

        self.assertTrue(result)
        self.assertEqual(message.answer.await_args.args[0], "hello")
        self.assertEqual(message.answer.await_args.kwargs["reply_parameters"].message_id, 88)

    async def test_safe_answer_cleans_up_forbidden_chat(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer=AsyncMock(side_effect=DummyForbidden("forbidden")),
        )

        with patch.object(bot, "_cleanup_failed_runtime_subscription", AsyncMock()) as cleanup:
            result = await bot._safe_answer(message, "hello")

        self.assertFalse(result)
        cleanup.assert_awaited_once_with(123)

    async def test_safe_answer_cleans_up_terminal_bad_request(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer=AsyncMock(side_effect=DummyBadRequest("not enough rights to send text messages to the chat")),
        )

        with patch.object(bot, "_cleanup_failed_runtime_subscription", AsyncMock()) as cleanup:
            result = await bot._safe_answer(message, "hello")

        self.assertFalse(result)
        cleanup.assert_awaited_once_with(123)

    async def test_safe_answer_photo_returns_true_on_success(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer_photo=AsyncMock(return_value=None),
        )

        result = await bot._safe_answer_photo(message, b"png-bytes", caption="hello", filename="test.png")

        self.assertTrue(result)
        message.answer_photo.assert_awaited_once()

    async def test_safe_answer_photo_cleans_up_forbidden_chat(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer_photo=AsyncMock(side_effect=DummyForbidden("forbidden")),
        )

        with patch.object(bot, "_cleanup_failed_runtime_subscription", AsyncMock()) as cleanup:
            result = await bot._safe_answer_photo(message, b"png-bytes", caption="hello")

        self.assertFalse(result)
        cleanup.assert_awaited_once_with(123)

    async def test_safe_answer_photo_cleans_up_terminal_bad_request(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer_photo=AsyncMock(side_effect=DummyBadRequest("not enough rights to send photos to the chat")),
        )

        with patch.object(bot, "_cleanup_failed_runtime_subscription", AsyncMock()) as cleanup:
            result = await bot._safe_answer_photo(message, b"png-bytes", caption="hello")

        self.assertFalse(result)
        cleanup.assert_awaited_once_with(123)

    async def test_market_chat_checks_kiyotaka_shortcut_before_ignoring_slash_text(self) -> None:
        message = SimpleNamespace(
            text="/okxbtcusdp",
            chat=SimpleNamespace(id=123, type="group"),
        )

        with patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=True)) as shortcut:
            await bot.market_chat(message)

        shortcut.assert_awaited_once()
        self.assertEqual(shortcut.await_args.args, (message, "/okxbtcusdp"))
        self.assertIn("constraints", shortcut.await_args.kwargs)

    async def test_market_chat_checks_wide_kiyotaka_shortcut_before_ignoring_slash_text(self) -> None:
        message = SimpleNamespace(
            text="/okxbtcusdpwide",
            chat=SimpleNamespace(id=123, type="group"),
        )

        with patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=True)) as shortcut:
            await bot.market_chat(message)

        shortcut.assert_awaited_once()
        self.assertEqual(shortcut.await_args.args, (message, "/okxbtcusdpwide"))
        self.assertIn("constraints", shortcut.await_args.kwargs)

    async def test_kiyotaka_shortcut_uses_api_report_before_background_capture(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
        )
        status_message = SimpleNamespace(delete=AsyncMock())

        with (
            patch.object(bot, "_safe_progress_answer", AsyncMock(return_value=status_message)) as progress_answer,
            patch.object(bot, "_safe_edit_message_text", AsyncMock()),
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "_start_kiyotaka_capture_task") as start_capture,
            patch.object(bot, "has_kiyotaka_api_key", return_value=True),
            patch.object(bot, "get_okx_btc_levels_report_with_focus_prices", return_value=("api-report", (76000.0, 53000.0, 52900.0))),
            patch.object(bot, "capture_kiyotaka_screenshot", AsyncMock(side_effect=AssertionError("browser should not run"))),
        ):
            handled = await bot._maybe_answer_kiyotaka_snapshot(message, "/okxbtcusdtpwide")

        self.assertTrue(handled)
        self.assertIn("api-report", safe_answer.await_args.args[1])
        self.assertIn("예상 약 2분, 최대 약 3분", safe_answer.await_args.args[1])
        start_capture.assert_called_once_with(
            message,
            bot.get_kiyotaka_shortcut_spec("/okxbtcusdtpwide"),
            "api-report",
            (76000.0, 53000.0, 52900.0),
            status_message,
        )

    async def test_kiyotaka_shortcut_honors_text_only_constraint(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
        )
        status_message = SimpleNamespace(delete=AsyncMock())
        text = "/okxbtcusdtp 텍스트로만"

        with (
            patch.object(bot, "_safe_progress_answer", AsyncMock(return_value=status_message)) as progress_answer,
            patch.object(bot, "_safe_edit_message_text", AsyncMock()) as edit_text,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "_safe_delete_message", AsyncMock()) as delete_message,
            patch.object(bot, "_start_kiyotaka_capture_task") as start_capture,
            patch.object(bot, "has_kiyotaka_api_key", return_value=True),
            patch.object(bot, "get_okx_btc_levels_report_with_focus_prices", return_value=("api-report", (76000.0, 53000.0))),
            patch.object(bot, "capture_kiyotaka_screenshot", AsyncMock(side_effect=AssertionError("capture should not run"))),
        ):
            handled = await bot._maybe_answer_kiyotaka_snapshot(
                message,
                text,
                constraints=bot.extract_message_constraints(text),
            )

        self.assertTrue(handled)
        self.assertIn("텍스트 응답 모드", progress_answer.await_args.args[1])
        self.assertIn("요청대로 캡처는 쓰지 않았다", edit_text.await_args.args[1])
        self.assertEqual(safe_answer.await_args.args, (message, "api-report"))
        start_capture.assert_not_called()
        delete_message.assert_awaited_once_with(status_message)
        status_message.delete.assert_not_awaited()

    async def test_bitfinex_eth_shortcut_uses_api_report(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
        )
        status_message = SimpleNamespace(delete=AsyncMock())

        with (
            patch.object(bot, "_safe_progress_answer", AsyncMock(return_value=status_message)) as progress_answer,
            patch.object(bot, "_safe_edit_message_text", AsyncMock()),
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "_safe_answer_photo", AsyncMock(return_value=True)) as safe_answer_photo,
            patch.object(bot, "_start_kiyotaka_capture_task") as start_capture,
            patch.object(bot, "has_kiyotaka_api_key", return_value=True),
            patch.object(bot, "get_bitfinex_eth_levels_report_with_focus_prices", return_value=("bitfinex-eth-report", (2500.0, 2300.0, 2200.0))),
            patch.object(bot, "capture_kiyotaka_screenshot", AsyncMock(return_value=b"png-bytes")) as capture,
        ):
            handled = await bot._maybe_answer_kiyotaka_snapshot(message, "비파 이더")

        self.assertTrue(handled)
        progress_text = progress_answer.await_args.args[1]
        self.assertIn("작동 중", progress_text)
        self.assertIn("BITFINEX ETH", progress_text)
        self.assertIn("흐릿한 물량 제외", progress_text)
        capture.assert_not_awaited()
        start_capture.assert_called_once_with(
            message,
            bot.get_kiyotaka_shortcut_spec("비파 이더"),
            "bitfinex-eth-report",
            (2500.0, 2300.0, 2200.0),
            status_message,
        )
        safe_answer_photo.assert_not_awaited()
        self.assertIn("bitfinex-eth-report", safe_answer.await_args.args[1])
        self.assertIn("캡처는 뒤에서", safe_answer.await_args.args[1])
        status_message.delete.assert_not_awaited()

    async def test_bitfinex_eth_shortcut_sends_text_if_capture_fails(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
        )
        status_message = SimpleNamespace(delete=AsyncMock())

        with (
            patch.object(bot, "_safe_progress_answer", AsyncMock(return_value=status_message)),
            patch.object(bot, "_safe_edit_message_text", AsyncMock()),
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "_safe_answer_photo", AsyncMock(return_value=True)) as safe_answer_photo,
            patch.object(bot, "_start_kiyotaka_capture_task") as start_capture,
            patch.object(bot, "has_kiyotaka_api_key", return_value=True),
            patch.object(bot, "get_bitfinex_eth_levels_report_with_focus_prices", return_value=("bitfinex-eth-report", (2500.0, 2300.0, 2200.0))),
            patch.object(bot, "capture_kiyotaka_screenshot", AsyncMock(side_effect=bot.KiyotakaScreenshotError("no chart"))),
        ):
            handled = await bot._maybe_answer_kiyotaka_snapshot(message, "비파 이더")

        self.assertTrue(handled)
        safe_answer_photo.assert_not_awaited()
        start_capture.assert_called_once()
        self.assertIn("bitfinex-eth-report", safe_answer.await_args.args[1])
        self.assertIn("캡처는 뒤에서", safe_answer.await_args.args[1])

    def test_okx_split_capture_eta_defaults_to_under_three_minutes(self) -> None:
        spec = bot.get_kiyotaka_shortcut_spec("/okxbtcusdtp")

        assert spec is not None
        jobs = bot._get_kiyotaka_capture_jobs(spec, (76000.0, 53000.0, 52900.0))
        with patch.dict(bot.os.environ, {}, clear=True):
            self.assertEqual(bot._get_kiyotaka_capture_timeout_for_spec_ms(spec), 90000)
            self.assertEqual(bot._get_kiyotaka_capture_eta_text(spec, jobs), "예상 약 2분, 최대 약 3분")

    async def test_okx_split_capture_sends_two_photos_with_eta_updates(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
        )
        status_message = SimpleNamespace()
        spec = bot.get_kiyotaka_shortcut_spec("/okxbtcusdtp")

        assert spec is not None
        with (
            patch.dict(bot.os.environ, {}, clear=True),
            patch.object(bot, "capture_kiyotaka_screenshot", AsyncMock(side_effect=[b"near", b"remote"])) as capture,
            patch.object(bot, "_safe_answer_photo", AsyncMock(return_value=True)) as answer_photo,
            patch.object(bot, "_safe_edit_message_text", AsyncMock()) as edit_text,
            patch.object(bot, "_safe_delete_message", AsyncMock()) as delete_message,
        ):
            await bot._send_kiyotaka_capture_when_ready(
                message,
                spec,
                report="api-report",
                focus_prices=(76000.0, 53000.0, 52900.0),
                status_message=status_message,
            )

        self.assertEqual(capture.await_count, 2)
        self.assertEqual(capture.await_args_list[0].kwargs["timeout_ms"], 90000)
        self.assertEqual(capture.await_args_list[0].kwargs["focus_prices"], ())
        self.assertEqual(capture.await_args_list[1].kwargs["timeout_ms"], 90000)
        self.assertEqual(capture.await_args_list[1].kwargs["focus_prices"], (53000.0, 52900.0))
        self.assertEqual(answer_photo.await_count, 2)
        self.assertIn("capture 1/2", answer_photo.await_args_list[0].kwargs["caption"])
        self.assertIn("capture 2/2", answer_photo.await_args_list[1].kwargs["caption"])
        self.assertIn("Focus: 53,000, 52,900", answer_photo.await_args_list[1].kwargs["caption"])
        self.assertIn("남은 예상 약 2분, 최대 약 3분", edit_text.await_args_list[0].args[1])
        delete_message.assert_awaited_once_with(status_message)

    async def test_okxbit_command_uses_kiyotaka_split_capture_flow(self) -> None:
        message = SimpleNamespace(text="/okxbit", chat=SimpleNamespace(id=123))

        with patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=True)) as snapshot:
            await bot.okxbit(message)

        snapshot.assert_awaited_once_with(message, "/okxbtcusdtp")

    async def test_kiyotaka_progress_reply_reports_background_capture_status(self) -> None:
        message = SimpleNamespace(
            text="언제되는거지",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=SimpleNamespace(
                text="BITFINEX ETHUSDT 진한 오더벽\nAPI 조회 완료. Kiyotaka 캡처도 같이 준비 중이다.",
                caption=None,
                from_user=SimpleNamespace(is_bot=True),
            ),
            entities=None,
        )

        bot._ACTIVE_KIYOTAKA_CAPTURES[123] = "BITFINEX ETH"
        try:
            with (
                patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
                patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            ):
                await bot.market_chat(message)
        finally:
            bot._ACTIVE_KIYOTAKA_CAPTURES.pop(123, None)

        safe_answer.assert_awaited_once()
        self.assertIn("캡처는 아직 찍는 중", safe_answer.await_args.args[1])

    async def test_kiyotaka_shortcut_without_api_does_not_fallback_to_browser_by_default(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
        )
        status_message = SimpleNamespace(delete=AsyncMock())

        with (
            patch.object(bot, "_safe_progress_answer", AsyncMock(return_value=status_message)),
            patch.object(bot, "_safe_edit_message_text", AsyncMock()),
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "has_kiyotaka_api_key", return_value=False),
            patch.object(bot, "_kiyotaka_browser_fallback_enabled", return_value=False),
            patch.object(bot, "capture_kiyotaka_screenshot", AsyncMock(side_effect=AssertionError("browser should not run"))),
        ):
            handled = await bot._maybe_answer_kiyotaka_snapshot(message, "/okxbtcusdtp")

        self.assertTrue(handled)
        self.assertIn("API 조회 실패", safe_answer.await_args.args[1])
        status_message.delete.assert_not_awaited()

    async def test_market_chat_routes_okx_eth_request_to_heatmap_report(self) -> None:
        message = SimpleNamespace(
            text="okx 이더 밴드 확인",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_okx_eth_levels_report", return_value="eth-report"),
        ):
            await bot.market_chat(message)

        acknowledge.assert_awaited_once_with(message, is_market=True)
        self.assertEqual(safe_answer.await_count, 2)
        self.assertEqual(safe_answer.await_args_list[0].args, (message, "OKX ETH 딥 히트맵 밴드를 뒤지고 있다..."))
        self.assertEqual(safe_answer.await_args_list[1].args, (message, "eth-report"))

    async def test_market_chat_ignores_unaddressed_group_market_chatter(self) -> None:
        message = SimpleNamespace(
            text="비트 자리 어떨까",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
        ):
            await bot.market_chat(message)

        acknowledge.assert_not_awaited()
        safe_answer.assert_not_awaited()

    async def test_market_chat_honors_bitmex_exclusion(self) -> None:
        message = SimpleNamespace(
            text="할머니 비트코인 어때 보여 대신 비트맥스 그거 쓰지말고 대답해줘",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_maybe_auto_register_market_chat", AsyncMock()) as auto_register,
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_bitmex_whale_grandma_reply", side_effect=AssertionError("BitMEX should not run")),
        ):
            await bot.market_chat(message)

        auto_register.assert_awaited_once_with(message)
        acknowledge.assert_awaited_once_with(message, is_market=True)
        safe_answer.assert_awaited_once()
        reply = safe_answer.await_args.args[1]
        self.assertIn("비트맥스 기준은 빼고", reply)
        self.assertIn("OKX", reply)
        self.assertNotIn("비트맥스 흐름 보고", reply)

    async def test_grandma_call_with_laugh_tail_uses_one_quick_reply(self) -> None:
        message = SimpleNamespace(
            text="할머니가ㅎ",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_grandma_casual_reply", AsyncMock(side_effect=AssertionError("LLM should not run"))),
        ):
            await bot.market_chat(message)

        acknowledge.assert_awaited_once_with(message, is_market=False)
        safe_answer.assert_awaited_once()
        self.assertIn(
            safe_answer.await_args.args[1],
            {
                "왜 그러느냐, 할매 여기 있다.",
                "응, 불렀느냐. 할매 왔다.",
                "허허, 여기 있지. 무슨 일 있느냐.",
            },
        )

    async def test_grandma_unsettling_call_uses_one_quick_reply(self) -> None:
        message = SimpleNamespace(
            text="할머니 부활",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_grandma_casual_reply", AsyncMock(side_effect=AssertionError("LLM should not run"))),
        ):
            await bot.market_chat(message)

        acknowledge.assert_awaited_once_with(message, is_market=False)
        safe_answer.assert_awaited_once()
        self.assertIn(
            safe_answer.await_args.args[1],
            {
                "에구, 그런 말은 사람 놀라니까 하지 마라. 저녁 뭐 먹을지나 심심한 얘기처럼 편한 걸로 다시 말해보거라.",
                "아이고, 무덤이니 부활이니 그런 소린 듣기만 해도 등골이 서늘하다. 할매한텐 무서운 장난 말고 딴 얘기 해라.",
                "허허, 그런 으스스한 말은 할매가 못 받겠다. 밥이나 날씨 같은 편한 얘기로 다시 불러보거라.",
            },
        )

    async def test_breakfast_recommendation_uses_one_quick_reply(self) -> None:
        message = SimpleNamespace(
            text="할매 내일 아침 추천 좀",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_grandma_casual_reply", AsyncMock(side_effect=AssertionError("LLM should not run"))),
        ):
            await bot.market_chat(message)

        acknowledge.assert_awaited_once_with(message, is_market=False)
        safe_answer.assert_awaited_once()
        self.assertIn("아침", safe_answer.await_args.args[1])

    async def test_death_euphemism_to_grandma_uses_safety_reply(self) -> None:
        message = SimpleNamespace(
            text="할매 강 강 건너 가소",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_grandma_casual_reply", AsyncMock(side_effect=AssertionError("LLM should not run"))),
        ):
            await bot.market_chat(message)

        acknowledge.assert_awaited_once_with(message, is_market=False)
        safe_answer.assert_awaited_once()

    async def test_casual_reply_guard_blocks_excluded_tool_leak(self) -> None:
        message = SimpleNamespace(
            text="할매 비트맥스 말고 그냥 농담해줘",
            chat=SimpleNamespace(id=123, type="group"),
            reply_to_message=None,
            entities=None,
        )

        with (
            patch.object(bot, "_maybe_answer_kiyotaka_snapshot", AsyncMock(return_value=False)),
            patch.object(bot, "_acknowledge_message", AsyncMock()) as acknowledge,
            patch.object(bot, "_safe_answer", AsyncMock(return_value=True)) as safe_answer,
            patch.object(bot, "get_grandma_casual_reply", AsyncMock(return_value="BitMEX 기준으로 보면 어쩌고")),
        ):
            await bot.market_chat(message)

        acknowledge.assert_awaited_once_with(message, is_market=False)
        safe_answer.assert_awaited_once()
        self.assertIn("조건을 어긴 답변", safe_answer.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
