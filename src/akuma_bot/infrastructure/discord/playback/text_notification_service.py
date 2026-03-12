from __future__ import annotations


async def notify_text_channel(guild, sessions, message: str, preferred_channel_id: int = 0) -> None:
    session = sessions.guild(guild.id)
    channel = None
    if preferred_channel_id:
        channel = guild.get_channel(int(preferred_channel_id))
    if not channel and session.last_text_channel_id:
        channel = guild.get_channel(int(session.last_text_channel_id))
    if not channel:
        prefix = f"{guild.id}:"
        for key in list(sessions.panel_messages.keys()):
            if key.startswith(prefix):
                try:
                    _, channel_id_text = key.split(":", 1)
                    channel = guild.get_channel(int(channel_id_text))
                except Exception:
                    channel = None
                if channel:
                    break
    if channel and hasattr(channel, "send"):
        try:
            await channel.send(message)
        except Exception:
            return
