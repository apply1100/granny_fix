import unittest

from services.casual_chat_service import build_grandma_quick_reply, build_grandma_safety_reply


class CasualChatQuickReplyTests(unittest.TestCase):
    def test_plain_grandma_call_returns_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매")

        self.assertIsNotNone(reply)
        self.assertIn(
            reply,
            {
                "왜 그러느냐, 할매 여기 있다.",
                "응, 불렀느냐. 할매 왔다.",
                "허허, 여기 있지. 무슨 일 있느냐.",
            },
        )

    def test_status_question_no_longer_uses_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 몇살임")

        self.assertIsNone(reply)

    def test_food_recommendation_no_longer_uses_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 저녁메뉴 추천 좀")

        self.assertIsNone(reply)

    def test_unsettling_request_no_longer_uses_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매니 무덤에서 부활해줘")

        self.assertIsNone(reply)

    def test_safety_reply_handles_self_harm_language(self) -> None:
        reply = build_grandma_safety_reply("할매 자살추천")

        self.assertIsInstance(reply, str)
        self.assertTrue(reply)

    def test_safety_reply_handles_attack_language(self) -> None:
        reply = build_grandma_safety_reply("할매 죽어")

        self.assertIsInstance(reply, str)
        self.assertTrue(reply)


if __name__ == "__main__":
    unittest.main()
