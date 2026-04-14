import unittest
from unittest.mock import patch

import bot


class AddressedQuickReplyTests(unittest.TestCase):
    def test_reply_to_bot_short_status_question_now_skips_quick_reply(self) -> None:
        reply = bot._build_addressed_quick_reply(
            text="살아있어?",
            replied_to_bot=True,
            mentioned_bot=False,
        )

        self.assertIsNone(reply)

    def test_explicit_bot_mention_only_gets_quick_reply(self) -> None:
        with patch.object(bot, "BOT_USERNAME", "gpgrandpa_bot"):
            reply = bot._build_addressed_quick_reply(
                text="@gpgrandpa_bot",
                replied_to_bot=False,
                mentioned_bot=True,
            )

        self.assertIsNotNone(reply)

    def test_non_addressed_short_status_question_stays_unhandled(self) -> None:
        reply = bot._build_addressed_quick_reply(
            text="살아있어?",
            replied_to_bot=False,
            mentioned_bot=False,
        )

        self.assertIsNone(reply)


if __name__ == "__main__":
    unittest.main()
