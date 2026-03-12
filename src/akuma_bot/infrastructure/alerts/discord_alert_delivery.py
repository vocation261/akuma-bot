from __future__ import annotations

import asyncio
import discord


class DiscordAlertDelivery:
    def __init__(self, mention_everyone: bool) -> None:
        self.mention_everyone = mention_everyone

    async def send(self, channels: list[discord.abc.Messageable], embed: discord.Embed) -> int:
        content = "@everyone 🚨🎙️🔥" if self.mention_everyone else "🚨🎙️🔥"
        results = await asyncio.gather(
            *[
                channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(everyone=self.mention_everyone),
                )
                for channel in channels
            ],
            return_exceptions=True,
        )
        return sum(1 for item in results if not isinstance(item, Exception))
