from __future__ import annotations

from typing import Protocol, Any


class SpaceProviderPort(Protocol):
    def find_live_spaces_for_accounts(self, user_ids: list[str], username_map: dict[str, str] | None = None) -> list[dict[str, Any]]: ...


class AlertConfigPort(Protocol):
    def load(self) -> dict: ...
    def save(self, config: dict) -> None: ...


class AlertedSpacePort(Protocol):
    def contains(self, key: str) -> bool: ...
    def add(self, key: str) -> None: ...
