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

    def test_grandma_call_with_laugh_tail_returns_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할머니가ㅎ")

        self.assertIsNotNone(reply)
        self.assertIn(
            reply,
            {
                "왜 그러느냐, 할매 여기 있다.",
                "응, 불렀느냐. 할매 왔다.",
                "허허, 여기 있지. 무슨 일 있느냐.",
            },
        )

    def test_grandma_dementia_complaint_returns_quick_repair_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 치매.")

        self.assertIsNotNone(reply)
        self.assertIn("할매", reply)

    def test_grandma_short_status_slang_returns_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 오늘 뭐함")

        self.assertIsNotNone(reply)

    def test_status_question_no_longer_uses_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 몇살임")

        self.assertIsNone(reply)

    def test_food_recommendation_uses_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 저녁메뉴 추천 좀")

        self.assertIsNotNone(reply)

    def test_breakfast_recommendation_mentions_breakfast(self) -> None:
        reply = build_grandma_quick_reply("할매 내일 아침 추천 좀")

        self.assertIsNotNone(reply)
        self.assertIn("아침", reply)

    def test_oauth_question_gets_plain_grandma_explanation(self) -> None:
        reply = build_grandma_quick_reply("할매 OAuth가 뭐야?")

        self.assertIsNotNone(reply)
        self.assertIn("비밀번호", reply)
        self.assertIn("허락", reply)
        self.assertIn("구글", reply)

    def test_short_unsettling_grandma_request_returns_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할머니 부활")

        self.assertIsNotNone(reply)
        self.assertIn(
            reply,
            {
                "에구, 그런 말은 사람 놀라니까 하지 마라. 저녁 뭐 먹을지나 심심한 얘기처럼 편한 걸로 다시 말해보거라.",
                "아이고, 무덤이니 부활이니 그런 소린 듣기만 해도 등골이 서늘하다. 할매한텐 무서운 장난 말고 딴 얘기 해라.",
                "허허, 그런 으스스한 말은 할매가 못 받겠다. 밥이나 날씨 같은 편한 얘기로 다시 불러보거라.",
            },
        )

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
