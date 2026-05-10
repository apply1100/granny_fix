import unittest

from services.message_constraints_service import (
    build_constraint_violation_reply,
    extract_message_constraints,
    find_reply_constraint_violation,
    validate_tool_selection,
)


class MessageConstraintTests(unittest.TestCase):
    def test_extracts_bitmex_exclusion_from_nearby_instruction(self) -> None:
        constraints = extract_message_constraints("할머니 비트코인 어때 보여 대신 비트맥스 그거 쓰지말고 대답해줘")

        self.assertIn("bitmex", constraints.excluded_tools)

    def test_extracts_text_only_as_capture_exclusion(self) -> None:
        constraints = extract_message_constraints("okx 비트 사진 말고 텍스트로만 정리해줘")

        self.assertTrue(constraints.wants_text_only)
        self.assertIn("kiyotaka_capture", constraints.excluded_tools)

    def test_tool_selection_blocks_excluded_tool(self) -> None:
        constraints = extract_message_constraints("비트맥스 빼고 봐줘")

        violation = validate_tool_selection("bitmex", constraints)

        self.assertIsNotNone(violation)
        assert violation is not None
        self.assertEqual(violation.kind, "tool_excluded")

    def test_reply_guard_blocks_unexplained_excluded_tool_mention(self) -> None:
        constraints = extract_message_constraints("비트맥스 말고 답해줘")

        violation = find_reply_constraint_violation("BitMEX 고래 기준으로는 숏이 강합니다.", constraints)

        self.assertIsNotNone(violation)
        assert violation is not None
        self.assertIn("비트맥스", build_constraint_violation_reply(violation))

    def test_reply_guard_allows_explaining_that_tool_was_excluded(self) -> None:
        constraints = extract_message_constraints("비트맥스 말고 답해줘")

        violation = find_reply_constraint_violation("비트맥스 기준은 빼고 답하겠다.", constraints)

        self.assertIsNone(violation)


if __name__ == "__main__":
    unittest.main()
