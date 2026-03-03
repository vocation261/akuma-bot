from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[4]


def sanitize_alert_config(raw: dict | None) -> dict:
    payload = raw if isinstance(raw, dict) else {}

    user_ids_raw = payload.get("user_ids", [])
    if not isinstance(user_ids_raw, list):
        user_ids_raw = []
    user_ids: list[str] = []
    for value in user_ids_raw:
        item = str(value).strip()
        if item.isdigit() and item not in user_ids:
            user_ids.append(item)

    username_map_raw = payload.get("username_map", {})
    username_map: dict[str, str] = {}
    if isinstance(username_map_raw, dict):
        for uid, username in username_map_raw.items():
            uid_str = str(uid).strip()
            if not uid_str.isdigit():
                continue
            if not isinstance(username, str):
                continue
            cleaned = username.strip().lstrip("@")
            if cleaned:
                username_map[uid_str] = cleaned

    try:
        interval = int(payload.get("check_interval", 600))
    except Exception:
        interval = 600
    if interval < 10:
        interval = 10

    try:
        retry_attempts = int(payload.get("retry_attempts", 3))
    except Exception:
        retry_attempts = 3
    retry_attempts = max(1, min(6, retry_attempts))

    try:
        retry_backoff_seconds = float(payload.get("retry_backoff_seconds", 1.0))
    except Exception:
        retry_backoff_seconds = 1.0
    retry_backoff_seconds = max(0.0, min(10.0, retry_backoff_seconds))

    return {
        "user_ids": user_ids,
        "check_interval": interval,
        "username_map": username_map,
        "retry_attempts": retry_attempts,
        "retry_backoff_seconds": retry_backoff_seconds,
    }


@dataclass(slots=True)
class AlertConfigRepository:
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.path is None:
            raw_path = os.environ.get("ALERT_CONFIG_PATH", "").strip()
            self.path = Path(raw_path) if raw_path else (_root_dir() / "config.json")

    def load(self) -> dict:
        if not self.path.exists():
            data = sanitize_alert_config(None)
            self.save(data)
            return data
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return sanitize_alert_config(json.load(handle))
        except Exception:
            return sanitize_alert_config(None)

    def save(self, config: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(sanitize_alert_config(config), handle, indent=4, ensure_ascii=False)


@dataclass(slots=True)
class AlertedSpaceRepository:
    path: Path | None = None
    _cache: set[str] | None = None

    def __post_init__(self) -> None:
        if self.path is None:
            raw_path = os.environ.get("ALERTED_SPACES_PATH", "").strip()
            self.path = Path(raw_path) if raw_path else (_root_dir() / "alertados.json")

    def load(self) -> set[str]:
        if self._cache is not None:
            return set(self._cache)
        if not self.path.exists():
            self._cache = set()
            return set()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._cache = {str(item).strip() for item in data if str(item).strip()}
        except Exception:
            self._cache = set()
        return set(self._cache)

    def contains(self, key: str) -> bool:
        if self._cache is None:
            self.load()
        return key in (self._cache or set())

    def add(self, key: str) -> None:
        if self._cache is None:
            self.load()
        self._cache = self._cache or set()
        self._cache.add(str(key))
        self.save(self._cache)

    def save(self, alerted: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = {str(item).strip() for item in alerted if str(item).strip()}
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(sorted(self._cache), handle, indent=4, ensure_ascii=False)
