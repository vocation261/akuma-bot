import unittest

from akuma_bot.infrastructure.alerts.services.space_query_service import XSpacesScraper


class SpaceQueryNamingTests(unittest.TestCase):
    def test_alias_methods_exist(self):
        scraper = XSpacesScraper()
        self.assertTrue(hasattr(scraper, "find_live_spaces_for_accounts"))
        self.assertTrue(hasattr(scraper, "check_spaces"))
        self.assertTrue(callable(scraper.find_live_spaces_for_accounts))
        self.assertTrue(callable(scraper.check_spaces))


if __name__ == "__main__":
    unittest.main()
