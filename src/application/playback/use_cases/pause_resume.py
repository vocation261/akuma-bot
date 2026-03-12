from __future__ import annotations


async def execute_pause_resume(voice_gateway, guild):
    return await voice_gateway.pause_toggle(guild)
