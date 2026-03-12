"""Tests for History application use cases."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from application.history import (
    AddBookmarkUseCase,
    LogPlaybackUseCase,
    QueryPlayHistoryUseCase,
)
from domain.history import (
    Bookmark,
    BookmarkId,
    ChannelId,
    EventType,
    GuildId,
    PlayHistory,
    PlaySource,
    PlayStatus,
    Timestamp,
    UserId,
)


class TestLogPlaybackUseCase:
    """Tests for logging playback events."""

    @pytest.mark.asyncio
    async def test_log_successful_playback(self) -> None:
        """Use case should record successful playback."""
        # Arrange
        mock_play_repo = AsyncMock()
        mock_audit_repo = AsyncMock()
        use_case = LogPlaybackUseCase(mock_play_repo, mock_audit_repo)

        ts = Timestamp.now()

        # Act
        await use_case.execute(
            timestamp=ts,
            source=PlaySource("discord:live"),
            url="https://x.com/i/spaces/test",
            status=PlayStatus.OK,
            message="Started",
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_id=UserId(123),
            user_name="alice",
            user_tag="@alice",
        )

        # Assert
        assert mock_play_repo.save.called
        captured_event = mock_play_repo.save.call_args[0][0]
        assert isinstance(captured_event, PlayHistory)
        assert captured_event.status == PlayStatus.OK
        assert captured_event.is_successful()


class TestAddBookmarkUseCase:
    """Tests for adding bookmarks."""

    @pytest.mark.asyncio
    async def test_add_bookmark(self) -> None:
        """Use case should create bookmark and audit log."""
        # Arrange
        mock_bookmark_repo = AsyncMock()
        mock_audit_repo = AsyncMock()
        mock_bookmark_repo.save.return_value = BookmarkId(1)

        use_case = AddBookmarkUseCase(mock_bookmark_repo, mock_audit_repo)

        ts = Timestamp.now()

        # Act
        result = await use_case.execute(
            timestamp=ts,
            guild_id=GuildId(999),
            channel_id=ChannelId(888),
            user_id=UserId(123),
            user_name="alice",
            user_tag="@alice",
            url="https://x.com/i/spaces/test",
            title="My Bookmark",
            position_seconds=3600,
            note="Test",
        )

        # Assert
        assert result == BookmarkId(1)
        assert mock_bookmark_repo.save.called
        assert mock_audit_repo.save.called

        # Verify bookmark was created
        bookmark = mock_bookmark_repo.save.call_args[0][0]
        assert isinstance(bookmark, Bookmark)
        assert bookmark.title == "My Bookmark"

        # Verify audit was created
        audit = mock_audit_repo.save.call_args[0][0]
        assert audit.event_type == EventType.BOOKMARK_ADD


class TestQueryPlayHistoryUseCase:
    """Tests for querying playback history."""

    @pytest.mark.asyncio
    async def test_query_by_guild(self) -> None:
        """Use case should retrieve history for a guild."""
        # Arrange
        mock_repo = AsyncMock()
        mock_repo.by_guild.return_value = []

        use_case = QueryPlayHistoryUseCase(mock_repo)

        # Act
        result = await use_case.by_guild(GuildId(999), limit=5)

        # Assert
        assert result == []
        mock_repo.by_guild.assert_called_once_with(GuildId(999), 5)

    @pytest.mark.asyncio
    async def test_query_by_user(self) -> None:
        """Use case should retrieve history for a user."""
        # Arrange
        mock_repo = AsyncMock()
        mock_repo.by_user.return_value = []

        use_case = QueryPlayHistoryUseCase(mock_repo)

        # Act
        result = await use_case.by_user(UserId(123), limit=10)

        # Assert
        assert result == []
        mock_repo.by_user.assert_called_once_with(UserId(123), 10)
