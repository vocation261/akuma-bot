"""Infrastructure layer: SQLite implementation for History repositories."""

import asyncio
import csv
import os
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from akuma_bot.domain.history import (
    AuditLog,
    AuditLogId,
    Bookmark,
    BookmarkId,
    ChannelId,
    EventType,
    GuildId,
    PlayHistory,
    PlayHistoryId,
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


class SqliteHistoryDb:
    """Low-level SQLite database access for history tables."""

    def __init__(self, db_path: str):
        """Initialize database connection."""
        self.db_path = os.path.abspath(db_path)
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.cursor()
                self._create_tables(cursor)
                self._migrate_columns(cursor)
                conn.commit()
            finally:
                conn.close()

    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create all required tables."""
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                guild_id INTEGER DEFAULT 0,
                channel_id INTEGER DEFAULT 0,
                user_id INTEGER DEFAULT 0,
                user_name TEXT DEFAULT '',
                user_tag TEXT DEFAULT '',
                event_type TEXT DEFAULT 'play_audio'
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER DEFAULT 0,
                user_id INTEGER DEFAULT 0,
                user_name TEXT DEFAULT '',
                user_tag TEXT DEFAULT '',
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                position_sec INTEGER DEFAULT 0,
                note TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                event_type TEXT NOT NULL,
                guild_id INTEGER DEFAULT 0,
                channel_id INTEGER DEFAULT 0,
                user_id INTEGER DEFAULT 0,
                user_name TEXT DEFAULT '',
                user_tag TEXT DEFAULT '',
                resource_id TEXT DEFAULT '',
                resource_name TEXT DEFAULT '',
                details TEXT DEFAULT ''
            )
            """
        )

    def _migrate_columns(self, cursor: sqlite3.Cursor) -> None:
        """Add missing columns to existing tables."""
        cursor.execute("PRAGMA table_info(play_history)")
        columns = [row[1] for row in cursor.fetchall()]

        if "user_name" not in columns:
            cursor.execute(
                "ALTER TABLE play_history ADD COLUMN user_name TEXT DEFAULT ''"
            )
        if "user_tag" not in columns:
            cursor.execute(
                "ALTER TABLE play_history ADD COLUMN user_tag TEXT DEFAULT ''"
            )
        if "event_type" not in columns:
            cursor.execute(
                "ALTER TABLE play_history ADD COLUMN event_type TEXT DEFAULT 'play_audio'"
            )

        cursor.execute("PRAGMA table_info(bookmarks)")
        columns = [row[1] for row in cursor.fetchall()]

        if "user_name" not in columns:
            cursor.execute(
                "ALTER TABLE bookmarks ADD COLUMN user_name TEXT DEFAULT ''"
            )
        if "user_tag" not in columns:
            cursor.execute(
                "ALTER TABLE bookmarks ADD COLUMN user_tag TEXT DEFAULT ''"
            )

    def execute_and_get_id(self, query: str, params: tuple) -> int:
        """Execute INSERT and return last row ID."""
        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                conn.close()

    def execute_query(
        self,
        query: str,
        params: tuple,
    ) -> List[tuple]:
        """Execute SELECT query and return results."""
        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
            finally:
                conn.close()

    def execute_update(self, query: str, params: tuple) -> int:
        """Execute UPDATE/DELETE and return row count."""
        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()


