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


class SafeAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_answer_returns_true_on_success(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer=AsyncMock(return_value=None),
        )

        result = await bot._safe_answer(message, "hello")

        self.assertTrue(result)
        message.answer.assert_awaited_once_with("hello")

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


if __name__ == "__main__":
    unittest.main()
