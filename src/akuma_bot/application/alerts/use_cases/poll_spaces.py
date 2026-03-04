from __future__ import annotations

from typing import Any

from akuma_bot.domain.alerts.entities import SpaceEvent
from akuma_bot.domain.alerts.services import should_emit_event


def resolve_target_channels(client, space: dict[str, Any], user_channels: dict[str, list[int]], fallback_channel_ids: list[int]):
    creator_id = str(space.get("creator_id") or "").strip()
    selected_channel_ids: list[int] = []

    if creator_id:
        for value in list(user_channels.get(creator_id, [])):
            try:
                channel_id = int(value)
            except Exception:
                continue
            if channel_id not in selected_channel_ids:
                selected_channel_ids.append(channel_id)

    if not selected_channel_ids:
        selected_channel_ids = list(fallback_channel_ids)

    channels = [client.get_channel(channel_id) for channel_id in selected_channel_ids]
    return [channel for channel in channels if channel is not None]


def compute_delivery_key(space: dict[str, Any], alerted_repo) -> tuple[bool, str]:
    event = SpaceEvent(
        space_id=str(space.get("id") or ""),
        creator_id=str(space.get("creator_id") or ""),
        state=str(space.get("state") or ""),
    )
    if not event.space_id:
        return False, ""
    return should_emit_event(event, alerted_repo.contains)
