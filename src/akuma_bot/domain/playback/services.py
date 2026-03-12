from __future__ import annotations


def can_seek(is_live: bool, has_active_track: bool) -> bool:
    return (not is_live) and has_active_track
