import json
import logging
from pathlib import Path
from typing import Dict, List, Union

log = logging.getLogger(__name__)

# The default structure for the main alert configuration file.
# This will be used if the file is missing or corrupted.
DEFAULT_ALERT_CONFIG = {
    "user_ids": [],
    "check_interval": 600,
    "username_map": {},
    "user_channels": {}
}

# The default structure for the file that tracks spaces already alerted.
DEFAULT_ALERTED_SPACES = []


class JsonStore:
    """
    A robust class for handling loading and saving of JSON data to a file.
    It handles file creation, directory creation, and corruption gracefully.
    """

    def __init__(self, path: Union[str, Path], default_data: Union[Dict, List]):
        self.path = Path(path)
        self.default_data = default_data

    def load(self) -> Union[Dict, List]:
        """
        Loads data from the JSON file.
        - If the file doesn't exist, it creates it with default data.
        - If the file is corrupt or empty, it logs an error and returns default data.
        """
        if not self.path.exists():
            log.warning(f"File not found: {self.path}. Creating it with default structure.")
            self.save(self.default_data)
            return self.default_data

        if self.path.is_dir():
            log.warning(f"Path {self.path} is a directory, removing it and creating file with default data.")
            import shutil
            shutil.rmtree(self.path)
            self.save(self.default_data)
            return self.default_data

        try:
            with self.path.open("r", encoding="utf-8") as f:
                content = f.read()
                if not content:
                    log.warning(f"File is empty: {self.path}. Using default data.")
                    return self.default_data
                return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            log.error(f"Failed to load or parse {self.path}: {e}. Using default data as a fallback.")
            return self.default_data

    def save(self, data: Union[Dict, List]) -> None:
        """Saves data to the JSON file, creating parent directories if necessary.

        If the target path happens to be a directory, it will be removed before
        writing the new file in order to avoid IsADirectoryError.
        """
        try:
            if self.path.is_dir():
                log.warning(f"Path {self.path} is a directory, removing before saving.")
                import shutil

                shutil.rmtree(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            log.error(f"Could not write to file {self.path}: {e}")


class AlertConfigRepository:
    def __init__(self):
        import os
        # determine if we are in development mode (ENV=dev or token contains dev)
        is_dev = os.getenv("ENV", "").lower() == "dev" or "dev" in os.getenv("DISCORD_TOKEN", "").lower()
        # allow overriding default locations via env vars
        env_path = os.getenv("ALERT_CONFIG_PATH")
        if env_path:
            path = env_path
        else:
            path = "/app/config.dev.json" if is_dev else "/app/config.json"
        self.store = JsonStore(path, DEFAULT_ALERT_CONFIG)
        # eager load so that missing files are created and directories replaced
        self.store.load()

    def load(self):
        data = self.store.load()
        try:
            return sanitize_alert_config(data)
        except Exception:
            # in case the underlying file is malformed, fall back to defaults
            return DEFAULT_ALERT_CONFIG

    def save(self, data):
        self.store.save(data)


class AlertedSpaceRepository:
    def __init__(self):
        import os
        is_dev = os.getenv("ENV", "").lower() == "dev" or "dev" in os.getenv("DISCORD_TOKEN", "").lower()
        env_path = os.getenv("ALERTED_SPACES_PATH")
        if env_path:
            path = env_path
        else:
            path = "/app/alertados.dev.json" if is_dev else "/app/alertados.json"
        self.store = JsonStore(path, DEFAULT_ALERTED_SPACES)
        # ensure file exists and is not accidentally a directory
        self.store.load()

    def load(self):
        return self.store.load()

    def save(self, data):
        self.store.save(data)


def sanitize_alert_config(config: dict) -> dict:
    """Sanitize and ensure the config has all required keys."""
    sanitized = DEFAULT_ALERT_CONFIG.copy()
    sanitized.update(config)
    # Ensure lists and dicts are properly typed
    sanitized["user_ids"] = list(sanitized.get("user_ids", []))
    sanitized["username_map"] = dict(sanitized.get("username_map", {}))
    sanitized["user_channels"] = dict(sanitized.get("user_channels", {}))
    sanitized["check_interval"] = int(sanitized.get("check_interval", 600) or 600)
    return sanitized