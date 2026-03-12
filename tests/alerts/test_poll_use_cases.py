import unittest
from unittest.mock import Mock

from application.alerts.use_cases.poll_spaces import compute_delivery_key, resolve_target_channels


class PollAlertUseCaseTests(unittest.TestCase):
    def test_compute_delivery_key_live(self):
        alerted_repo = Mock()
        alerted_repo.contains.side_effect = lambda key: False
        should_send, key = compute_delivery_key({"id": "abc", "state": "live", "creator_id": "u1"}, alerted_repo)
        self.assertTrue(should_send)
        self.assertEqual(key, "abc")

    def test_compute_delivery_key_ended(self):
        alerted_repo = Mock()
        alerted_repo.contains.side_effect = lambda key: key == "abc"
        should_send, key = compute_delivery_key({"id": "abc", "state": "ended", "creator_id": "u1"}, alerted_repo)
        self.assertTrue(should_send)
        self.assertEqual(key, "abc:ENDED")

    def test_resolve_target_channels_prefers_user_channels(self):
        client = Mock()
        client.get_channel.side_effect = lambda channel_id: f"channel:{channel_id}"
        channels = resolve_target_channels(
            client,
            {"creator_id": "u1"},
            user_channels={"u1": [1, 2]},
            fallback_channel_ids=[9],
        )
        self.assertEqual(channels, ["channel:1", "channel:2"])

    def test_resolve_target_channels_uses_fallback(self):
        client = Mock()
        client.get_channel.side_effect = lambda channel_id: f"channel:{channel_id}"
        channels = resolve_target_channels(
            client,
            {"creator_id": "u1"},
            user_channels={},
            fallback_channel_ids=[9],
        )
        self.assertEqual(channels, ["channel:9"])


if __name__ == "__main__":
    unittest.main()
