import asyncio
import unittest
from unittest.mock import Mock

from akuma_bot.application.alerts.use_cases.manage_alert_accounts import (
    add_account_to_channel,
    map_username,
    remove_account_from_channel,
    set_interval,
)


class InMemoryConfigRepo:
    def __init__(self, data):
        self.data = dict(data)

    def load(self):
        return dict(self.data)

    def save(self, config):
        self.data = dict(config)


class ManageAlertAccountsExtendedTests(unittest.TestCase):
    def test_add_handle_resolver_error(self):
        repo = InMemoryConfigRepo({"user_ids": [], "username_map": {}, "user_channels": {}})
        scraper = Mock()
        scraper.get_user_id.return_value = (None, "network error")

        ok, message = asyncio.run(add_account_to_channel(repo, scraper=scraper, value="someuser", channel_id=10))

        self.assertFalse(ok)
        self.assertIn("Could not resolve", message)

    def test_remove_account_when_empty(self):
        repo = InMemoryConfigRepo({"user_ids": [], "username_map": {}, "user_channels": {}})

        ok, message = remove_account_from_channel(repo, "123", channel_id=10)

        self.assertFalse(ok)
        self.assertEqual(message, "No accounts configured.")

    def test_map_username_requires_numeric_id(self):
        repo = InMemoryConfigRepo({"user_ids": ["123"], "username_map": {}, "user_channels": {}})

        ok, message = map_username(repo, "abc", "user")

        self.assertFalse(ok)
        self.assertEqual(message, "ID must be numeric.")

    def test_set_interval_has_minimum(self):
        repo = InMemoryConfigRepo({"check_interval": 600})

        ok, message = set_interval(repo, 3)

        self.assertTrue(ok)
        self.assertIn("10s", message)
        self.assertEqual(repo.data["check_interval"], 10)


if __name__ == "__main__":
    unittest.main()
