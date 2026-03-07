import asyncio
import unittest
from unittest.mock import Mock

from akuma_bot.application.alerts.use_cases.manage_alert_accounts import (
    add_account_to_channel,
    list_accounts_for_guild,
    remove_account_from_channel,
)


class InMemoryConfigRepo:
    def __init__(self, data):
        self.data = dict(data)

    def load(self):
        return dict(self.data)

    def save(self, config):
        self.data = dict(config)


class ManageAlertAccountsTests(unittest.TestCase):
    def test_add_new_numeric_account_with_channel(self):
        repo = InMemoryConfigRepo({"user_ids": [], "username_map": {}, "user_channels": {}})
        is_success, message = asyncio.run(add_account_to_channel(repo, scraper=Mock(), value="123", channel_id=77))
        self.assertTrue(is_success)
        self.assertIn("added", message)
        self.assertEqual(repo.data["user_ids"], ["123"])
        self.assertEqual(repo.data["user_channels"]["123"], [77])

    def test_add_existing_account_adds_new_channel(self):
        repo = InMemoryConfigRepo({"user_ids": ["123"], "username_map": {}, "user_channels": {"123": [10]}})
        is_success, message = asyncio.run(add_account_to_channel(repo, scraper=Mock(), value="123", channel_id=20))
        self.assertTrue(is_success)
        self.assertIn("this channel", message)
        self.assertEqual(repo.data["user_channels"]["123"], [10, 20])

    def test_remove_only_current_channel_preserves_global_account(self):
        repo = InMemoryConfigRepo({"user_ids": ["123"], "username_map": {"123": "user"}, "user_channels": {"123": [10, 20]}})
        is_success, message = remove_account_from_channel(repo, "123", channel_id=10)
        self.assertTrue(is_success)
        self.assertIn("channel", message)
        self.assertEqual(repo.data["user_ids"], ["123"])
        self.assertEqual(repo.data["user_channels"]["123"], [20])

    def test_remove_last_channel_removes_account(self):
        repo = InMemoryConfigRepo({"user_ids": ["123"], "username_map": {"123": "user"}, "user_channels": {"123": [10]}})
        is_success, message = remove_account_from_channel(repo, "123", channel_id=10)
        self.assertTrue(is_success)
        self.assertIn("removed", message)
        self.assertNotIn("123", repo.data["user_ids"])
        self.assertNotIn("123", repo.data["user_channels"])

    def test_list_accounts_for_guild_filters_by_channel_guild(self):
        repo = InMemoryConfigRepo(
            {
                "user_ids": ["1", "2"],
                "username_map": {"1": "a", "2": "b"},
                "user_channels": {"1": [100], "2": [200]},
            }
        )
        fake_client = Mock()
        channel_100 = Mock()
        channel_100.guild = Mock(id=999)
        channel_200 = Mock()
        channel_200.guild = Mock(id=888)
        fake_client.get_channel.side_effect = lambda cid: {100: channel_100, 200: channel_200}.get(cid)

        user_ids, username_map = list_accounts_for_guild(repo, fake_client, guild_id=999)
        self.assertEqual(user_ids, ["1"])
        self.assertEqual(username_map["1"], "a")


if __name__ == "__main__":
    unittest.main()
