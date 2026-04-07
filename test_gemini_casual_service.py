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
            patch.object(gemini_casual_service, "_get_gemini_api_key", return_value="test-key"),
            patch.object(
                gemini_casual_service,
                "_get_gemini_models",
                return_value=["missing-model", "working-model"],
            ),
            patch.object(gemini_casual_service, "DEBUG_RESP_PATH", fake_debug_path),
            patch.object(gemini_casual_service, "_request_gemini_response", new=request_mock),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("할매")

        self.assertEqual(reply, "할매가 왔다.")
        self.assertEqual(request_mock.await_count, 2)

    async def test_user_reply_hides_raw_http_errors(self) -> None:
        fake_debug_path = Mock()
        fake_debug_path.parent.mkdir = Mock()
        fake_debug_path.write_text = Mock()
        request_mock = AsyncMock(side_effect=RuntimeError("Gemini HTTP 500: boom"))

        with (
            patch.object(gemini_casual_service, "_get_gemini_api_key", return_value="test-key"),
            patch.object(gemini_casual_service, "_get_gemini_models", return_value=["only-model"]),
            patch.object(gemini_casual_service, "DEBUG_RESP_PATH", fake_debug_path),
            patch.object(gemini_casual_service, "_request_gemini_response", new=request_mock),
            patch.object(gemini_casual_service, "build_grandma_unavailable_reply", return_value="fallback reply"),
        ):
            reply = await gemini_casual_service.get_grandma_casual_reply("할매")

        self.assertEqual(reply, "fallback reply")
        self.assertNotIn("Gemini HTTP", reply)


if __name__ == "__main__":
    unittest.main()
