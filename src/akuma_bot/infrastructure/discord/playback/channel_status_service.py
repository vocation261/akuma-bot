from __future__ import annotations

import logging

logger = logging.getLogger("akuma_bot")


async def set_channel_status(session, channel, text: str) -> None:
    if not session.channel_status_enabled or not channel:
        return
    status_text = (f"{session.channel_status_prefix}{text}".strip().replace("\n", " "))[:120]
    if not status_text:
        return
    if session.original_channel_status is None:
        session.original_channel_status = getattr(channel, "status", None)
    try:
        await channel.edit(status=status_text, reason="akuma_bot playback status")
        session.channel_status_overridden = True
        session.current_channel_status = status_text
        session.channel_status_warning = ""
    except Exception:
        session.channel_status_warning = "Missing Manage Channels permission for channel status."


async def restore_channel_status(session, guild) -> None:
    if not session.channel_status_overridden:
        return
    channel_id = int(session.last_vc_channel_id or 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    if not channel:
        session.original_channel_status = None
        session.channel_status_overridden = False
        session.current_channel_status = ""
        return
    try:
        await channel.edit(status=session.original_channel_status or "", reason="akuma_bot restore channel status")
    except Exception:
        logger.debug("Could not restore channel status for channel %s", channel_id)
    finally:
        session.original_channel_status = None
        session.channel_status_overridden = False
        session.current_channel_status = ""
