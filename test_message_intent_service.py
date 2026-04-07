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

    def test_casual_intent_keeps_short_grandma_status_question(self) -> None:
        intent = classify_message_intent(
            text="할매 요즘 뭐해",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")


if __name__ == "__main__":
    unittest.main()
