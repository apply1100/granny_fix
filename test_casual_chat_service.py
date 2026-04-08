import unittest

from services.casual_chat_service import build_grandma_quick_reply


class CasualChatQuickReplyTests(unittest.TestCase):
    def test_food_recommendation_returns_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 저녁메뉴 추천 좀")

        self.assertIsNotNone(reply)
        self.assertIn(
            reply,
            {
                "에구, 저녁거리면 너무 거창한 건 말고 계란말이에 된장국 하나 놓고 김치랑 먹어도 속이 편하단다.",
                "할매 같으면 저녁엔 된장찌개나 김치찌개에 두부 좀 넣고 밥 한 그릇 먹겠다. 반찬은 멸치나 계란이면 충분허다.",
                "오늘 저녁은 너무 복잡하게 말고 비빔밥이나 볶음밥처럼 한 그릇으로 끝나는 게 낫겠다. 국물 땡기면 어묵탕도 괜찮다.",
            },
        )

    def test_food_mention_without_recommendation_stays_out_of_quick_reply(self) -> None:
        reply = build_grandma_quick_reply("할매 저녁 먹었어")

        self.assertIsNone(reply)


if __name__ == "__main__":
    unittest.main()
