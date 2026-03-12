"""X Spaces audio downloader using yt-dlp."""

from __future__ import annotations

import datetime
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Tuple

from infrastructure.runtime.text_utils import extract_space_id

logger = logging.getLogger("akuma_bot")
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
_YTDLP_PROGRESS_RE = re.compile(
    r"^download:(?P<downloaded>\d+|NA):(?P<total>\d+|NA):(?P<estimate>\d+|NA)$",
    re.IGNORECASE,
)



def _format_space_date(raw_date: str) -> str:
    text = str(raw_date or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return "unknown-date"


def _resolve_space_status(info: dict[str, Any]) -> tuple[bool, str]:
    live_status = str(info.get("live_status") or "").strip().lower()
    live_flag = info.get("is_live")
    if isinstance(live_flag, bool):
        if live_flag:
            return True, "live"
        if live_status in {"post_live", "was_live", "ended", "not_live"}:
            return False, "ended"
        return False, "ended"

    if live_status in {"is_live", "live", "running"}:
        return True, "live"
    if live_status in {"post_live", "was_live", "ended", "not_live"}:
        return False, "ended"

    duration_value = info.get("duration") or info.get("duration_seconds") or 0
    try:
        if float(duration_value or 0) > 0:
            return False, "ended"
    except Exception:
        pass

    return False, "unknown"


def _metadata_from_info(info: dict[str, Any], fallback_space_id: str) -> dict[str, Any]:
    uploader = str(info.get("uploader_id") or info.get("channel_id") or info.get("uploader") or "unknown").strip()
    if uploader and not uploader.startswith("@"):
        uploader = f"@{uploader}"

    ts_candidates = [
        info.get("release_timestamp"),
        info.get("timestamp"),
    ]
    started_at_utc = "unknown"
    for value in ts_candidates:
        try:
            if value is None:
                continue
            dt = datetime.datetime.fromtimestamp(int(value), datetime.UTC)
            started_at_utc = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            break
        except Exception:
            continue

    duration_value = info.get("duration") or info.get("duration_seconds") or 0
    if not duration_value:
        for fmt in list(info.get("formats") or []):
            try:
                candidate = float(fmt.get("duration") or 0)
            except Exception:
                candidate = 0.0
            if candidate > 0:
                duration_value = candidate
                break

    is_live, status_key = _resolve_space_status(info)

    return {
        "space_id": str(info.get("id") or fallback_space_id or "unknown-space").strip(),
        "space_title": str(info.get("title") or "Untitled Space").strip() or "Untitled Space",
        "space_date": _format_space_date(str(info.get("upload_date") or "")),
        "space_started_at": started_at_utc,
        "twitter_account": uploader or "@unknown",
        "duration_sec": int(float(duration_value or 0)),
        "is_live": is_live,
        "status_key": status_key,
    }


def fetch_space_metadata(url: str) -> Tuple[bool, str, dict[str, Any] | None]:
    try:
        space_id = extract_space_id(url)
        if not space_id:
            return False, "Invalid URL", None

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--dump-single-json",
            "--skip-download",
            url,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        payload = result.stdout.strip()
        if not payload:
            return False, "No metadata", None

        import json

        info = json.loads(payload)
        metadata = _metadata_from_info(info if isinstance(info, dict) else {}, space_id)
        return True, "ok", metadata
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        if "not available" in error_msg.lower() or "private" in error_msg.lower():
            return False, "Not available", None
        return False, error_msg[:200], None
    except Exception as e:
        return False, str(e)[:200], None


def download_space_audio(
    url: str,
    output_dir: Path,
    audio_format: str = "mp3",
    progress_callback: Callable[[int], None] | None = None,
) -> Tuple[bool, str, Path | None]:
    try:
        space_id = extract_space_id(url)
        if not space_id:
            return False, "Invalid URL", None

        output_dir.mkdir(parents=True, exist_ok=True)

        output_template = str(output_dir / f"{space_id}.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-x",
            "--audio-format",
            audio_format,
            "-o",
            output_template,
            "--no-warnings",
            "--newline",
            "--concurrent-fragments",
            "8",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--progress-template",
            "download:%(progress.downloaded_bytes)s:%(progress.total_bytes)s:%(progress.total_bytes_estimate)s",
            url,
        ]

        logger.info(f"Downloading Space audio: {space_id}")
        if progress_callback:
            try:
                progress_callback(0)
            except Exception:
                pass

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        last_percent = -1
        output_lines: list[str] = []

        assert process.stdout is not None
        for line in process.stdout:
            output_lines.append(line)

            progress_match = _YTDLP_PROGRESS_RE.search(line.strip())
            if progress_match:
                try:
                    downloaded_raw = progress_match.group("downloaded")
                    total_raw = progress_match.group("total")
                    estimate_raw = progress_match.group("estimate")
                    downloaded = int(downloaded_raw) if downloaded_raw.isdigit() else 0
                    total = int(total_raw) if total_raw.isdigit() else 0
                    estimated_total = int(estimate_raw) if estimate_raw.isdigit() else 0
                    denominator = total or estimated_total
                    if denominator > 0 and downloaded >= 0:
                        percent_value = int((downloaded * 100) / denominator)
                        percent_value = max(0, min(100, percent_value))
                        if percent_value > last_percent:
                            last_percent = percent_value
                            if progress_callback:
                                try:
                                    progress_callback(percent_value)
                                except Exception:
                                    pass
                        continue
                except Exception:
                    pass

            match = _PERCENT_RE.search(line)
            if not match:
                continue
            try:
                percent_value = int(float(match.group(1)))
            except Exception:
                continue
            if percent_value > last_percent:
                last_percent = percent_value
                if progress_callback:
                    try:
                        progress_callback(percent_value)
                    except Exception:
                        pass

        return_code = process.wait(timeout=600)
        if return_code != 0:
            error_msg = "".join(output_lines).strip()
            if "not available" in error_msg.lower() or "private" in error_msg.lower():
                return False, "Space is not available or not recorded", None
            if "not found" in error_msg.lower():
                return False, "Space not found", None
            return False, f"Download failed: {error_msg[:200]}", None

        if progress_callback:
            try:
                progress_callback(100)
            except Exception:
                pass

        audio_path = output_dir / f"{space_id}.{audio_format}"
        if not audio_path.exists():
            matches = list(output_dir.glob(f"{space_id}.*"))
            if matches:
                audio_path = matches[0]
            else:
                return False, "File not found", None

        logger.info(f"Audio downloaded: {audio_path}")
        return True, audio_path.name, audio_path

    except subprocess.TimeoutExpired:
        logger.error(f"Download timeout: {url}")
        return False, "Timeout", None

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        logger.error(f"yt-dlp error: {error_msg}")
        if "not available" in error_msg.lower() or "private" in error_msg.lower():
            return False, "Not available", None
        if "not found" in error_msg.lower():
            return False, "Not found", None
        return False, error_msg[:200], None

    except FileNotFoundError:
        logger.error("yt-dlp not found")
        return False, "yt-dlp not installed", None

    except Exception as e:
        logger.exception(f"Download error: {e}")
        return False, str(e)[:200], None
