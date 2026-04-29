import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services import gemini_casual_service


class GeminiModelSelectionTests(unittest.TestCase):
    def test_default_model_order_prefers_safe_default_then_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                gemini_casual_service._get_gemini_models(),
                ["gemini-1.5-flash", "gemini-2.0-flash"],
            )

    def test_configured_model_keeps_default_as_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GEMINI_CASUAL_MODEL": "gemini-2.0-flash",
                "GEMINI_CASUAL_MODEL_FALLBACKS": "gemini-2.0-flash, gemini-1.5-flash",
            },
            clear=True,
        ):
            self.assertEqual(
                gemini_casual_service._get_gemini_models(),
                ["gemini-2.0-flash", "gemini-1.5-flash"],
            )


class GeminiReplyFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        gemini_casual_service._GEMINI_RETRY_AFTER_TS = 0.0

    async def test_short_call_uses_quick_reply_before_local_qwen(self) -> None:
        with (
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                side_effect=AssertionError("Local Qwen should not run"),
            ),
            patch.object(
                gemini_casual_service,
                "_get_gemini_api_key",
                side_effect=AssertionError("Gemini should not run"),
            ),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("할매")

        self.assertIn(
            reply,
            {
                "왜 그러느냐, 할매 여기 있다.",
                "응, 불렀느냐. 할매 왔다.",
                "허허, 여기 있지. 무슨 일 있느냐.",
            },
        )

    async def test_short_complaint_uses_quick_reply_before_local_qwen(self) -> None:
        with (
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                side_effect=AssertionError("Local Qwen should not run"),
            ),
            patch.object(
                gemini_casual_service,
                "_get_gemini_api_key",
                side_effect=AssertionError("Gemini should not run"),
            ),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("할매 정신차려")

        self.assertIn(
            reply,
            {
                "에구, 우리 손주 성났구나. 할매가 숨 한 번 고르고 다시 들을 테니 천천히 말해 보거라.",
                "허허, 그리 타박하면 할매도 마음이 철렁한다. 뭘 원하는지만 짧게 말해 주면 다시 맞춰 보마.",
                "아이고, 할매가 좀 헤맸구나. 화는 조금 내려놓고 하고 싶은 말을 한 줄로만 다시 줘 보거라.",
            },
        )

    async def test_disabled_gemini_returns_local_qwen_error_reply(self) -> None:
        with (
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                gemini_casual_service,
                "build_local_qwen_error_reply",
                return_value="Qwen error",
            ),
            patch.object(
                gemini_casual_service,
                "_get_gemini_api_key",
                side_effect=AssertionError("Gemini key lookup should not run while disabled"),
            ),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("longer prompt")

        self.assertEqual(reply, "Qwen error")

    async def test_local_qwen_reply_short_circuits_gemini(self) -> None:
        with (
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                new=AsyncMock(return_value="local qwen reply"),
            ),
            patch.object(gemini_casual_service, "_get_gemini_api_key", side_effect=AssertionError("Gemini should not run")),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("longer prompt")

        self.assertEqual(reply, "local qwen reply")

    async def test_retries_with_fallback_model_after_404(self) -> None:
        fake_debug_path = Mock()
        fake_debug_path.parent.mkdir = Mock()
        fake_debug_path.write_text = Mock()
        request_mock = AsyncMock(
            side_effect=[
                RuntimeError('Gemini HTTP 404: {"error":{"code":404}}'),
                {"candidates": [{"content": {"parts": [{"text": "할매가 왔다."}]}}]},
            ]
        )

        with (
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                new=AsyncMock(return_value=None),
            ),
            patch.object(gemini_casual_service, "gemini_casual_is_enabled", return_value=True),
            patch.object(gemini_casual_service, "_get_gemini_api_key", return_value="test-key"),
            patch.object(
                gemini_casual_service,
                "_get_gemini_models",
                return_value=["missing-model", "working-model"],
            ),
            patch.object(gemini_casual_service, "DEBUG_RESP_PATH", fake_debug_path),
            patch.object(gemini_casual_service, "_request_gemini_response", new=request_mock),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("오늘 좀 이상하다")

        self.assertEqual(reply, "할매가 왔다.")
        self.assertEqual(request_mock.await_count, 2)
        fake_debug_path.write_text.assert_not_called()

    async def test_debug_response_file_is_saved_only_when_enabled(self) -> None:
        fake_debug_path = Mock()
        fake_debug_path.parent.mkdir = Mock()
        fake_debug_path.write_text = Mock()
        request_mock = AsyncMock(return_value={"candidates": [{"content": {"parts": [{"text": "halmi reply"}]}}]})

        with (
            patch.dict(os.environ, {"GEMINI_DEBUG_SAVE_RESPONSE": "1"}, clear=False),
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                new=AsyncMock(return_value=None),
            ),
            patch.object(gemini_casual_service, "gemini_casual_is_enabled", return_value=True),
            patch.object(gemini_casual_service, "_get_gemini_api_key", return_value="test-key"),
            patch.object(gemini_casual_service, "_get_gemini_models", return_value=["working-model"]),
            patch.object(gemini_casual_service, "DEBUG_RESP_PATH", fake_debug_path),
            patch.object(gemini_casual_service, "_request_gemini_response", new=request_mock),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("longer prompt")

        self.assertEqual(reply, "halmi reply")
        fake_debug_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        fake_debug_path.write_text.assert_called_once()

    async def test_user_reply_hides_raw_http_errors(self) -> None:
        fake_debug_path = Mock()
        fake_debug_path.parent.mkdir = Mock()
        fake_debug_path.write_text = Mock()
        request_mock = AsyncMock(side_effect=RuntimeError("Gemini HTTP 500: boom"))

        with (
            patch.object(
                gemini_casual_service,
                "get_local_qwen_casual_reply",
                new=AsyncMock(return_value=None),
            ),
            patch.object(gemini_casual_service, "gemini_casual_is_enabled", return_value=True),
            patch.object(gemini_casual_service, "_get_gemini_api_key", return_value="test-key"),
            patch.object(gemini_casual_service, "_get_gemini_models", return_value=["only-model"]),
            patch.object(gemini_casual_service, "DEBUG_RESP_PATH", fake_debug_path),
            patch.object(gemini_casual_service, "_request_gemini_response", new=request_mock),
            patch.object(gemini_casual_service, "build_grandma_unavailable_reply", return_value="fallback reply"),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("오늘 좀 이상하다")

        self.assertEqual(reply, "fallback reply")
        self.assertNotIn("Gemini HTTP", reply)


if __name__ == "__main__":
    unittest.main()
