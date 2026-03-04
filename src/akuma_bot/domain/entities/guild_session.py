from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from akuma_bot.domain.value_objects.queue_item import QueueItem


@dataclass
class GuildSession:
    guild_id: int = 0
    voice_client: Any = None
    current_url: str = ""
    current_stream_url: str = ""
    current_local_path: str = ""
    play_start_time: float | None = None
    elapsed_accumulated: float = 0.0
    is_live: bool = True
    volume: float = 1.0
    idle_since: float | None = None
    title: str = ""
    host: str = ""
    host_handle: str = ""
    host_image: str = ""
    listeners: int = 0
    participants: int = 0
    duration_str: str = ""
    duration_sec: int = 0
    status_label: str = ""
    owner_user_id: int = 0
    last_vc_channel_id: int = 0
    last_text_channel_id: int = 0
    last_play_url: str = ""
    last_play_mode: str = ""
    last_play_vc_channel_id: int = 0
    queue: list[QueueItem] = field(default_factory=list)
    suppress_after_events: int = 0
    play_retry_count: int = 0
    max_play_retries: int = 2
    restarting_track: bool = False
    active_ytdlp_args: str = ""
    active_stream_cache_ttl: int = 300
    original_channel_status: str | None = None
    channel_status_overridden: bool = False
    current_channel_status: str = ""
    channel_status_enabled: bool = True
    channel_status_prefix: str = "🎙️ Space: "
    channel_status_warning: str = ""
    alone_since: float | None = None

    def elapsed(self) -> int:
        if self.play_start_time is None:
            return max(0, int(self.elapsed_accumulated))
        return max(0, int(self.elapsed_accumulated + max(0.0, time.time() - self.play_start_time)))

    def reset(self) -> None:
        self.current_url = ""
        self.current_stream_url = ""
        self.current_local_path = ""
        self.play_start_time = None
        self.elapsed_accumulated = 0.0
        self.is_live = True
        self.idle_since = None
        self.title = ""
        self.host = ""
        self.host_handle = ""
        self.host_image = ""
        self.listeners = 0
        self.participants = 0
        self.duration_str = ""
        self.duration_sec = 0
        self.status_label = ""
        self.queue.clear()
        self.suppress_after_events = 0
        self.play_retry_count = 0
        self.max_play_retries = 2
        self.restarting_track = False
        self.active_ytdlp_args = ""
        self.active_stream_cache_ttl = 300
        self.original_channel_status = None
        self.channel_status_overridden = False
        self.current_channel_status = ""
        self.channel_status_warning = ""
        self.last_text_channel_id = 0
        self.alone_since = None
