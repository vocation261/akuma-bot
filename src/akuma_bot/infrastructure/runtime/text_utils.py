from __future__ import annotations

import re

COLOR_LIVE = 0xED4245
COLOR_PLAY = 0x57F287
COLOR_PAUSED = 0xFEE75C
COLOR_IDLE = 0x2F3136


def embed_color(is_live: bool, is_playing: bool, is_paused: bool) -> int:
    if is_live:
        return COLOR_LIVE
    if is_paused:
        return COLOR_PAUSED
    if is_playing:
        return COLOR_PLAY
    return COLOR_IDLE


def format_elapsed(value: int) -> str:
    value = max(0, int(value or 0))
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02}m {seconds:02}s"
    if minutes:
        return f"{minutes}m {seconds:02}s"
    return f"{seconds}s"


def validate_playable_url(url: str) -> tuple[bool, str]:
    text = str(url or "").strip()
    if not re.match(r"https?://", text, re.IGNORECASE):
        return False, "Invalid URL. Please provide a full https URL."
    lowered = text.lower()
    if "discord.com/channels/" in lowered or "discordapp.com/channels/" in lowered:
        return False, "That is a Discord message URL, not playable media."
    if not re.search(
        r"https?://(?:www\.)?(?:x|twitter)\.com/(?:i/spaces/[A-Za-z0-9]+|[A-Za-z0-9_]+/spaces/[A-Za-z0-9]+)",
        text,
        re.IGNORECASE,
    ):
        return False, "Only X Space URLs are supported."
    return True, ""


def extract_space_id(url: str) -> str:
    match = re.search(r"/spaces/([A-Za-z0-9]+)", str(url or ""))
    return match.group(1) if match else ""

