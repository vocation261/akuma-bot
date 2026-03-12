import unittest

from infrastructure.transcription.downloader import _metadata_from_info


class DownloaderMetadataTests(unittest.TestCase):
    def test_metadata_marks_live_space(self):
        metadata = _metadata_from_info(
            {
                "id": "abc",
                "title": "Live Space",
                "uploader_id": "host",
                "is_live": True,
                "duration": 0,
            },
            "abc",
        )

        self.assertTrue(metadata["is_live"])
        self.assertEqual(metadata["status_key"], "live")

    def test_metadata_marks_recorded_space(self):
        metadata = _metadata_from_info(
            {
                "id": "abc",
                "title": "Recorded Space",
                "uploader_id": "host",
                "is_live": False,
                "duration": 321,
            },
            "abc",
        )

        self.assertFalse(metadata["is_live"])
        self.assertEqual(metadata["status_key"], "ended")
        self.assertEqual(metadata["duration_sec"], 321)


if __name__ == "__main__":
    unittest.main()