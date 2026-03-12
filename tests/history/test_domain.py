"""Tests for History domain layer."""

import pytest
import time

from domain.history import (
    AuditLog,
    Bookmark,
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


class TestValueObjects:
    """Tests for value objects."""

    def test_user_info_valid(self) -> None:
        """User info should accept valid data."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        assert user.user_id == UserId(123)
        assert user.name == "alice"
        assert user.tag == "@alice"

    def test_user_info_invalid_id(self) -> None:
        """User info should reject zero ID."""
        with pytest.raises(ValueError):
            UserInfo(user_id=UserId(0), name="alice", tag="@alice")

    def test_user_info_invalid_name_length(self) -> None:
        """User info should truncate long names."""
        with pytest.raises(ValueError):
            UserInfo(user_id=UserId(123), name="x" * 101, tag="@alice")

    def test_timestamp_valid(self) -> None:
        """Timestamp should accept valid values."""
        ts = Timestamp(1234567890.5)
        assert ts.unix_timestamp == 1234567890.5

    def test_timestamp_now(self) -> None:
        """Timestamp.now() should return recent timestamp."""
        before = time.time()
        ts = Timestamp.now()
        after = time.time()
        assert before <= ts.unix_timestamp <= after

    def test_timestamp_invalid(self) -> None:
        """Timestamp should reject negative values."""
        with pytest.raises(ValueError):
            Timestamp(-1.0)

    def test_play_source_valid(self) -> None:
        """PlaySource should accept valid types."""
        source = PlaySource("discord:live")
        assert source.source_type == "discord:live"

    def test_play_source_invalid(self) -> None:
        """PlaySource should reject invalid types."""
        with pytest.raises(ValueError):
            PlaySource("invalid_source")


class TestPlayHistory:
    """Tests for PlayHistory entity."""

    def test_create_valid(self) -> None:
        """PlayHistory should accept valid playback event."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        hist = PlayHistory(
            id=None,
            timestamp=ts,
            source=PlaySource("discord:live"),
            url="https://x.com/i/spaces/test",
            status=PlayStatus.OK,
            message="Playback started",
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user,
            event_type=EventType.PLAY_AUDIO,
        )

        assert hist.status == PlayStatus.OK
        assert hist.is_successful()

    def test_create_invalid_empty_url(self) -> None:
        """PlayHistory should reject empty URL."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        with pytest.raises(ValueError):
            PlayHistory(
                id=None,
                timestamp=ts,
                source=PlaySource("discord:live"),
                url="",
                status=PlayStatus.OK,
                message="Test",
                guild_id=GuildId(999),
                channel_id=ChannelId(888),
                user_info=user,
                event_type=EventType.PLAY_AUDIO,
            )

    def test_long_message(self) -> None:
        """PlayHistory should truncate long messages."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        with pytest.raises(ValueError):
            PlayHistory(
                id=None,
                timestamp=ts,
                source=PlaySource("discord:live"),
                url="https://x.com/i/spaces/test",
                status=PlayStatus.OK,
                message="x" * 801,
                guild_id=GuildId(999),
                channel_id=ChannelId(888),
                user_info=user,
                event_type=EventType.PLAY_AUDIO,
            )


class TestBookmark:
    """Tests for Bookmark entity."""

    def test_create_valid(self) -> None:
        """Bookmark should accept valid data."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        bookmark = Bookmark(
            id=None,
            timestamp=ts,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user,
            url="https://x.com/i/spaces/test",
            title="My Bookmark",
            position_seconds=3600,
            note="Test bookmark",
        )

        assert bookmark.title == "My Bookmark"
        assert bookmark.position_seconds == 3600
        assert bookmark.is_valid_position()

    def test_negative_position(self) -> None:
        """Bookmark should reject negative position."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        with pytest.raises(ValueError):
            Bookmark(
                id=None,
                timestamp=ts,
                guild_id=GuildId(999),
                channel_id=ChannelId(888),
                user_info=user,
                url="https://x.com/i/spaces/test",
                title="Test",
                position_seconds=-1,
                note="",
            )

    def test_future_position_valid(self) -> None:
        """Bookmark position up to 365 days should be valid."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        bookmark = Bookmark(
            id=None,
            timestamp=ts,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user,
            url="https://x.com/i/spaces/test",
            title="Test",
            position_seconds=86400 * 365,
            note="",
        )

        assert bookmark.is_valid_position()


class TestAuditLog:
    """Tests for AuditLog entity."""

    def test_create_valid(self) -> None:
        """AuditLog should accept valid administrative event."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        log = AuditLog(
            id=None,
            timestamp=ts,
            event_type=EventType.BOOKMARK_ADD,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user,
            resource=ResourceReference(resource_id="", resource_name="My Bookmark"),
            details="Test audit",
        )

        assert log.event_type == EventType.BOOKMARK_ADD
        assert log.involves_user(UserId(123))

    def test_invalid_event_type(self) -> None:
        """AuditLog should reject play_audio event type."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        with pytest.raises(ValueError):
            AuditLog(
                id=None,
                timestamp=ts,
                event_type=EventType.PLAY_AUDIO,
                guild_id=GuildId(999),
                channel_id=ChannelId(888),
                user_info=user,
                resource=None,
                details="Test",
            )

    def test_is_about_resource(self) -> None:
        """AuditLog should identify resource references."""
        user = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp(1234567890.0)

        log = AuditLog(
            id=None,
            timestamp=ts,
            event_type=EventType.BOOKMARK_DELETE,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user,
            resource=ResourceReference(resource_id="42", resource_name=""),
            details="Deleted",
        )

        assert log.is_about_resource("42")
        assert not log.is_about_resource("99")
