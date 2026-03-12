from __future__ import annotations

from typing import Protocol


class VoiceGateway(Protocol):
    async def play(
        self,
        guild,
        user,
        url: str,
        mode: str = "recorded",
        force_vc_channel_id: int = 0,
        text_channel_id: int = 0,
    ) -> dict:
        ...

    async def pause_toggle(self, guild) -> tuple[bool, str]:
        ...

    async def stop(self, guild) -> tuple[bool, str]:
        ...

    async def mute_toggle(self, guild) -> tuple[bool, str]:
        ...

    async def seek(self, guild, seconds_delta: int) -> tuple[bool, str]:
        ...

    async def seek_to(self, guild, target_sec: int) -> tuple[bool, str]:
        ...

