import unittest

from services.message_intent_service import classify_message_intent, excludes_bitmex_market_source


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

    def test_position_lament_to_grandma_is_casual(self) -> None:
        intent = classify_message_intent(
            text="할머니 나 숏 못쳤어 어캄",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")

    def test_position_lament_alias_to_grandma_is_casual(self) -> None:
        intent = classify_message_intent(
            text="할메이야 롱 못탔어 어쩌냐",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "casual")

    def test_position_analysis_request_still_routes_to_market(self) -> None:
        intent = classify_message_intent(
            text="할매 비트 숏 자리 봐줘",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "market")

    def test_bitmex_exclusion_is_detected_without_losing_market_intent(self) -> None:
        text = "할머니 비트코인 어때 보여 대신 비트맥스 그거 쓰지말고 대답해줘"

        intent = classify_message_intent(
            text=text,
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )

        self.assertEqual(intent, "market")
        self.assertTrue(excludes_bitmex_market_source(text))

    def test_whale_history_intent_detects_trade_history_request(self) -> None:
        intent = classify_message_intent(
            text="할매 오늘 비트맥스 고래 체결된 내역 있어?",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "whale_history")

    def test_okx_btc_intent_detects_private_market_request(self) -> None:
        intent = classify_message_intent(
            text="okx 비트 물량 보여줘",
            chat_type="private",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "okx_heatmap")

    def test_okx_eth_intent_detects_group_request(self) -> None:
        intent = classify_message_intent(
            text="okx 이더 밴드 확인",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "okx_heatmap")

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

    def test_group_generic_ending_question_is_not_treated_as_probe(self) -> None:
        intent = classify_message_intent(
            text="있어?",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "ignore")

    def test_group_market_question_without_direct_address_is_ignored(self) -> None:
        intent = classify_message_intent(
            text="비트 자리 어떨까",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "ignore")

    def test_group_generic_show_me_message_is_ignored(self) -> None:
        intent = classify_message_intent(
            text="차트 보여줘",
            chat_type="group",
            replied_to_bot=False,
            mentioned_bot=False,
        )
        self.assertEqual(intent, "ignore")

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

    def test_death_euphemism_to_grandma_is_unsafe(self) -> None:
        intent = classify_message_intent(
            text="할매 강 강 건너 가소",
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
