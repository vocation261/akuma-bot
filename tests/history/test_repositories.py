"""Tests for SQLite history repository implementations."""

import pytest
import tempfile
import os
from pathlib import Path

from akuma_bot.domain.history import (
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
from akuma_bot.infrastructure.persistence.history_sqlite_repository import (
    SqliteAuditLogRepository,
    SqliteBookmarkRepository,
    SqliteHistoryDb,
    SqlitePlayHistoryRepository,
)


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test.db")


@pytest.fixture
def db(temp_db_path):
    """Create a test database."""
    return SqliteHistoryDb(temp_db_path)


class TestSqlitePlayHistoryRepository:
    """Tests for SQLite PlayHistory repository."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db) -> None:
        """Repository should save and retrieve playback events."""
        # Arrange
        repo = SqlitePlayHistoryRepository(db)
        user_info = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp.now()

        event = PlayHistory(
            id=None,
            timestamp=ts,
            source=PlaySource("discord:live"),
            url="https://x.com/i/spaces/test",
            status=PlayStatus.OK,
            message="Playback started",
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user_info,
            event_type=EventType.PLAY_AUDIO,
        )

        # Act
        event_id = await repo.save(event)
        events = await repo.by_guild(GuildId(999), limit=10)

        # Assert
        assert event_id is not None
        assert len(events) == 1
        assert events[0].url == "https://x.com/i/spaces/test"
        assert events[0].status == PlayStatus.OK

    @pytest.mark.asyncio
    async def test_retrieve_by_user(self, db) -> None:
        """Repository should retrieve events filtered by user."""
        # Arrange
        repo = SqlitePlayHistoryRepository(db)
        user1 = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        user2 = UserInfo(user_id=UserId(456), name="bob", tag="@bob")
        ts = Timestamp.now()

        event1 = PlayHistory(
            id=None,
            timestamp=ts,
            source=PlaySource("discord:live"),
            url="https://x.com/i/spaces/test1",
            status=PlayStatus.OK,
            message="Event 1",
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user1,
            event_type=EventType.PLAY_AUDIO,
        )

        event2 = PlayHistory(
            id=None,
            timestamp=ts,
            source=PlaySource("discord:rec"),
            url="https://x.com/i/spaces/test2",
            status=PlayStatus.OK,
            message="Event 2",
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user2,
            event_type=EventType.PLAY_AUDIO,
        )

        # Act
        await repo.save(event1)
        await repo.save(event2)

        alice_events = await repo.by_user(UserId(123), limit=10)
        bob_events = await repo.by_user(UserId(456), limit=10)

        # Assert
        assert len(alice_events) == 1
        assert len(bob_events) == 1
        assert alice_events[0].user_info.name == "alice"
        assert bob_events[0].user_info.name == "bob"


class TestSqliteBookmarkRepository:
    """Tests for SQLite Bookmark repository."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db) -> None:
        """Repository should save and retrieve bookmarks."""
        # Arrange
        repo = SqliteBookmarkRepository(db)
        user_info = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp.now()

        bookmark = Bookmark(
            id=None,
            timestamp=ts,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user_info,
            url="https://x.com/i/spaces/test",
            title="My Bookmark",
            position_seconds=3600,
            note="Test bookmark",
        )

        # Act
        bookmark_id = await repo.save(bookmark)
        retrieved = await repo.by_id(bookmark_id)
        guild_bookmarks = await repo.by_guild(GuildId(999), limit=10)

        # Assert
        assert retrieved is not None
        assert retrieved.title == "My Bookmark"
        assert retrieved.position_seconds == 3600
        assert len(guild_bookmarks) == 1

    @pytest.mark.asyncio
    async def test_delete_bookmark(self, db) -> None:
        """Repository should delete bookmarks."""
        # Arrange
        repo = SqliteBookmarkRepository(db)
        user_info = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp.now()

        bookmark = Bookmark(
            id=None,
            timestamp=ts,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user_info,
            url="https://x.com/i/spaces/test",
            title="Test",
            position_seconds=0,
            note="",
        )

        # Act
        bookmark_id = await repo.save(bookmark)
        deleted = await repo.delete(bookmark_id)
        remaining = await repo.by_guild(GuildId(999), limit=10)

        # Assert
        assert deleted is True
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_delete_all_for_guild(self, db) -> None:
        """Repository should delete all bookmarks for a guild."""
        # Arrange
        repo = SqliteBookmarkRepository(db)
        user_info = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp.now()

        # Create two bookmarks
        for i in range(2):
            bookmark = Bookmark(
                id=None,
                timestamp=ts,
                guild_id=GuildId(999),
                channel_id=ChannelId(888),
                user_info=user_info,
                url=f"https://x.com/i/spaces/test{i}",
                title=f"Bookmark {i}",
                position_seconds=0,
                note="",
            )
            await repo.save(bookmark)

        # Act
        deleted_count = await repo.delete_all_for_guild(GuildId(999))
        remaining = await repo.by_guild(GuildId(999), limit=10)

        # Assert
        assert deleted_count == 2
        assert len(remaining) == 0


class TestSqliteAuditLogRepository:
    """Tests for SQLite AuditLog repository."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db) -> None:
        """Repository should save and retrieve audit entries."""
        # Arrange
        from akuma_bot.domain.history import AuditLog

        repo = SqliteAuditLogRepository(db)
        user_info = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp.now()

        audit_entry = AuditLog(
            id=None,
            timestamp=ts,
            event_type=EventType.BOOKMARK_ADD,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_info=user_info,
            resource=ResourceReference(
                resource_id="",
                resource_name="My Bookmark",
            ),
            details="Test audit",
        )

        # Act
        entry_id = await repo.save(audit_entry)
        entries = await repo.by_guild(GuildId(999), limit=10)

        # Assert
        assert entry_id is not None
        assert len(entries) == 1
        assert entries[0].event_type == EventType.BOOKMARK_ADD

    @pytest.mark.asyncio
    async def test_retrieve_by_event_type(self, db) -> None:
        """Repository should retrieve entries by event type."""
        # Arrange
        from akuma_bot.domain.history import AuditLog

        repo = SqliteAuditLogRepository(db)
        user_info = UserInfo(user_id=UserId(123), name="alice", tag="@alice")
        ts = Timestamp.now()

        # Create two different event types
        for event_type in [EventType.BOOKMARK_ADD, EventType.BOOKMARK_DELETE]:
            audit_entry = AuditLog(
                id=None,
                timestamp=ts,
                event_type=event_type,
                guild_id=GuildId(999),
                channel_id=ChannelId(888),
                user_info=user_info,
                resource=None,
                details="Test",
            )
            await repo.save(audit_entry)

        # Act
        add_events = await repo.by_event_type(EventType.BOOKMARK_ADD, limit=10)
        delete_events = await repo.by_event_type(EventType.BOOKMARK_DELETE, limit=10)

        # Assert
        assert len(add_events) == 1
        assert len(delete_events) == 1
        assert add_events[0].event_type == EventType.BOOKMARK_ADD
        assert delete_events[0].event_type == EventType.BOOKMARK_DELETE