class SqlitePlayHistoryRepository(PlayHistoryRepository):
    """SQLite implementation of PlayHistoryRepository."""

    def __init__(self, db: SqliteHistoryDb):
        """Initialize repository."""
        self.db = db

    async def save(self, play_history: PlayHistory) -> PlayHistoryId:
        """Save playback event."""
        query = """
            INSERT INTO play_history
            (ts, source, url, status, message, guild_id, channel_id, user_id, user_name, user_tag, event_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            play_history.timestamp.unix_timestamp,
            play_history.source.source_type,
            play_history.url,
            play_history.status.value,
            play_history.message,
            play_history.guild_id,
            play_history.channel_id,
            play_history.user_info.user_id,
            play_history.user_info.name,
            play_history.user_info.tag,
            play_history.event_type.value,
        )
        row_id = await asyncio.to_thread(self.db.execute_and_get_id, query, params)
        return PlayHistoryId(row_id)

    async def by_guild(
        self, guild_id: GuildId, limit: int = 10
    ) -> List[PlayHistory]:
        """Retrieve playback events for a guild."""
        query = """
            SELECT ts, source, url, status, message, guild_id, channel_id, user_id, user_name, user_tag, event_type
            FROM play_history
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (guild_id, limit)
        )
        return [self._row_to_entity(row) for row in rows]

    async def by_user(
        self, user_id: UserId, limit: int = 10
    ) -> List[PlayHistory]:
        """Retrieve playback events for a user."""
        query = """
            SELECT ts, source, url, status, message, guild_id, channel_id, user_id, user_name, user_tag, event_type
            FROM play_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (user_id, limit)
        )
        return [self._row_to_entity(row) for row in rows]

    @staticmethod
    def _row_to_entity(row: tuple) -> PlayHistory:
        """Convert database row to domain entity."""
        (
            ts,
            source,
            url,
            status,
            message,
            guild_id,
            channel_id,
            user_id,
            user_name,
            user_tag,
            event_type,
        ) = row

        return PlayHistory(
            id=None,  # ID not returned in query
            timestamp=Timestamp(ts),
            source=PlaySource(source),
            url=url,
            status=PlayStatus(status),
            message=message,
            guild_id=GuildId(guild_id),
            channel_id=ChannelId(channel_id),
            user_info=UserInfo(
                user_id=UserId(user_id),
                name=user_name,
                tag=user_tag,
            ),
            event_type=EventType(event_type),
        )


class SqliteBookmarkRepository(BookmarkRepository):
    """SQLite implementation of BookmarkRepository."""

    def __init__(self, db: SqliteHistoryDb):
        """Initialize repository."""
        self.db = db

    async def save(self, bookmark: Bookmark) -> BookmarkId:
        """Save a bookmark."""
        query = """
            INSERT INTO bookmarks
            (ts, guild_id, channel_id, user_id, user_name, user_tag, url, title, position_sec, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            bookmark.timestamp.unix_timestamp,
            bookmark.guild_id,
            bookmark.channel_id,
            bookmark.user_info.user_id,
            bookmark.user_info.name,
            bookmark.user_info.tag,
            bookmark.url,
            bookmark.title,
            bookmark.position_seconds,
            bookmark.note,
        )
        row_id = await asyncio.to_thread(self.db.execute_and_get_id, query, params)
        return BookmarkId(row_id)

    async def by_id(self, bookmark_id: BookmarkId) -> Optional[Bookmark]:
        """Retrieve a bookmark by ID."""
        query = """
            SELECT id, ts, guild_id, channel_id, user_id, user_name, user_tag, url, title, position_sec, note
            FROM bookmarks
            WHERE id = ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (bookmark_id,)
        )
        if not rows:
            return None
        return self._row_to_entity(rows[0])

    async def by_guild(
        self, guild_id: GuildId, limit: int = 10
    ) -> List[Bookmark]:
        """Retrieve bookmarks for a guild."""
        query = """
            SELECT id, ts, guild_id, channel_id, user_id, user_name, user_tag, url, title, position_sec, note
            FROM bookmarks
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (guild_id, limit)
        )
        return [self._row_to_entity(row) for row in rows]

    async def delete(self, bookmark_id: BookmarkId) -> bool:
        """Delete a bookmark."""
        query = "DELETE FROM bookmarks WHERE id = ?"
        rowcount = await asyncio.to_thread(
            self.db.execute_update, query, (bookmark_id,)
        )
        return rowcount > 0

    async def delete_all_for_guild(self, guild_id: GuildId) -> int:
        """Delete all bookmarks for a guild."""
        query = "DELETE FROM bookmarks WHERE guild_id = ?"
        rowcount = await asyncio.to_thread(
            self.db.execute_update, query, (guild_id,)
        )
        return rowcount

    @staticmethod
    def _row_to_entity(row: tuple) -> Bookmark:
        """Convert database row to domain entity."""
        (
            id_val,
            ts,
            guild_id,
            channel_id,
            user_id,
            user_name,
            user_tag,
            url,
            title,
            position_sec,
            note,
        ) = row

        return Bookmark(
            id=BookmarkId(id_val),
            timestamp=Timestamp(ts),
            guild_id=GuildId(guild_id),
            channel_id=ChannelId(channel_id),
            user_info=UserInfo(
                user_id=UserId(user_id),
                name=user_name,
                tag=user_tag,
            ),
            url=url,
            title=title,
            position_seconds=position_sec,
            note=note,
        )


