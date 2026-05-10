import unittest

from services.message_router_service import route_message


class MessageRouterTests(unittest.TestCase):
    def test_bitmex_exclusion_routes_to_clarify_without_tool(self) -> None:
        route = route_message(
            text="할머니 비트코인 어때 보여 대신 비트맥스 그거 쓰지말고 대답해줘",
            chat_type="group",
        )

        self.assertEqual(route.intent, "market")
        self.assertEqual(route.action, "clarify")
        self.assertIsNone(route.tool)
        self.assertIn("bitmex", route.excluded_tools)

    def test_okx_eth_request_routes_to_okx_tool_with_asset(self) -> None:
        route = route_message(
            text="okx 이더 밴드 확인",
            chat_type="group",
        )

        self.assertEqual(route.intent, "okx_heatmap")
        self.assertEqual(route.action, "tool")
        self.assertEqual(route.tool, "okx_heatmap")
        self.assertEqual(route.asset, "eth")

    def test_unaddressed_group_market_chatter_is_ignored(self) -> None:
        route = route_message(
            text="비트 자리 어떨까",
            chat_type="group",
        )

        self.assertEqual(route.intent, "ignore")
        self.assertEqual(route.action, "ignore")

    def test_short_unsettling_call_uses_quick_reply_route(self) -> None:
        route = route_message(
            text="할머니 부활",
            chat_type="group",
        )

        self.assertEqual(route.intent, "casual")
        self.assertEqual(route.action, "quick_reply")

    def test_breakfast_recommendation_uses_quick_reply_route(self) -> None:
        route = route_message(
            text="할매 내일 아침 추천 좀",
            chat_type="group",
        )

        self.assertEqual(route.intent, "casual")
        self.assertEqual(route.action, "quick_reply")

    def test_death_euphemism_to_grandma_routes_to_safety(self) -> None:
        route = route_message(
            text="할매 강 강 건너 가소",
            chat_type="group",
        )

        self.assertEqual(route.intent, "unsafe")
        self.assertEqual(route.action, "safety_reply")


if __name__ == "__main__":
    unittest.main()
