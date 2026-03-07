"""Domain services and repositories for the History bounded context."""

from abc import ABC, abstractmethod
from typing import List, Optional

from .entities import AuditLog, AuditLogId, Bookmark, BookmarkId, PlayHistory, PlayHistoryId
from .value_objects import ChannelId, EventType, GuildId, UserId


class PlayHistoryRepository(ABC):
    """Repository port for PlayHistory aggregate."""

    @abstractmethod
    async def save(self, play_history: PlayHistory) -> PlayHistoryId:
        """Save a playback event."""
        raise NotImplementedError

    @abstractmethod
    async def by_guild(
        self, guild_id: GuildId, limit: int = 10
    ) -> List[PlayHistory]:
        """Retrieve playback events for a guild."""
        raise NotImplementedError

    @abstractmethod
    async def by_user(
        self, user_id: UserId, limit: int = 10
    ) -> List[PlayHistory]:
        """Retrieve playback events for a user."""
        raise NotImplementedError


class BookmarkRepository(ABC):
    """Repository port for Bookmark aggregate."""

    @abstractmethod
    async def save(self, bookmark: Bookmark) -> BookmarkId:
        """Save a bookmark."""
        raise NotImplementedError

    @abstractmethod
    async def by_id(self, bookmark_id: BookmarkId) -> Optional[Bookmark]:
        """Retrieve a bookmark by ID."""
        raise NotImplementedError

    @abstractmethod
    async def by_guild(
        self, guild_id: GuildId, limit: int = 10
    ) -> List[Bookmark]:
        """Retrieve bookmarks for a guild."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, bookmark_id: BookmarkId) -> bool:
        """Delete a bookmark."""
        raise NotImplementedError

    @abstractmethod
    async def delete_all_for_guild(self, guild_id: GuildId) -> int:
        """Delete all bookmarks for a guild."""
        raise NotImplementedError


class AuditLogRepository(ABC):
    """Repository port for AuditLog aggregate."""

    @abstractmethod
    async def save(self, audit_log: AuditLog) -> AuditLogId:
        """Save an audit log entry."""
        raise NotImplementedError

    @abstractmethod
    async def by_guild(
        self, guild_id: GuildId, limit: int = 20
    ) -> List[AuditLog]:
        """Retrieve audit logs for a guild."""
        raise NotImplementedError

    @abstractmethod
    async def by_event_type(
        self, event_type: EventType, limit: int = 20
    ) -> List[AuditLog]:
        """Retrieve audit logs by event type."""
        raise NotImplementedError

    @abstractmethod
    async def by_user(
        self, user_id: UserId, limit: int = 20
    ) -> List[AuditLog]:
        """Retrieve audit logs for a user."""
        raise NotImplementedError


class HistoryExporter(ABC):
    """Port for exporting history data."""

    @abstractmethod
    async def export_to_csv(
        self,
        guild_id: GuildId,
        output_path: str,
        max_rows: int = 1000,
    ) -> int:
        """Export playback history to CSV file."""
        raise NotImplementedError
