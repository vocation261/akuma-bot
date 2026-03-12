"""Application layer: Use cases for the History bounded context."""

from dataclasses import dataclass
from typing import List, Optional

from akuma_bot.domain.history import (
    AuditLog,
    Bookmark,
    BookmarkId,
    ChannelId,
    EventType,
    GuildId,
    PlayHistory,
    PlaySource,
    PlayStatus,
    ResourceReference,
    Timestamp,
    UserId,
    UserInfo,
)
from akuma_bot.domain.history.repositories import (
    AuditLogRepository,
    BookmarkRepository,
    HistoryExporter,
    PlayHistoryRepository,
)


@dataclass
class LogPlaybackUseCase:
    """Use case: Record an audio playback event."""

    play_history_repo: PlayHistoryRepository
    audit_log_repo: AuditLogRepository

    async def execute(
        self,
        *,
        timestamp: Timestamp,
        source: PlaySource,
        url: str,
        status: PlayStatus,
        message: str,
        guild_id: GuildId,
        channel_id: ChannelId,
        user_id: UserId,
        user_name: str,
        user_tag: str,
    ) -> None:
        """Execute: Record a playback event."""
        user_info = UserInfo(user_id=user_id, name=user_name, tag=user_tag)

        play_event = PlayHistory(
            id=None,
            timestamp=timestamp,
            source=source,
            url=url,
            status=status,
            message=message,
            guild_id=guild_id,
            channel_id=channel_id,
            user_info=user_info,
            event_type=EventType.PLAY_AUDIO,
        )

        await self.play_history_repo.save(play_event)


@dataclass
class AddBookmarkUseCase:
    """Use case: Create a bookmark at the current position."""

    bookmark_repo: BookmarkRepository
    audit_log_repo: AuditLogRepository

    async def execute(
        self,
        *,
        timestamp: Timestamp,
        guild_id: GuildId,
        channel_id: ChannelId,
        user_id: UserId,
        user_name: str,
        user_tag: str,
        url: str,
        title: str,
        position_seconds: int,
        note: str = "",
    ) -> BookmarkId:
        """Execute: Add a bookmark."""
        user_info = UserInfo(user_id=user_id, name=user_name, tag=user_tag)

        bookmark = Bookmark(
            id=None,
            timestamp=timestamp,
            guild_id=guild_id,
            channel_id=channel_id,
            user_info=user_info,
            url=url,
            title=title,
            position_seconds=position_seconds,
            note=note,
        )

        bookmark_id = await self.bookmark_repo.save(bookmark)

        audit_entry = AuditLog(
            id=None,
            timestamp=timestamp,
            event_type=EventType.BOOKMARK_ADD,
            guild_id=guild_id,
            channel_id=channel_id,
            user_info=user_info,
            resource=ResourceReference(
                resource_id="",
                resource_name=title,
            ),
            details=f"Position: {position_seconds}s, URL: {url}",
        )

        await self.audit_log_repo.save(audit_entry)

        return bookmark_id


@dataclass
class DeleteBookmarkUseCase:
    """Use case: Remove a bookmark."""

    bookmark_repo: BookmarkRepository
    audit_log_repo: AuditLogRepository

    async def execute(
        self,
        *,
        bookmark_id: BookmarkId,
        guild_id: GuildId,
        channel_id: ChannelId,
        user_id: UserId,
        user_name: str,
        user_tag: str,
        timestamp: Timestamp,
    ) -> bool:
        """Execute: Delete a bookmark."""
        user_info = UserInfo(user_id=user_id, name=user_name, tag=user_tag)

        deleted = await self.bookmark_repo.delete(bookmark_id)

        if deleted:
            audit_entry = AuditLog(
                id=None,
                timestamp=timestamp,
                event_type=EventType.BOOKMARK_DELETE,
                guild_id=guild_id,
                channel_id=channel_id,
                user_info=user_info,
                resource=ResourceReference(
                    resource_id=str(bookmark_id),
                    resource_name="",
                ),
                details=f"Bookmark {bookmark_id} deleted",
            )
            await self.audit_log_repo.save(audit_entry)

        return deleted


