import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from infrastructure.alerts.services.monitor_runner import (
    SpaceAlertMonitor,
    build_space_alert_embed,
)


class DummyConfigRepo:
    def __init__(self, data):
        self._data = dict(data)
        self.path = "dummy-config.json"

    def load(self):
        return dict(self._data)


class DummyAlertedRepo:
    def __init__(self):
        self.path = "dummy-alerted.json"

    def add(self, _key):
        pass


class MonitorRunnerTests(unittest.TestCase):
    def test_build_space_alert_embed_live(self):
        embed = build_space_alert_embed(
            {
                "id": "abc123",
                "state": "live",
                "username": "hostuser",
                "name": "Host Name",
                "creator_id": "999",
                "listener_count": 42,
                "followers_count": 1000,
                "title": "My Space",
            }
        )

        self.assertEqual(embed.title, "🚨 LIVE SPACE")
        self.assertIn("active Space", embed.description)
        self.assertEqual(embed.url, "https://x.com/i/spaces/abc123")

    def test_build_space_alert_embed_ended(self):
        embed = build_space_alert_embed({"id": "abc123", "state": "ended"})
        self.assertEqual(embed.title, "✅ SPACE ENDED")
        self.assertIn("has ended", embed.description)

    def test_channel_ids_parsing_and_dedup(self):
        monitor = SpaceAlertMonitor(
            client=Mock(),
            config_repo=DummyConfigRepo({}),
            alerted_repo=DummyAlertedRepo(),
            scraper=Mock(),
        )

        with patch.dict(
            os.environ,
            {
                "DISCORD_ALERT_CHANNEL_IDS": "1,2,invalid,2",
                "DISCORD_ALERT_CHANNEL_ID": "3",
            },
            clear=False,
        ):
            self.assertEqual(monitor._channel_ids(), [1, 2, 3])

    def test_status_text_uses_english_labels(self):
        monitor = SpaceAlertMonitor(
            client=Mock(),
            config_repo=DummyConfigRepo(
                {
                    "user_ids": ["1", "2"],
                    "check_interval": 60,
                    "user_channels": {"1": [11], "2": [22, 33]},
                }
            ),
            alerted_repo=DummyAlertedRepo(),
            scraper=Mock(),
        )

        with patch.dict(os.environ, {"DISCORD_ALERT_CHANNEL_IDS": "10,20"}, clear=False):
            status = monitor.status_text()

        self.assertIn("Monitored: 2", status)
        self.assertIn("Interval: 60s", status)
        self.assertIn("Channels per account: 3", status)
        self.assertIn("Alert channels: [10, 20]", status)

    def test_send_alert_partial_delivery_notifies_admin(self):
        client = Mock()
        admin_channel = Mock()
        admin_channel.send = AsyncMock(return_value=None)
        client.get_channel.side_effect = lambda cid: admin_channel if cid == 999 else None

        monitor = SpaceAlertMonitor(
            client=client,
            config_repo=DummyConfigRepo({}),
            alerted_repo=DummyAlertedRepo(),
            scraper=Mock(),
        )

        ok_channel = Mock()
        ok_channel.send = AsyncMock(return_value=None)
        bad_channel = Mock()
        bad_channel.send = AsyncMock(side_effect=RuntimeError("send failed"))

        with patch.dict(os.environ, {"DISCORD_ADMIN_CHANNEL_ID": "999"}, clear=False):
            result = asyncio.run(
                monitor._send_alert_to_channels(
                    {"id": "space1", "state": "live", "username": "host"},
                    [ok_channel, bad_channel],
                )
            )

        self.assertTrue(result)
        self.assertTrue(admin_channel.send.await_count >= 1)


if __name__ == "__main__":
    unittest.main()
