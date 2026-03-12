from __future__ import annotations


async def execute_track_end(voice_gateway, guild, error=None):
    return await voice_gateway._on_playback_end(guild, error)