class SqliteAuditLogRepository(AuditLogRepository):
    """SQLite implementation of AuditLogRepository."""

    def __init__(self, db: SqliteHistoryDb):
        """Initialize repository."""
        self.db = db

    async def save(self, audit_log: AuditLog) -> AuditLogId:
        """Save an audit log entry."""
        query = """
            INSERT INTO audit_log
            (ts, event_type, guild_id, channel_id, user_id, user_name, user_tag, resource_id, resource_name, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            audit_log.timestamp.unix_timestamp,
            audit_log.event_type.value,
            audit_log.guild_id,
            audit_log.channel_id,
            audit_log.user_info.user_id,
            audit_log.user_info.name,
            audit_log.user_info.tag,
            audit_log.resource.resource_id if audit_log.resource else "",
            audit_log.resource.resource_name if audit_log.resource else "",
            audit_log.details,
        )
        row_id = await asyncio.to_thread(self.db.execute_and_get_id, query, params)
        return AuditLogId(row_id)

    async def by_guild(
        self, guild_id: GuildId, limit: int = 20
    ) -> List[AuditLog]:
        """Retrieve audit logs for a guild."""
        query = """
            SELECT id, ts, event_type, guild_id, channel_id, user_id, user_name, user_tag, resource_id, resource_name, details
            FROM audit_log
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (guild_id, limit)
        )
        return [self._row_to_entity(row) for row in rows]

    async def by_event_type(
        self, event_type: EventType, limit: int = 20
    ) -> List[AuditLog]:
        """Retrieve audit logs by event type."""
        query = """
            SELECT id, ts, event_type, guild_id, channel_id, user_id, user_name, user_tag, resource_id, resource_name, details
            FROM audit_log
            WHERE event_type = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (event_type.value, limit)
        )
        return [self._row_to_entity(row) for row in rows]

    async def by_user(
        self, user_id: UserId, limit: int = 20
    ) -> List[AuditLog]:
        """Retrieve audit logs for a user."""
        query = """
            SELECT id, ts, event_type, guild_id, channel_id, user_id, user_name, user_tag, resource_id, resource_name, details
            FROM audit_log
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (user_id, limit)
        )
        return [self._row_to_entity(row) for row in rows]

    @staticmethod
    def _row_to_entity(row: tuple) -> AuditLog:
        """Convert database row to domain entity."""
        (
            id_val,
            ts,
            event_type,
            guild_id,
            channel_id,
            user_id,
            user_name,
            user_tag,
            resource_id,
            resource_name,
            details,
        ) = row

        resource = None
        if resource_id or resource_name:
            resource = ResourceReference(
                resource_id=resource_id,
                resource_name=resource_name,
            )

        return AuditLog(
            id=AuditLogId(id_val),
            timestamp=Timestamp(ts),
            event_type=EventType(event_type),
            guild_id=GuildId(guild_id),
            channel_id=ChannelId(channel_id),
            user_info=UserInfo(
                user_id=UserId(user_id),
                name=user_name,
                tag=user_tag,
            ),
            resource=resource,
            details=details,
        )


class SqliteHistoryExporter(HistoryExporter):
    """SQLite implementation of HistoryExporter."""

    def __init__(self, db: SqliteHistoryDb):
        """Initialize exporter."""
        self.db = db

    async def export_to_csv(
        self,
        guild_id: GuildId,
        output_path: str,
        max_rows: int = 1000,
    ) -> int:
        """Export playback history to CSV file."""
        query = """
            SELECT ts, source, url, status, message, guild_id, channel_id, user_id, user_name, user_tag, event_type
            FROM play_history
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            self.db.execute_query, query, (guild_id, max_rows)
        )

        resolved_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)

        with open(resolved_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "ts",
                    "source",
                    "url",
                    "status",
                    "message",
                    "guild_id",
                    "channel_id",
                    "user_id",
                    "user_name",
                    "user_tag",
                    "event_type",
                ]
            )
            writer.writerows(rows)

        return len(rows)
