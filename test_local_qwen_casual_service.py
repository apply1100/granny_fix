import unittest
from unittest.mock import Mock, patch

from services import local_qwen_casual_service


class LocalQwenDefaultConfigTests(unittest.TestCase):
    def test_server_tuned_defaults_match_current_target(self) -> None:
        self.assertEqual(local_qwen_casual_service.DEFAULT_LOCAL_QWEN_BACKEND, "llama_cpp")
        self.assertEqual(
            local_qwen_casual_service.DEFAULT_LOCAL_QWEN_MODEL_REPO,
            "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        )
        self.assertEqual(
            local_qwen_casual_service.DEFAULT_LOCAL_QWEN_MODEL_FILE,
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        )
        self.assertEqual(
            local_qwen_casual_service.DEFAULT_LOCAL_QWEN_OLLAMA_MODEL,
            "gemma4:e4b",
        )
        self.assertEqual(local_qwen_casual_service.DEFAULT_LOCAL_QWEN_CTX, 2048)
        self.assertEqual(local_qwen_casual_service.DEFAULT_LOCAL_QWEN_N_BATCH, 128)

    def test_backend_can_switch_to_ollama(self) -> None:
        with patch.dict("os.environ", {"LOCAL_QWEN_BACKEND": "ollama"}, clear=False):
            self.assertEqual(local_qwen_casual_service._get_local_qwen_backend(), "ollama")

    def test_ollama_model_defaults_to_requested_tag(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(
                local_qwen_casual_service._get_local_qwen_ollama_model(),
                "gemma4:e4b",
            )


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

    def test_ollama_chat_completion_normalizes_response_shape(self) -> None:
        response = Mock()
        response.read.return_value = b'{"message":{"content":"gemma reply"}}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)

        with patch.dict(
            "os.environ",
            {
                "LOCAL_QWEN_BACKEND": "ollama",
                "LOCAL_QWEN_OLLAMA_MODEL": "gemma4:e4b",
            },
            clear=False,
        ):
            with patch("urllib.request.urlopen", return_value=response):
                payload = local_qwen_casual_service._create_local_qwen_completion(
                    llm=None,
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=32,
                )

        self.assertEqual(payload["choices"][0]["message"]["content"], "gemma reply")

    def test_ollama_connection_error_is_summarized_cleanly(self) -> None:
        message = local_qwen_casual_service._summarize_local_qwen_error(
            RuntimeError("Ollama server is unavailable")
        )

        self.assertIsInstance(message, str)
        self.assertTrue(message)
        self.assertNotIn("unavailable", message.lower())


if __name__ == "__main__":
    unittest.main()
