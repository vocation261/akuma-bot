from __future__ import annotations

import asyncio
import datetime
import time

import discord

from infrastructure.runtime.text_utils import embed_color, extract_space_id, format_elapsed


def build_panel_embed(sessions, guild: discord.Guild, note: str = "") -> discord.Embed:
    session = sessions.guild(guild.id)
    voice_client = session.voice_client
    connected = bool(voice_client and voice_client.is_connected())
    playing = bool(voice_client and voice_client.is_playing())
    paused = bool(voice_client and voice_client.is_paused())
    elapsed = session.elapsed()
    source = getattr(voice_client, "source", None) if voice_client else None
    volume_percent = int(round(session.volume * 100))
    muted = False
    if source and hasattr(source, "volume"):
        try:
            volume_percent = int(round(float(source.volume) * 100))
            muted = volume_percent <= 0
        except Exception:
            muted = False

    embed = discord.Embed(color=embed_color(session.is_live, playing, paused))
    status_badge = "LIVE" if session.is_live else "RECORDED"
    if not connected and not session.current_url:
        status_badge = "IDLE"
    play_icon = "▶️" if playing else ("⏸️" if paused else "⏹️")
    embed.set_author(name=f"{play_icon} Space Bot Panel · {status_badge}")
    embed.title = (session.title or "No active session")[:256]
    if session.current_url:
        embed.url = session.current_url

    embed.add_field(name="State", value=session.status_label or ("Live" if session.is_live else "Recorded"), inline=True)
    embed.add_field(name="Audio", value="Paused" if paused else ("Playing" if playing else "Stopped"), inline=True)
    embed.add_field(name="Voice", value="Connected" if connected else "Disconnected", inline=True)
    embed.add_field(name="Source", value=f"[Open link]({session.current_url})" if session.current_url else "No source", inline=False)
    host_value = f"@{session.host_handle}" if session.host_handle else (session.host or "—")
    if session.host and session.host_handle and session.host.lower() != session.host_handle.lower():
        host_value = f"{session.host}\n@{session.host_handle}"
    embed.add_field(name="Host", value=host_value, inline=True)
    embed.add_field(name="Audience", value=f"{session.listeners:,}" if session.listeners else "—", inline=True)
    embed.add_field(name="Volume", value="Muted" if muted else f"{volume_percent}%", inline=True)
    embed.add_field(name="Elapsed", value=format_elapsed(elapsed) if elapsed else "0s", inline=True)
    embed.add_field(name="Duration", value=session.duration_str or "—", inline=True)

    if session.host_image:
        embed.set_thumbnail(url=session.host_image)

    status_line = f"Channel status: `{session.current_channel_status}`" if session.current_channel_status else "Channel status: `default`"
    if session.channel_status_warning:
        status_line = f"{status_line}\n{session.channel_status_warning[:120]}"
    embed.description = f"{note[:220]}\n{status_line}" if note else status_line
    space_id = extract_space_id(session.current_url)
    footer_items = ["Dynamic panel", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())]
    if space_id:
        footer_items.insert(1, space_id)
    embed.set_footer(text=" • ".join(footer_items))
    embed.timestamp = datetime.datetime.now(datetime.UTC)
    return embed


def panel_signature(sessions, guild_id: int) -> tuple:
    session = sessions.guild(guild_id)
    voice_client = session.voice_client
    elapsed_bucket = session.elapsed() // 30
    return (
        bool(voice_client and voice_client.is_connected()),
        bool(voice_client and voice_client.is_playing()) if voice_client else False,
        bool(voice_client and voice_client.is_paused()) if voice_client else False,
        session.is_live,
        session.current_url,
        session.status_label,
        session.title,
        session.host,
        session.listeners,
        session.duration_str,
        elapsed_bucket,
    )


