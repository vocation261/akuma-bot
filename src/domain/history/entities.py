"""Domain entities for the History bounded context."""

from dataclasses import dataclass, field
from typing import Optional, NewType

from .value_objects import (
    ChannelId,
    EventType,
    GuildId,
    PlayStatus,
    PlaySource,
    ResourceReference,
    Timestamp,
    UserId,
    UserInfo,
)


# Entity IDs
PlayHistoryId = NewType("PlayHistoryId", int)
BookmarkId = NewType("BookmarkId", int)
AuditLogId = NewType("AuditLogId", int)


@dataclass
class PlayHistory:
    """
    Entity representing a single audio playback event.

    This aggregate root tracks when a user initiated playback,
    what they played, and the outcome.
    """

    id: Optional[PlayHistoryId]
    timestamp: Timestamp
    source: PlaySource
    url: str
    status: PlayStatus
    message: str
    guild_id: GuildId
    channel_id: ChannelId
    user_info: UserInfo
    event_type: EventType

    def __post_init__(self) -> None:
        """Validate playback event."""
        if not self.url:
            raise ValueError("url must not be empty")
        if len(self.url) > 2048:
            raise ValueError("url must not exceed 2048 characters")
        if len(self.message) > 800:
            raise ValueError("message must not exceed 800 characters")

    def is_successful(self) -> bool:
        """Check if playback was successful."""
        return self.status == PlayStatus.OK


@dataclass
class Bookmark:
    """
    Entity representing a saved position in a Space.

    This aggregate root tracks a user's marked position with
    optional title and notes.
    """

    id: Optional[BookmarkId]
    timestamp: Timestamp
    guild_id: GuildId
    channel_id: ChannelId
    user_info: UserInfo
    url: str
    title: str
    position_seconds: int
    note: str

    def __post_init__(self) -> None:
        """Validate bookmark."""
        if not self.url:
            raise ValueError("url must not be empty")
        if len(self.url) > 2048:
            raise ValueError("url must not exceed 2048 characters")
        if len(self.title) > 250:
            raise ValueError("title must not exceed 250 characters")
        if len(self.note) > 200:
            raise ValueError("note must not exceed 200 characters")
        if self.position_seconds < 0:
            raise ValueError("position_seconds must be non-negative")

    def is_valid_position(self) -> bool:
        """Verify that position is reasonable."""
        # Position should not be unreasonably far in the future
        # (more than 24 hours = 86400 seconds)
        return 0 <= self.position_seconds <= 86400 * 365


@dataclass
class AuditLog:
    """
    Entity representing a single audit event.

    This aggregate root records administrative actions like
    bookmark creation/deletion and alert management.
    """

    id: Optional[AuditLogId]
    timestamp: Timestamp
    event_type: EventType
    guild_id: GuildId
    channel_id: ChannelId
    user_info: UserInfo
    resource: Optional[ResourceReference]
    details: str

    def __post_init__(self) -> None:
        """Validate audit log entry."""
        # event_type should be administrative (not play_audio)
        allowed_types = {
            EventType.BOOKMARK_ADD,
            EventType.BOOKMARK_DELETE,
            EventType.BOOKMARK_CLEAR,
            EventType.ALERT_ADD,
            EventType.ALERT_REMOVE,
        }
        if self.event_type not in allowed_types:
            raise ValueError(f"event_type must be one of {allowed_types}")
        if len(self.details) > 500:
            raise ValueError("details must not exceed 500 characters")

    def involves_user(self, user_id: UserId) -> bool:
        """Check if this event involves a specific user."""
        return self.user_info.user_id == user_id

    def is_about_resource(self, resource_id: str) -> bool:
        """Check if this event concerns a specific resource."""
        return self.resource and self.resource.resource_id == resource_id
