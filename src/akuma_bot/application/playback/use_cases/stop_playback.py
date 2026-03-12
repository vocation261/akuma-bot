from __future__ import annotations


async def execute_stop_playback(voice_gateway, guild):
    return await voice_gateway.stop(guild)
