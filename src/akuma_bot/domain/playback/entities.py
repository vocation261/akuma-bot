from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackSessionState:
    guild_id: int
    is_live: bool
    is_playing: bool
    is_paused: bool
    queue_size: int
