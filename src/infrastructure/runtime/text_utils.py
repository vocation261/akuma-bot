from __future__ import annotations

import subprocess
import re
from pathlib import Path

COLOR_LIVE = 0xED4245
COLOR_PLAY = 0x57F287
COLOR_PAUSED = 0xFEE75C
COLOR_IDLE = 0x2F3136
X_SPACE_URL_RE = re.compile(r"https://(?:www\.)?x\.com/i/spaces/[A-Za-z0-9]+(?:[/?#].*)?", re.IGNORECASE)


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


def format_duration_hms(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds or 0))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}h {minutes}m {secs}s"


def validate_playable_url(url: str) -> tuple[bool, str]:
    text = str(url or "").strip()
    if not re.match(r"https://", text, re.IGNORECASE):
        return False, "Invalid URL. Please provide a full https URL."
    lowered = text.lower()
    if "discord.com/channels/" in lowered or "discordapp.com/channels/" in lowered:
        return False, "That is a Discord message URL, not playable media."
    if not is_x_space_url(text):
        return False, "Use URL format: https://x.com/i/spaces/<id>"
    return True, ""


def is_x_space_url(url: str) -> bool:
    return bool(X_SPACE_URL_RE.fullmatch(str(url or "").strip()))


def extract_space_id(url: str) -> str:
    """Extract Space ID from X/Twitter Space URL. Supports /spaces/ and /i/spaces/ patterns."""
    match = re.search(r"/(?:i/)?spaces/([A-Za-z0-9_-]+)", str(url or ""), re.IGNORECASE)
    return match.group(1) if match else ""


def extract_space_id_from_text(text: str | None) -> str:
    return extract_space_id(str(text or ""))


def safe_filename(text: str, max_len: int = 80, default: str = "untitled") -> str:
    """
    Create a safe filesystem path component from text.
    Removes or replaces invalid filename characters.
    """
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(text or "").strip())
    # Normalize whitespace and underscores
    cleaned = re.sub(r"[_\s]+", "_", cleaned)
    # Strip leading/trailing dots, underscores, and spaces
    cleaned = cleaned.strip("._").strip()
    if not cleaned:
        return default
    return cleaned[:max_len] if max_len > 0 else cleaned


def build_filename_from_display_label(display_label: str, max_len: int = 140) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(display_label or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "space-audio"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    return f"{cleaned}.mp3"


def chunk_text_for_discord(text: str, max_chars: int = 2000) -> list[str]:
    content = str(text or "")
    if not content:
        return [""]
    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        chunk = remaining[:cut]
        chunks.append(chunk)
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def probe_audio_duration_seconds(audio_path: Path, ffprobe_cmd: str = "ffprobe") -> int:
    try:
        cmd = [
            ffprobe_cmd,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        return max(0, int(float((result.stdout or "").strip() or 0)))
    except Exception:
        return 0

