from __future__ import annotations

from typing import Protocol


class PanelGateway(Protocol):
    async def upsert(self, guild, channel, note: str = "", target_message=None) -> tuple:
        ...

    async def autorefresh_loop(self, client, interval: float = 4.0) -> None:
        ...

