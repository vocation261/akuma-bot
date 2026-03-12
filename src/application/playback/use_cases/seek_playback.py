from __future__ import annotations


async def execute_seek_playback(voice_gateway, guild, seconds_delta: int):
    return await voice_gateway.seek(guild, seconds_delta)
