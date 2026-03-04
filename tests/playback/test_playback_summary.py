import unittest

from akuma_bot.infrastructure.discord.playback.playback_summary_service import build_end_notice, session_details_snapshot


class FakeSession:
    host = ""
    host_handle = "sample"
    title = "Space"
    participants = 10
    listeners = 5
    current_url = "https://x.com/i/spaces/abc"

    @staticmethod
    def elapsed():
        return 90


class PlaybackSummaryTests(unittest.TestCase):
    def test_session_details_snapshot(self):
        details = session_details_snapshot(FakeSession())
        self.assertEqual(details["host"], "@sample")
        self.assertEqual(details["title"], "Space")

    def test_build_end_notice_inactivity(self):
        details = {
            "title": "Space",
            "host": "@sample",
            "participants": 10,
            "listeners": 5,
            "duration": "1m 30s",
            "url": "https://x.com/i/spaces/abc",
        }
        notice = build_end_notice("inactivity", details)
        self.assertIn("inactivity", notice.lower())
        self.assertIn("Space", notice)


if __name__ == "__main__":
    unittest.main()
