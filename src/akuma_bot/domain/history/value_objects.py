"""Value objects for the History bounded context."""

from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import NewType


class PlayStatus(str, Enum):
    """Enumeration for playback status."""

    OK = "ok"
    ERROR = "error"
    PENDING = "pending"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    """Enumeration for event types."""

    PLAY_AUDIO = "play_audio"
    BOOKMARK_ADD = "bookmark_add"
    BOOKMARK_DELETE = "bookmark_delete"
    BOOKMARK_CLEAR = "bookmark_clear"
    ALERT_ADD = "alert_add"
    ALERT_REMOVE = "alert_remove"


# Strongly typed IDs as value objects
UserId = NewType("UserId", int)
ChannelId = NewType("ChannelId", int)
GuildId = NewType("GuildId", int)
BookmarkId = NewType("BookmarkId", int)
AuditLogId = NewType("AuditLogId", int)


@dataclass(frozen=True)
class UserInfo:
    """Immutable value object representing user information."""

    user_id: UserId
    name: str
    tag: str

    def __post_init__(self) -> None:
        """Validate user info."""
        if not self.user_id:
            raise ValueError("user_id must not be empty")
        if len(self.name) > 100:
            raise ValueError("user name must not exceed 100 characters")
        if len(self.tag) > 100:
            raise ValueError("user tag must not exceed 100 characters")


@dataclass(frozen=True)
class Timestamp:
    """Immutable value object representing a precise moment in time."""

    unix_timestamp: float

    def __post_init__(self) -> None:
        """Validate timestamp."""
        if self.unix_timestamp < 0:
            raise ValueError("timestamp must be non-negative")

    def as_datetime(self) -> datetime:
        """Convert to datetime object."""
        return datetime.fromtimestamp(self.unix_timestamp)

    @classmethod
    def now(cls) -> "Timestamp":
        """Create timestamp for current moment."""
        import time
        return cls(float(time.time()))


@dataclass(frozen=True)
class PlaySource:
    """Immutable value object representing where playback came from."""

    source_type: str  # e.g., "discord:live", "discord:rec"

    def __post_init__(self) -> None:
        """Validate source."""
        valid_types = {"discord:live", "discord:rec"}
        if self.source_type not in valid_types:
            raise ValueError(f"source_type must be one of {valid_types}")


@dataclass(frozen=True)
class ResourceReference:
    """Immutable value object for referencing a resource in audit logs."""

    resource_id: str
    resource_name: str

    def __post_init__(self) -> None:
        """Validate resource reference."""
        if len(self.resource_id) > 200:
            raise ValueError("resource_id must not exceed 200 characters")
        if len(self.resource_name) > 200:
            raise ValueError("resource_name must not exceed 200 characters")
