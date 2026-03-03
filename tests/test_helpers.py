import unittest

from akuma_bot.infrastructure.media.yt_dlp_resolver import YtDlpResolver
from akuma_bot.infrastructure.runtime.text_utils import extract_space_id, format_elapsed, validate_playable_url


class HelpersTestCase(unittest.TestCase):
    def test_fmt_elapsed(self):
        self.assertEqual(format_elapsed(5), '5s')
        self.assertEqual(format_elapsed(65), '1m 05s')
        self.assertEqual(format_elapsed(3661), '1h 01m 01s')

    def test_url_validation(self):
        resolver = YtDlpResolver()
        self.assertTrue(resolver.is_space_url('https://x.com/i/spaces/abc123'))
        self.assertFalse(resolver.is_space_url('notaurl'))

        ok, msg = validate_playable_url('https://youtube.com/watch?v=123')
        self.assertFalse(ok)
        self.assertIn('only x space urls', msg.lower())

        ok, msg = validate_playable_url('https://discord.com/channels/1/2/3')
        self.assertFalse(ok)
        self.assertIn('not playable', msg.lower())

    def test_space_helpers(self):
        url = 'https://x.com/i/spaces/1RDxlaNnVgQJL'
        self.assertTrue(YtDlpResolver().is_space_url(url))
        self.assertEqual(extract_space_id(url), '1RDxlaNnVgQJL')


if __name__ == '__main__':
    unittest.main()
