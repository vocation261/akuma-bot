from __future__ import annotations

from domain.alerts.entities import SpaceEvent


def should_emit_event(event: SpaceEvent, alerted_exists: callable) -> tuple[bool, str]:
    live_key = event.space_id
    ended_key = f"{event.space_id}:ENDED"
    state = str(event.state or "").lower()
    if state in {"running", "live", ""}:
        return (not alerted_exists(live_key), live_key)
    if state == "ended":
        should_emit = alerted_exists(live_key) and not alerted_exists(ended_key)
        return should_emit, ended_key
    return False, live_key
