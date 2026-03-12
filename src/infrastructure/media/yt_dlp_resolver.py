from __future__ import annotations

import json
import logging
import shlex
import subprocess
import time

from infrastructure.media.space_scraper import scrape_space_html
from infrastructure.runtime.text_utils import is_x_space_url

logger = logging.getLogger("akuma_bot")


class YtDlpResolver:
    def get_media_info(self, url: str, extra_args: str = "") -> dict:
        extra = shlex.split(extra_args) if extra_args else []
        try:
            result = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-warnings", "--quiet", *extra, url],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip().splitlines()[0])
                return {
                    "id": str(data.get("id") or "").strip(),
                    "title": str(data.get("title") or "").strip(),
                    "uploader": str(data.get("uploader") or data.get("channel") or "").strip(),
                    "uploader_id": str(data.get("uploader_id") or data.get("channel_id") or "").strip(),
                    "thumbnail": str(data.get("thumbnail") or "").strip(),
                    "description": str(data.get("description") or "").strip(),
                    "duration": int(data.get("duration") or 0),
                    "language": data.get("language") or "?",
                    "live": bool(data.get("is_live", False)),
                    "timestamp": data.get("timestamp") or 0,
                    "viewcount": data.get("concurrent_view_count") or data.get("view_count") or 0,
                }
        except Exception as exc:
            logger.debug("get_media_info failed for %s: %s", url, exc)
        return {"title": "", "uploader": "", "duration": 0, "language": "?", "live": False, "viewcount": 0}

    def get_stream_url(self, url: str, retries: int = 3, extra_args: str = "") -> str:
        extra = shlex.split(extra_args) if extra_args else []
        format_candidates = ["bestaudio[ext=m4a]/bestaudio/best", "bestaudio/best", "best"]
        for attempt in range(1, retries + 1):
            try:
                for fmt in format_candidates:
                    result = subprocess.run(
                        ["yt-dlp", "-g", "-f", fmt, "--no-warnings", "--quiet", *extra, url],
                        capture_output=True,
                        text=True,
                        timeout=35,
                    )
                    if result.returncode == 0:
                        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                        if lines:
                            return lines[0]
            except Exception as exc:
                logger.debug("get_stream_url failed at attempt %s: %s", attempt, exc)
            if attempt < retries:
                time.sleep(2 * attempt)
        return ""

    def is_space_url(self, url: str) -> bool:
        return is_x_space_url(url)

    def resolve_live_status(self, info: dict, source_is_space: bool) -> tuple[bool, str]:
        live_flag = info.get("live")
        if isinstance(live_flag, bool):
            return live_flag, "live" if live_flag else "ended"
        if source_is_space:
            duration = int(info.get("duration") or 0)
            if duration > 0:
                return False, "ended"
        return False, "unknown"

    def host_avatar_url(self, handle: str) -> str:
        normalized = (handle or "").strip().lstrip("@")
        return f"https://unavatar.io/x/{normalized}" if normalized else ""

    def scrape_space_html(self, url: str) -> dict:
        return scrape_space_html(url)

