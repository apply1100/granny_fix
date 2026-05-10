import unittest

from services.casual_chat_service import build_grandma_quick_reply
from services.message_intent_service import classify_message_intent


class GrandmaCallVariantTests(unittest.TestCase):
    def test_halmi_is_classified_as_casual(self) -> None:
        intent = classify_message_intent(
            text="할미",
            chat_type="supergroup",
            replied_to_bot=False,
            mentioned_bot=False,
        )

        self.assertEqual(intent, "casual")

    def test_halmi_gets_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할미")

        self.assertIsNotNone(reply)


if __name__ == "__main__":
    unittest.main()