class PanelView(discord.ui.View):
    def __init__(self, guild_id: int, voice_gateway, sessions):
        super().__init__(timeout=1800)
        self.guild_id = guild_id
        self.voice_gateway = voice_gateway
        self.sessions = sessions
        self.sync_buttons()

    def sync_buttons(self) -> None:
        session = self.sessions.guild(self.guild_id)
        voice_client = session.voice_client
        has_voice = bool(voice_client and voice_client.is_connected())
        has_audio = has_voice and bool(voice_client.is_playing() or voice_client.is_paused())
        has_last = bool(session.last_play_url)

        muted = False
        source = getattr(voice_client, "source", None) if voice_client else None
        if source and hasattr(source, "volume"):
            try:
                muted = float(source.volume) <= 0
            except Exception:
                muted = False

        for button in self.children:
            custom_id = str(getattr(button, "custom_id", "") or "")
            key = custom_id.replace("sb:", "")
            if key == "mute":
                button.label = "🔊 Unmute" if muted else "🔇 Mute"
                button.style = discord.ButtonStyle.success if muted else discord.ButtonStyle.secondary
                button.disabled = not has_voice
            elif key == "stop":
                button.disabled = not has_voice
            elif key == "restart":
                button.disabled = not has_last
            elif key == "mark":
                button.disabled = not has_audio

    async def refresh(self, interaction: discord.Interaction, note: str = ""):
        self.sync_buttons()
        embed = build_panel_embed(self.sessions, interaction.guild, note=note)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.secondary, row=0, custom_id="sb:mute")
    async def mute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Panel belongs to another guild.", ephemeral=True)
            return
        _, message = await self.voice_gateway.mute_toggle(interaction.guild)
        await self.refresh(interaction, message)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, row=0, custom_id="sb:stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Panel belongs to another guild.", ephemeral=True)
            return
        _, message = await self.voice_gateway.stop(interaction.guild)
        await self.refresh(interaction, message)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=0, custom_id="sb:refresh")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Panel belongs to another guild.", ephemeral=True)
            return
        await self.refresh(interaction)

    @discord.ui.button(label="🔁 Restart", style=discord.ButtonStyle.secondary, row=0, custom_id="sb:restart")
    async def restart_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Panel belongs to another guild.", ephemeral=True)
            return
        session = self.sessions.guild(self.guild_id)
        if not session.last_play_url:
            await self.refresh(interaction, "No previous item to restart.")
            return
        result = await self.voice_gateway.play(
            interaction.guild,
            interaction.user,
            session.last_play_url,
            mode=session.last_play_mode or "recorded",
            force_vc_channel_id=session.last_play_vc_channel_id,
            text_channel_id=int(interaction.channel_id or 0),
        )
        await self.refresh(interaction, result.get("message", ""))

    @discord.ui.button(label="📍 Bookmark", style=discord.ButtonStyle.secondary, row=1, custom_id="sb:mark")
    async def mark_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = self.sessions.guild(self.guild_id)
        await interaction.response.send_message(
            f"Bookmark saved at {format_elapsed(session.elapsed())} - {session.title or session.current_url}",
            ephemeral=False,
        )


class DiscordPanelGateway:
    def __init__(self, sessions, voice_gateway):
        self.sessions = sessions
        self.voice_gateway = voice_gateway

    async def upsert(self, guild, channel, note: str = "", target_message=None) -> tuple:
        if not guild or not channel or not hasattr(channel, "history"):
            return None, False
        panel_key = f"{guild.id}:{channel.id}"
        panel_id = self.sessions.panel_messages.get(panel_key, 0)
        view = PanelView(guild.id, self.voice_gateway, self.sessions)
        embed = build_panel_embed(self.sessions, guild, note=note)
        existing_message = target_message
        if existing_message is None and panel_id:
            try:
                existing_message = await channel.fetch_message(panel_id)
            except Exception:
                existing_message = None
        if existing_message is None:
            bot_id = None
            try:
                bot_id = channel.guild.me.id
            except Exception:
                bot_id = None
            if bot_id:
                async for message in channel.history(limit=50):
                    if message.author.id != bot_id:
                        continue
                    embeds = list(getattr(message, "embeds", []) or [])
                    if not embeds:
                        continue
                    author_name = str(getattr(getattr(embeds[0], "author", None), "name", "") or "")
                    if "Space Bot Panel" in author_name:
                        existing_message = message
                        self.sessions.panel_messages[panel_key] = message.id
                        break
        if existing_message is not None:
            await existing_message.edit(content=None, embed=embed, view=view)
            self.sessions.panel_messages[panel_key] = existing_message.id
            self.sessions.panel_signatures[panel_key] = panel_signature(self.sessions, guild.id)
            try:
                if not getattr(existing_message, "pinned", False):
                    await existing_message.pin(reason="akuma_bot persistent panel")
            except Exception:
                pass
            return existing_message, True
        sent = await channel.send(embed=embed, view=view)
        if sent:
            self.sessions.panel_messages[panel_key] = sent.id
            self.sessions.panel_signatures[panel_key] = panel_signature(self.sessions, guild.id)
            try:
                await sent.pin(reason="akuma_bot persistent panel")
            except Exception:
                pass
        return sent, False

    async def autorefresh_loop(self, client, interval: float = 4.0):
        while True:
            try:
                await asyncio.sleep(interval)
                if not client.is_ready():
                    continue
                for panel_key, message_id in list(self.sessions.panel_messages.items()):
                    try:
                        guild_id_str, channel_id_str = panel_key.split(":", 1)
                        guild_id = int(guild_id_str)
                        channel_id = int(channel_id_str)
                    except Exception:
                        continue
                    signature = panel_signature(self.sessions, guild_id)
                    if self.sessions.panel_signatures.get(panel_key) == signature:
                        continue
                    guild = client.get_guild(guild_id)
                    if not guild:
                        continue
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                    try:
                        message = await channel.fetch_message(message_id)
                        view = PanelView(guild_id, self.voice_gateway, self.sessions)
                        embed = build_panel_embed(self.sessions, guild)
                        await message.edit(embed=embed, view=view)
                        self.sessions.panel_signatures[panel_key] = signature
                    except Exception:
                        continue
            except asyncio.CancelledError:
                break
            except Exception:
                continue

