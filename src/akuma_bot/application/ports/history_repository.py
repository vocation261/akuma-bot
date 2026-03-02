from __future__ import annotations

from typing import Protocol


class HistoryRepository(Protocol):
    def log(self, source: str, url: str, status: str, message: str, guild_id: int = 0, channel_id: int = 0, user_id: int = 0) -> None:
        ...

    def latest(self, limit: int = 10, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None) -> list[tuple]:
        ...

    def export_csv(self, output_path: str, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None, limit: int = 1000) -> int:
        ...

    def add_bookmark(self, guild_id: int, channel_id: int, user_id: int, url: str, title: str, position_sec: int, note: str = "") -> None:
        ...

    def latest_bookmarks(self, guild_id: int, limit: int = 10) -> list[tuple]:
        ...

