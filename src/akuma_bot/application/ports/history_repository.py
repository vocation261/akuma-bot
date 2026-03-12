from __future__ import annotations

from typing import Protocol


class HistoryRepository(Protocol):
    def log(self, source: str, url: str, status: str, message: str, guild_id: int = 0, channel_id: int = 0, user_id: int = 0, user_name: str = "", user_tag: str = "", event_type: str = "play") -> None:
        ...

    def latest(self, limit: int = 10, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None) -> list[tuple]:
        ...

    def export_csv(self, output_path: str, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None, limit: int = 1000) -> int:
        ...

    def add_bookmark(self, guild_id: int, channel_id: int, user_id: int, url: str, title: str, position_sec: int, note: str = "", user_name: str = "", user_tag: str = "") -> None:
        ...

    def latest_bookmarks(self, guild_id: int, limit: int = 10) -> list[tuple]:
        ...

    def delete_bookmark(self, guild_id: int, bookmark_id: int) -> bool:
        ...

    def clear_bookmarks(self, guild_id: int) -> int:
        ...

    def log_audit_event(self, event_type: str, guild_id: int = 0, channel_id: int = 0, user_id: int = 0, user_name: str = "", user_tag: str = "", resource_id: str = "", resource_name: str = "", details: str = "") -> None:
        ...

    def latest_audit_events(self, guild_id: int | None = None, event_type: str | None = None, limit: int = 20) -> list[tuple]:
        ...