@dataclass
class ClearBookmarksUseCase:
    """Use case: Remove all bookmarks for a guild."""

    bookmark_repo: BookmarkRepository
    audit_log_repo: AuditLogRepository

    async def execute(
        self,
        *,
        guild_id: GuildId,
        channel_id: ChannelId,
        user_id: UserId,
        user_name: str,
        user_tag: str,
        timestamp: Timestamp,
    ) -> int:
        """Execute: Clear all bookmarks for a guild."""
        user_info = UserInfo(user_id=user_id, name=user_name, tag=user_tag)

        deleted_count = await self.bookmark_repo.delete_all_for_guild(guild_id)

        if deleted_count > 0:
            audit_entry = AuditLog(
                id=None,
                timestamp=timestamp,
                event_type=EventType.BOOKMARK_CLEAR,
                guild_id=guild_id,
                channel_id=channel_id,
                user_info=user_info,
                resource=None,
                details=f"Cleared {deleted_count} bookmarks",
            )
            await self.audit_log_repo.save(audit_entry)

        return deleted_count


@dataclass
class LogAuditEventUseCase:
    """Use case: Record an administrative action."""

    audit_log_repo: AuditLogRepository

    async def execute(
        self,
        *,
        event_type: EventType,
        timestamp: Timestamp,
        guild_id: GuildId,
        channel_id: ChannelId,
        user_id: UserId,
        user_name: str,
        user_tag: str,
        resource_id: str = "",
        resource_name: str = "",
        details: str = "",
    ) -> AuditLogId:
        """Execute: Log an audit event."""
        user_info = UserInfo(user_id=user_id, name=user_name, tag=user_tag)

        resource = None
        if resource_id or resource_name:
            resource = ResourceReference(
                resource_id=resource_id,
                resource_name=resource_name,
            )

        audit_entry = AuditLog(
            id=None,
            timestamp=timestamp,
            event_type=event_type,
            guild_id=guild_id,
            channel_id=channel_id,
            user_info=user_info,
            resource=resource,
            details=details,
        )

        return await self.audit_log_repo.save(audit_entry)


@dataclass
class QueryPlayHistoryUseCase:
    """Use case: Query playback history."""

    play_history_repo: PlayHistoryRepository

    async def by_guild(
        self, guild_id: GuildId, limit: int = 10
    ) -> List[PlayHistory]:
        """Query: Retrieve playback events for a guild."""
        return await self.play_history_repo.by_guild(guild_id, limit)

    async def by_user(
        self, user_id: UserId, limit: int = 10
    ) -> List[PlayHistory]:
        """Query: Retrieve playback events for a user."""
        return await self.play_history_repo.by_user(user_id, limit)


@dataclass
class QueryBookmarksUseCase:
    """Use case: Query bookmarks."""

    bookmark_repo: BookmarkRepository

    async def by_guild(
        self, guild_id: GuildId, limit: int = 10
    ) -> List[Bookmark]:
        """Query: Retrieve bookmarks for a guild."""
        return await self.bookmark_repo.by_guild(guild_id, limit)


@dataclass
class QueryAuditLogsUseCase:
    """Use case: Query audit log entries."""

    audit_log_repo: AuditLogRepository

    async def by_guild(
        self, guild_id: GuildId, limit: int = 20
    ) -> List[AuditLog]:
        """Query: Retrieve audit logs for a guild."""
        return await self.audit_log_repo.by_guild(guild_id, limit)

    async def by_event_type(
        self, event_type: EventType, limit: int = 20
    ) -> List[AuditLog]:
        """Query: Retrieve audit logs by event type."""
        return await self.audit_log_repo.by_event_type(event_type, limit)

    async def by_user(
        self, user_id: UserId, limit: int = 20
    ) -> List[AuditLog]:
        """Query: Retrieve audit logs for a user."""
        return await self.audit_log_repo.by_user(user_id, limit)
