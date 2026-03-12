from __future__ import annotations

from akuma_bot.infrastructure.runtime.text_utils import format_elapsed


def session_details_snapshot(session) -> dict:
    host_value = str(session.host) if session.host else (f"@{session.host_handle}" if session.host_handle else "—")
    return {
        "title": str(session.title or "Unknown Space"),
        "host": host_value,
        "participants": int(session.participants or 0),
        "listeners": int(session.listeners or 0),
        "duration": format_elapsed(session.elapsed()),
        "url": str(session.current_url or ""),
    }


def build_end_notice(reason: str, details: dict) -> str:
    if reason == "inactivity":
        return (
            "Session ended by inactivity: bot was alone in voice channel for 5 minutes.\n"
            f"Space: {details['title']}\n"
            f"Host: {details['host']}\n"
            f"Participants: {details['participants']:,}\n"
            f"Listeners: {details['listeners']:,}\n"
            f"Duration played: {details['duration']}\n"
            f"URL: {details['url'] or '—'}"
        )
    if reason == "space_ended":
        return (
            "Session ended: the Space stream has finished.\n"
            f"Space: {details['title']}\n"
            f"Host: {details['host']}\n"
            f"Participants: {details['participants']:,}\n"
            f"Listeners: {details['listeners']:,}\n"
            f"Duration played: {details['duration']}\n"
            f"URL: {details['url'] or '—'}"
        )
    return "Session ended."
