from __future__ import annotations

import asyncio
import time

from akuma_bot.domain.entities.guild_session import GuildSession


class SessionStore:
    def __init__(self):
        self.guilds: dict[int, GuildSession] = {}
        self.lock = asyncio.Lock()
        self.stream_url_cache: dict[str, dict] = {}
        self.panel_messages: dict[str, int] = {}
        self.panel_signatures: dict[str, tuple] = {}
        self.play_locks: dict[int, asyncio.Lock] = {}
        self.seek_locks: dict[int, asyncio.Lock] = {}

    def guild(self, guild_id: int) -> GuildSession:
        if guild_id not in self.guilds:
            self.guilds[guild_id] = GuildSession(guild_id=guild_id)
        return self.guilds[guild_id]

    def play_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self.play_locks:
            self.play_locks[guild_id] = asyncio.Lock()
        return self.play_locks[guild_id]

    def seek_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self.seek_locks:
            self.seek_locks[guild_id] = asyncio.Lock()
        return self.seek_locks[guild_id]

    def get_cached_stream(self, url: str, ttl: int = 300) -> str:
        item = self.stream_url_cache.get(url)
        if isinstance(item, dict):
            if (time.time() - float(item.get("ts", 0))) <= ttl:
                return str(item.get("stream_url") or "")
        return ""

    def set_cached_stream(self, url: str, stream_url: str, max_items: int = 300) -> None:
        self.stream_url_cache[url] = {"stream_url": stream_url, "ts": time.time()}
        if len(self.stream_url_cache) > max_items:
            oldest = sorted(self.stream_url_cache, key=lambda key: float((self.stream_url_cache[key] or {}).get("ts", 0)))
            for key in oldest[: len(self.stream_url_cache) - max_items]:
                self.stream_url_cache.pop(key, None)

