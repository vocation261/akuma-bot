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
                    "user_id INTEGER DEFAULT 0"
                    ")"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS bookmarks ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "ts REAL NOT NULL,"
                    "guild_id INTEGER NOT NULL,"
                    "channel_id INTEGER DEFAULT 0,"
                    "user_id INTEGER DEFAULT 0,"
                    "url TEXT NOT NULL,"
                    "title TEXT NOT NULL,"
                    "position_sec INTEGER DEFAULT 0,"
                    "note TEXT NOT NULL"
                    ")"
                )
                cursor.execute("PRAGMA table_info(play_history)")
                columns = [row[1] for row in cursor.fetchall()]
                if "user_id" not in columns:
                    cursor.execute("ALTER TABLE play_history ADD COLUMN user_id INTEGER DEFAULT 0")
                connection.commit()
            finally:
                connection.close()

    def log(self, source: str, url: str, status: str, message: str, guild_id: int = 0, channel_id: int = 0, user_id: int = 0) -> None:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO play_history (ts, source, url, status, message, guild_id, channel_id, user_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        float(time.time()),
                        str(source or "unknown"),
                        str(url or ""),
                        str(status or "unknown"),
                        str(message or "")[:800],
                        int(guild_id or 0),
                        int(channel_id or 0),
                        int(user_id or 0),
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
                query = "SELECT ts, source, url, status, message, guild_id, channel_id, user_id FROM play_history"
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
            writer.writerow(["ts", "source", "url", "status", "message", "guild_id", "channel_id", "user_id"])
            writer.writerows(rows)
        return len(rows)

    def add_bookmark(self, guild_id: int, channel_id: int, user_id: int, url: str, title: str, position_sec: int, note: str = "") -> None:
        with self.lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO bookmarks (ts, guild_id, channel_id, user_id, url, title, position_sec, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        float(time.time()),
                        int(guild_id or 0),
                        int(channel_id or 0),
                        int(user_id or 0),
                        str(url or ""),
                        str(title or "")[:250],
                        int(position_sec or 0),
                        str(note or "")[:200],
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
                    "SELECT ts, channel_id, user_id, url, title, position_sec, note "
                    "FROM bookmarks WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
                    (int(guild_id or 0), max(1, int(limit or 10))),
                )
                return cursor.fetchall()
            finally:
                connection.close()

