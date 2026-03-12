import os
import tempfile
import unittest
from pathlib import Path

from infrastructure.alerts.config_store import (
    JsonStore,
    DEFAULT_ALERT_CONFIG,
    DEFAULT_ALERTED_SPACES,
    AlertConfigRepository,
    AlertedSpaceRepository,
)


class JsonStoreTests(unittest.TestCase):
    def test_jsonstore_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            store = JsonStore(path, {"a": 1})
            data = store.load()
            self.assertEqual(data, {"a": 1})
            self.assertTrue(path.exists())
            with path.open("r", encoding="utf-8") as f:
                self.assertIn('"a": 1', f.read())

    def test_jsonstore_removes_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dir_as_file"
            path.mkdir()
            store = JsonStore(path, {"b": 2})
            data = store.load()
            self.assertEqual(data, {"b": 2})
            # after loading it should be a regular file
            self.assertTrue(path.is_file())

    def test_save_overwrites_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dir_as_file"
            path.mkdir()
            store = JsonStore(path, {"c": 3})
            store.save({"c": 4})
            self.assertEqual(store.load(), {"c": 4})


class RepositoryPathTests(unittest.TestCase):
    def test_alert_config_repository_selects_dev_path(self):
        os.environ["ENV"] = "dev"
        repo = AlertConfigRepository()
        self.assertTrue(str(repo.store.path).endswith("config.dev.json"))

    def test_alert_config_repository_selects_prod_path(self):
        os.environ.pop("ENV", None)
        repo = AlertConfigRepository()
        self.assertTrue(str(repo.store.path).endswith("config.json"))

    def test_alerted_space_repository_selects_dev_path(self):
        os.environ["ENV"] = "dev"
        repo = AlertedSpaceRepository()
        self.assertTrue(str(repo.store.path).endswith("alertados.dev.json"))

    def test_alerted_space_repository_selects_prod_path(self):
        os.environ.pop("ENV", None)
        repo = AlertedSpaceRepository()
        self.assertTrue(str(repo.store.path).endswith("alertados.json"))

    def test_load_sanitizes_missing_keys(self):
        # repository should always return a config with required fields even when
        # the underlying file is empty or missing keys.
        with tempfile.TemporaryDirectory() as tmp:
            dummy = Path(tmp) / "cfg.json"
            dummy.write_text("{}", encoding="utf-8")
            repo = AlertConfigRepository()
            # hijack the internal store to point at our temporary file
            repo.store = JsonStore(dummy, DEFAULT_ALERT_CONFIG)
            result = repo.load()
            self.assertIn("user_ids", result)
            self.assertIsInstance(result["user_ids"], list)
            self.assertIn("user_channels", result)
            self.assertIsInstance(result["user_channels"], dict)
            self.assertEqual(result["check_interval"], 600)

    def test_env_path_override(self):
        # if environment variable is set the repository should use it
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom.json"
            os.environ["ALERT_CONFIG_PATH"] = str(custom)
            repo = AlertConfigRepository()
            self.assertEqual(repo.store.path, custom)
            os.environ.pop("ALERT_CONFIG_PATH", None)

    def test_env_path_override_alerted(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "alerted.json"
            os.environ["ALERTED_SPACES_PATH"] = str(custom)
            repo = AlertedSpaceRepository()
            self.assertEqual(repo.store.path, custom)
            os.environ.pop("ALERTED_SPACES_PATH", None)


if __name__ == "__main__":
    unittest.main()
