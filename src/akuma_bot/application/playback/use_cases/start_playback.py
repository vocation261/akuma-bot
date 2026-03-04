from __future__ import annotations


async def execute_start_playback(voice_gateway, guild, user, url: str, mode: str, text_channel_id: int = 0):
    return await voice_gateway.play(guild, user, url, mode=mode, text_channel_id=text_channel_id)
