import unittest

from services.message_intent_service import classify_message_intent


class MessageIntentTests(unittest.TestCase):
    def test_market_intent_detects_bit_position_question(self) -> None:
        intent = classify_message_intent(
            text="할매 비트 자리 어떨까",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "market")

    def test_market_intent_detects_bit_impression_question(self) -> None:
        intent = classify_message_intent(
            text="할매니 비트 어때보여",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "market")

    def test_whale_history_intent_detects_trade_history_request(self) -> None:
        intent = classify_message_intent(
            text="할매 오늘 비트맥스 고래 체결된 내역 있어?",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "whale_history")

    def test_casual_intent_keeps_short_grandma_status_question(self) -> None:
        intent = classify_message_intent(
            text="할매 요즘 뭐해",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")

    def test_group_short_grandma_call_is_not_ignored(self) -> None:
        intent = classify_message_intent(
            text="할미",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")

    def test_group_short_noise_still_ignored(self) -> None:
        intent = classify_message_intent(
            text="ㅎㅎㅎ",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "ignore")

    def test_group_direct_status_probe_is_casual(self) -> None:
        intent = classify_message_intent(
            text="살아있나?",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")

    def test_private_direct_status_probe_is_casual(self) -> None:
        intent = classify_message_intent(
            text="답장해",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")

    def test_direct_attack_to_grandma_is_unsafe(self) -> None:
        intent = classify_message_intent(
            text="할매 죽어",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "unsafe")

    def test_self_harm_request_to_grandma_is_unsafe(self) -> None:
        intent = classify_message_intent(
            text="할매 자살추천",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "unsafe")


if __name__ == "__main__":
    unittest.main()
