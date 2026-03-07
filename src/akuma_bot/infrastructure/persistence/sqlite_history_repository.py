from __future__ import annotations

import csv
import os
import sqlite3
import threading
import time


class SqliteHistoryRepository:
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS play_history ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "ts REAL NOT NULL,"
                    "source TEXT NOT NULL,"
                    "url TEXT NOT NULL,"
                    "status TEXT NOT NULL,"
                    "message TEXT NOT NULL,"
                    "guild_id INTEGER DEFAULT 0,"
                    "channel_id INTEGER DEFAULT 0,"
                    "user_id INTEGER DEFAULT 0,"
                    "user_name TEXT DEFAULT '',"
                    "user_tag TEXT DEFAULT '',"
                    "event_type TEXT DEFAULT 'play'"
                    ")"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS bookmarks ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "ts REAL NOT NULL,"
                    "guild_id INTEGER NOT NULL,"
                    "channel_id INTEGER DEFAULT 0,"
                    "user_id INTEGER DEFAULT 0,"
                    "user_name TEXT DEFAULT '',"
                    "user_tag TEXT DEFAULT '',"
                    "url TEXT NOT NULL,"
                    "title TEXT NOT NULL,"
                    "position_sec INTEGER DEFAULT 0,"
                    "note TEXT NOT NULL"
                    ")"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS audit_log ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "ts REAL NOT NULL,"
                    "event_type TEXT NOT NULL,"
                    "guild_id INTEGER DEFAULT 0,"
                    "channel_id INTEGER DEFAULT 0,"
                    "user_id INTEGER DEFAULT 0,"
                    "user_name TEXT DEFAULT '',"
                    "user_tag TEXT DEFAULT '',"
                    "resource_id TEXT DEFAULT '',"
                    "resource_name TEXT DEFAULT '',"
                    "details TEXT DEFAULT ''"
                    ")"
                )
                # Migrate existing columns if they don't exist
                cursor.execute("PRAGMA table_info(play_history)")
                columns = [row[1] for row in cursor.fetchall()]
                if "user_name" not in columns:
                    cursor.execute("ALTER TABLE play_history ADD COLUMN user_name TEXT DEFAULT ''")
                if "user_tag" not in columns:
                    cursor.execute("ALTER TABLE play_history ADD COLUMN user_tag TEXT DEFAULT ''")
                if "event_type" not in columns:
                    cursor.execute("ALTER TABLE play_history ADD COLUMN event_type TEXT DEFAULT 'play'")
                
                # Migrate bookmarks columns
                cursor.execute("PRAGMA table_info(bookmarks)")
                columns = [row[1] for row in cursor.fetchall()]
                if "user_name" not in columns:
                    cursor.execute("ALTER TABLE bookmarks ADD COLUMN user_name TEXT DEFAULT ''")
                if "user_tag" not in columns:
                    cursor.execute("ALTER TABLE bookmarks ADD COLUMN user_tag TEXT DEFAULT ''")
                
                connection.commit()
            finally:
                connection.close()

    def log(self, source: str, url: str, status: str, message: str, guild_id: int = 0, channel_id: int = 0, user_id: int = 0, user_name: str = "", user_tag: str = "", event_type: str = "play") -> None:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO play_history (ts, source, url, status, message, guild_id, channel_id, user_id, user_name, user_tag, event_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        float(time.time()),
                        str(source or "unknown"),
                        str(url or ""),
                        str(status or "unknown"),
                        str(message or "")[:800],
                        int(guild_id or 0),
                        int(channel_id or 0),
                        int(user_id or 0),
                        str(user_name or "")[:100],
                        str(user_tag or "")[:100],
                        str(event_type or "play")[:50],
                    ),
                )
                connection.commit()
            finally:
                connection.close()

    def latest(self, limit: int = 10, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None) -> list[tuple]:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                where = []
                values: list[int] = []
                if guild_id is not None:
                    where.append("guild_id = ?")
                    values.append(int(guild_id or 0))
                if channel_id is not None:
                    where.append("channel_id = ?")
                    values.append(int(channel_id or 0))
                if user_id is not None:
                    where.append("user_id = ?")
                    values.append(int(user_id or 0))
                query = "SELECT ts, source, url, status, message, guild_id, channel_id, user_id, user_name, user_tag, event_type FROM play_history"
                if where:
                    query += " WHERE " + " AND ".join(where)
                query += " ORDER BY id DESC LIMIT ?"
                values.append(max(1, int(limit or 10)))
                cursor.execute(query, tuple(values))
                return cursor.fetchall()
            finally:
                connection.close()

    def export_csv(self, output_path: str, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None, limit: int = 1000) -> int:
        rows = self.latest(limit=limit, guild_id=guild_id, channel_id=channel_id, user_id=user_id)
        resolved = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts", "source", "url", "status", "message", "guild_id", "channel_id", "user_id", "user_name", "user_tag", "event_type"])
            writer.writerows(rows)
        return len(rows)

    def add_bookmark(self, guild_id: int, channel_id: int, user_id: int, url: str, title: str, position_sec: int, note: str = "", user_name: str = "", user_tag: str = "") -> None:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO bookmarks (ts, guild_id, channel_id, user_id, url, title, position_sec, note, user_name, user_tag) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        float(time.time()),
                        int(guild_id or 0),
                        int(channel_id or 0),
                        int(user_id or 0),
                        str(url or ""),
                        str(title or "")[:250],
                        int(position_sec or 0),
                        str(note or "")[:200],
                        str(user_name or "")[:100],
                        str(user_tag or "")[:100],
                    ),
                )
                connection.commit()
            finally:
                connection.close()

    def latest_bookmarks(self, guild_id: int, limit: int = 10) -> list[tuple]:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT id, ts, channel_id, user_id, url, title, position_sec, note, user_name, user_tag "
                    "FROM bookmarks WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
                    (int(guild_id or 0), max(1, int(limit or 10))),
                )
                return cursor.fetchall()
            finally:
                connection.close()

    def delete_bookmark(self, guild_id: int, bookmark_id: int) -> bool:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "DELETE FROM bookmarks WHERE guild_id = ? AND id = ?",
                    (int(guild_id or 0), int(bookmark_id or 0)),
                )
                connection.commit()
                return cursor.rowcount > 0
            finally:
                connection.close()

    def clear_bookmarks(self, guild_id: int) -> int:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "DELETE FROM bookmarks WHERE guild_id = ?",
                    (int(guild_id or 0),),
                )
                connection.commit()
                return int(cursor.rowcount or 0)
            finally:
                connection.close()

    def log_audit_event(
        self,
        event_type: str,
        guild_id: int = 0,
        channel_id: int = 0,
        user_id: int = 0,
        user_name: str = "",
        user_tag: str = "",
        resource_id: str = "",
        resource_name: str = "",
        details: str = "",
    ) -> None:
        """Log an audit event (bookmark add/delete, alert add/delete, etc.)"""
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO audit_log (ts, event_type, guild_id, channel_id, user_id, user_name, user_tag, resource_id, resource_name, details) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        float(time.time()),
                        str(event_type or "unknown")[:50],
                        int(guild_id or 0),
                        int(channel_id or 0),
                        int(user_id or 0),
                        str(user_name or "")[:100],
                        str(user_tag or "")[:100],
                        str(resource_id or "")[:200],
                        str(resource_name or "")[:200],
                        str(details or "")[:500],
                    ),
                )
                connection.commit()
            finally:
                connection.close()

    def latest_audit_events(self, guild_id: int | None = None, event_type: str | None = None, limit: int = 20) -> list[tuple]:
        """Retrieve audit log entries"""
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                where = []
                values: list = []
                if guild_id is not None:
                    where.append("guild_id = ?")
                    values.append(int(guild_id or 0))
                if event_type is not None:
                    where.append("event_type = ?")
                    values.append(str(event_type))
                query = "SELECT id, ts, event_type, guild_id, channel_id, user_id, user_name, user_tag, resource_id, resource_name, details FROM audit_log"
                if where:
                    query += " WHERE " + " AND ".join(where)
                query += " ORDER BY id DESC LIMIT ?"
                values.append(max(1, int(limit or 20)))
                cursor.execute(query, tuple(values))
                return cursor.fetchall()
            finally:
                connection.close()

