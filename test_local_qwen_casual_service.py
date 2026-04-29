import asyncio
import time
import unittest
from unittest.mock import Mock, patch

from services import local_qwen_casual_service


class LocalQwenDefaultConfigTests(unittest.TestCase):
    def test_server_tuned_defaults_match_current_target(self) -> None:
        self.assertEqual(local_qwen_casual_service.DEFAULT_LOCAL_QWEN_BACKEND, "ollama")
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
        self.assertEqual(local_qwen_casual_service.DEFAULT_LOCAL_QWEN_REQUEST_TIMEOUT_SECONDS, 60)

    def test_backend_can_switch_to_llama_cpp(self) -> None:
        with patch.dict("os.environ", {"LOCAL_QWEN_BACKEND": "llama_cpp"}, clear=False):
            self.assertEqual(local_qwen_casual_service._get_local_qwen_backend(), "llama_cpp")

    def test_ollama_model_defaults_to_requested_tag(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(
                local_qwen_casual_service._get_local_qwen_ollama_model(),
                "gemma4:e4b",
            )


class LocalQwenContextRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(
            "os.environ",
            {"LOCAL_QWEN_BACKEND": "llama_cpp"},
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

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

    def test_mother_persona_reply_is_rejected(self) -> None:
        llm = Mock()
        llm.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "왜 그래? 무슨 일 있니? 엄마한테 다 말해봐."
                    }
                }
            ]
        }

        with patch.object(local_qwen_casual_service, "_get_local_qwen", return_value=llm):
            with self.assertRaises(local_qwen_casual_service.LocalQwenPersonaDriftError):
                local_qwen_casual_service._generate_local_qwen_reply(
                    user_message="니가 왜 내 엄마야",
                    history=[],
                    system_prompt="Reply like a warm Korean grandmother.",
                    mode_instructions="Keep the answer brief and natural.",
                )

    def test_mother_persona_error_does_not_trigger_backoff(self) -> None:
        should_back_off = local_qwen_casual_service._should_back_off_local_qwen_error(
            local_qwen_casual_service.LocalQwenPersonaDriftError("persona drift")
        )

        self.assertFalse(should_back_off)

    def test_persona_drift_returns_fixed_correction_without_backoff(self) -> None:
        local_qwen_casual_service._LOCAL_QWEN_RETRY_AFTER_TS = 0.0
        self.addCleanup(setattr, local_qwen_casual_service, "_LOCAL_QWEN_LAST_ERROR_MESSAGE", None)
        self.addCleanup(setattr, local_qwen_casual_service, "_LOCAL_QWEN_RETRY_AFTER_TS", 0.0)

        with patch.object(
            local_qwen_casual_service,
            "_generate_local_qwen_reply",
            side_effect=local_qwen_casual_service.LocalQwenPersonaDriftError("persona drift"),
        ):
            reply = asyncio.run(
                local_qwen_casual_service.get_local_qwen_casual_reply(
                    user_message="니가 왜 내 엄마야",
                    history=[],
                    system_prompt="Reply like a warm Korean grandmother.",
                    mode_instructions="Keep the answer brief and natural.",
                )
            )

        self.assertIsNotNone(reply)
        self.assertIn("할머니", reply)
        self.assertIn("엄마가 아니라", reply)
        self.assertEqual(local_qwen_casual_service._LOCAL_QWEN_RETRY_AFTER_TS, 0.0)

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
            with patch("urllib.request.urlopen", return_value=response) as urlopen:
                payload = local_qwen_casual_service._create_local_qwen_completion(
                    llm=None,
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=32,
                )

        self.assertEqual(payload["choices"][0]["message"]["content"], "gemma reply")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 60)

    def test_ollama_timeout_can_be_configured_with_bounds(self) -> None:
        with patch.dict("os.environ", {"LOCAL_QWEN_REQUEST_TIMEOUT_SECONDS": "2"}, clear=False):
            self.assertEqual(local_qwen_casual_service._get_local_qwen_request_timeout_seconds(), 5)

        with patch.dict("os.environ", {"LOCAL_QWEN_REQUEST_TIMEOUT_SECONDS": "90"}, clear=False):
            self.assertEqual(local_qwen_casual_service._get_local_qwen_request_timeout_seconds(), 60)

    def test_ollama_timeout_defaults_to_longer_local_model_budget(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(local_qwen_casual_service._get_local_qwen_request_timeout_seconds(), 60)

    def test_ollama_connection_error_is_summarized_cleanly(self) -> None:
        message = local_qwen_casual_service._summarize_local_qwen_error(
            RuntimeError("Ollama server is unavailable")
        )

        self.assertIsInstance(message, str)
        self.assertTrue(message)
        self.assertNotIn("unavailable", message.lower())

    def test_ollama_timeout_error_is_summarized_cleanly(self) -> None:
        message = local_qwen_casual_service._summarize_local_qwen_error(
            TimeoutError("timed out")
        )

        self.assertEqual(message, "Ollama 응답 시간이 초과되었습니다.")

    def test_user_facing_error_hides_system_library_detail(self) -> None:
        local_qwen_casual_service._LOCAL_QWEN_LAST_ERROR_MESSAGE = (
            local_qwen_casual_service._summarize_local_qwen_error(
                RuntimeError("libgomp.so.1: cannot open shared object file")
            )
        )
        local_qwen_casual_service._LOCAL_QWEN_RETRY_AFTER_TS = 0.0
        self.addCleanup(setattr, local_qwen_casual_service, "_LOCAL_QWEN_LAST_ERROR_MESSAGE", None)

        reply = local_qwen_casual_service.build_local_qwen_error_reply()

        self.assertIn("할매", reply)
        self.assertNotIn("Qwen", reply)
        self.assertNotIn("libgomp", reply)


    def test_cooldown_reply_does_not_expose_countdown_seconds(self) -> None:
        local_qwen_casual_service._LOCAL_QWEN_RETRY_AFTER_TS = time.time() + 120
        self.addCleanup(setattr, local_qwen_casual_service, "_LOCAL_QWEN_RETRY_AFTER_TS", 0.0)

        reply = local_qwen_casual_service.build_local_qwen_error_reply()

        self.assertNotRegex(reply, r"\d+")
        self.assertNotIn("답변 도구", reply)


class LocalQwenFeatureToggleTests(unittest.TestCase):
    def tearDown(self) -> None:
        # Keep global module state from leaking between tests.
        local_qwen_casual_service._LOCAL_QWEN_LAST_ERROR_MESSAGE = None
        local_qwen_casual_service._LOCAL_QWEN_RETRY_AFTER_TS = 0.0

    def test_disabled_flag_returns_none_and_error_reply_is_user_facing(self) -> None:
        with patch.dict("os.environ", {"LOCAL_QWEN_ENABLED": "0"}, clear=False):
            reply = asyncio.run(
                local_qwen_casual_service.get_local_qwen_casual_reply(
                    user_message="할머니 뭐해",
                    history=[],
                    system_prompt="Reply like a warm Korean grandmother.",
                    mode_instructions="Keep the answer brief and natural.",
                )
            )
            error_reply = local_qwen_casual_service.build_local_qwen_error_reply()

        self.assertIsNone(reply)
        self.assertIn("할매", error_reply)
        self.assertNotIn("답변 도구", error_reply)

    def test_cooldown_short_circuits_requests(self) -> None:
        local_qwen_casual_service._LOCAL_QWEN_RETRY_AFTER_TS = time.time() + 120

        with patch.object(local_qwen_casual_service, "_generate_local_qwen_reply") as generate:
            reply = asyncio.run(
                local_qwen_casual_service.get_local_qwen_casual_reply(
                    user_message="할머니 뭐해",
                    history=[],
                    system_prompt="Reply like a warm Korean grandmother.",
                    mode_instructions="Keep the answer brief and natural.",
                )
            )

        self.assertIsNone(reply)
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
