from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


@dataclass(slots=True)
class AppConfig:
    discord_token: str
    ytdlp_args: str
    stream_url_cache_ttl: int
    queue_playlist_max_items: int
    player_max_retries: int
    vc_channel_status_enabled: bool
    vc_channel_status_prefix: str
    history_db_path: str
    idle_disconnect_seconds: int
    sync_guild_id: int | None


def load_config() -> AppConfig:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required")
    sync_guild_raw = os.environ.get("SYNC_GUILD_ID", "").strip()
    sync_guild_id = int(sync_guild_raw) if sync_guild_raw.isdigit() else None
    return AppConfig(
        discord_token=token,
        ytdlp_args=os.environ.get("YTDLP_ARGS", "").strip(),
        stream_url_cache_ttl=_as_int(os.environ.get("STREAM_URL_CACHE_TTL"), 300),
        queue_playlist_max_items=_as_int(os.environ.get("QUEUE_PLAYLIST_MAX_ITEMS"), 100),
        player_max_retries=_as_int(os.environ.get("PLAYER_MAX_RETRIES"), 2),
        vc_channel_status_enabled=_as_bool(os.environ.get("VC_CHANNEL_STATUS_ENABLED"), True),
        vc_channel_status_prefix=os.environ.get("VC_CHANNEL_STATUS_PREFIX", "🎙️ Space: "),
        history_db_path=os.environ.get("HISTORY_DB_PATH", "data/history.db"),
        idle_disconnect_seconds=_as_int(os.environ.get("IDLE_DISCONNECT_SECONDS"), 60),
        sync_guild_id=sync_guild_id,
    )

