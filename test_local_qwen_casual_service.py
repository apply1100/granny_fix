import unittest
from unittest.mock import Mock, patch

from services import local_qwen_casual_service


class LocalQwenContextRetryTests(unittest.TestCase):
    def test_retries_with_compact_prompt_after_context_overflow(self) -> None:
        llm = Mock()
        llm.create_chat_completion.side_effect = [
            ValueError("Requested tokens (568) exceeded context window of 512"),
            {"choices": [{"message": {"content": "compact reply"}}]},
        ]

        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "second answer"},
            {"role": "user", "content": "third question"},
            {"role": "assistant", "content": "third answer"},
        ]

        with patch.object(local_qwen_casual_service, "_get_local_qwen", return_value=llm):
            reply = local_qwen_casual_service._generate_local_qwen_reply(
                user_message="recommend a dinner menu",
                history=history,
                system_prompt="Reply like a warm Korean grandmother.",
                mode_instructions="Keep the answer brief and natural.",
            )

        self.assertEqual(reply, "compact reply")
        self.assertEqual(llm.create_chat_completion.call_count, 2)

        first_call = llm.create_chat_completion.call_args_list[0].kwargs
        second_call = llm.create_chat_completion.call_args_list[1].kwargs

        self.assertEqual(
            first_call["max_tokens"],
            local_qwen_casual_service.DEFAULT_LOCAL_QWEN_MAX_TOKENS,
        )
        self.assertEqual(
            second_call["max_tokens"],
            local_qwen_casual_service.COMPACT_LOCAL_QWEN_MAX_TOKENS,
        )
        self.assertLess(len(second_call["messages"]), len(first_call["messages"]))

    def test_context_window_error_message_is_not_raw_llama_error(self) -> None:
        message = local_qwen_casual_service._summarize_local_qwen_error(
            ValueError("Requested tokens (568) exceeded context window of 512")
        )

        self.assertIsInstance(message, str)
        self.assertTrue(message)
        self.assertNotIn("Requested tokens", message)

    def test_meta_style_reply_is_rejected(self) -> None:
        llm = Mock()
        llm.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "The assistant keeps interactions warm for the user."
                    }
                }
            ]
        }

        with patch.object(local_qwen_casual_service, "_get_local_qwen", return_value=llm):
            with self.assertRaises(local_qwen_casual_service.LocalQwenMetaLeakError):
                local_qwen_casual_service._generate_local_qwen_reply(
                    user_message="grandma are you okay",
                    history=[],
                    system_prompt="Reply like a warm Korean grandmother.",
                    mode_instructions="Keep the answer brief and natural.",
                )

    def test_meta_leak_error_does_not_trigger_backoff(self) -> None:
        should_back_off = local_qwen_casual_service._should_back_off_local_qwen_error(
            local_qwen_casual_service.LocalQwenMetaLeakError("meta leak")
        )

        self.assertFalse(should_back_off)


if __name__ == "__main__":
    unittest.main()
