from __future__ import annotations

import asyncio
import datetime
import re
import time

import discord

from akuma_bot.infrastructure.runtime.text_utils import embed_color, extract_space_id, format_elapsed


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
        session.elapsed() // 5,
    )


class SeekModal(discord.ui.Modal, title="Go to position"):
    target_input = discord.ui.TextInput(
        label="Target (12m, 1h20m, 12:34, 452)",
        required=True,
        max_length=24,
        placeholder="12m | 1h20m | MM:SS | HH:MM:SS",
    )

    def __init__(self, guild_id: int, panel_message, voice_gateway, sessions):
        super().__init__()
        self.guild_id = guild_id
        self.panel_message = panel_message
        self.voice_gateway = voice_gateway
        self.sessions = sessions

    def parse_seconds(self, raw: str) -> int | None:
        text = str(raw or "").strip().lower().replace(" ", "")
        if not text:
            return None
        if text.isdigit():
            return max(0, int(text))
        if ":" in text:
            parts = [part.strip() for part in text.split(":")]
            if any((not part) or (not part.isdigit()) for part in parts):
                return None
            numbers = [int(part) for part in parts]
            if len(numbers) == 2:
                return max(0, numbers[0] * 60 + numbers[1])
            if len(numbers) == 3:
                return max(0, numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
            return None
        tokens = re.findall(r"(\d+)([hms])", text)
        if not tokens:
            return None
        total = 0
        for number, unit in tokens:
            total += int(number) * {"h": 3600, "m": 60, "s": 1}[unit]
        return max(0, total)

    async def on_submit(self, interaction: discord.Interaction):
        target = self.parse_seconds(str(self.target_input.value))
        if target is None:
            await interaction.response.send_message("Invalid format.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await self.voice_gateway.seek_to(interaction.guild, target)
        try:
            view = PanelView(self.guild_id, self.voice_gateway, self.sessions)
            embed = build_panel_embed(self.sessions, interaction.guild, note=message)
            await self.panel_message.edit(embed=embed, view=view)
        except Exception:
            pass
        if ok:
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
        else:
            await interaction.followup.send(message, ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self, guild_id: int, voice_gateway, sessions):
        super().__init__(timeout=1800)
        self.guild_id = guild_id
        self.voice_gateway = voice_gateway
        self.sessions = sessions
        self.clear_guard: dict[int, tuple[int, float]] = {}
        self.sync_buttons()

    def sync_buttons(self) -> None:
        session = self.sessions.guild(self.guild_id)
        voice_client = session.voice_client
        has_voice = bool(voice_client and voice_client.is_connected())
        has_audio = has_voice and bool(voice_client.is_playing() or voice_client.is_paused())
        is_paused = has_voice and bool(voice_client.is_paused())
        is_live = session.is_live
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
            if key == "pause":
                button.label = "▶️ Resume" if is_paused else "⏸️ Pause"
                button.style = discord.ButtonStyle.secondary if is_paused else discord.ButtonStyle.primary
                button.disabled = not has_audio or is_live
            elif key == "mute":
                button.label = "🔊 Unmute" if muted else "🔇 Mute"
                button.style = discord.ButtonStyle.success if muted else discord.ButtonStyle.secondary
                button.disabled = not has_voice
            elif key == "stop":
                button.disabled = not has_voice
            elif key == "restart":
                button.disabled = not has_last
            elif key in {"bk60", "bk5", "fw5", "fw30", "fw60", "seek_modal"}:
                button.disabled = is_live or not has_audio
            elif key == "mark":
                button.disabled = not has_audio

    async def refresh(self, interaction: discord.Interaction, note: str = ""):
        self.sync_buttons()
        embed = build_panel_embed(self.sessions, interaction.guild, note=note)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.primary, row=0, custom_id="sb:pause")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Panel belongs to another guild.", ephemeral=True)
            return
        _, message = await self.voice_gateway.pause_toggle(interaction.guild)
        await self.refresh(interaction, message)

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
        )
        await self.refresh(interaction, result.get("message", ""))

    @discord.ui.button(label="⏪ -1m", style=discord.ButtonStyle.primary, row=1, custom_id="sb:bk60")
    async def back_1m_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, message = await self.voice_gateway.seek(interaction.guild, -60)
        await self.refresh(interaction, message)

    @discord.ui.button(label="⏪ -5m", style=discord.ButtonStyle.primary, row=1, custom_id="sb:bk5")
    async def back_5m_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, message = await self.voice_gateway.seek(interaction.guild, -300)
        await self.refresh(interaction, message)

    @discord.ui.button(label="⏩ +5m", style=discord.ButtonStyle.primary, row=1, custom_id="sb:fw5")
    async def forward_5m_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, message = await self.voice_gateway.seek(interaction.guild, 300)
        await self.refresh(interaction, message)

    @discord.ui.button(label="⏩ +30m", style=discord.ButtonStyle.primary, row=1, custom_id="sb:fw30")
    async def forward_30m_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, message = await self.voice_gateway.seek(interaction.guild, 1800)
        await self.refresh(interaction, message)

    @discord.ui.button(label="⏩ +1h", style=discord.ButtonStyle.primary, row=1, custom_id="sb:fw60")
    async def forward_1h_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, message = await self.voice_gateway.seek(interaction.guild, 3600)
        await self.refresh(interaction, message)

    @discord.ui.button(label="🎯 Seek", style=discord.ButtonStyle.secondary, row=2, custom_id="sb:seek_modal")
    async def seek_modal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SeekModal(self.guild_id, interaction.message, self.voice_gateway, self.sessions))

    @discord.ui.button(label="📍 Bookmark", style=discord.ButtonStyle.secondary, row=2, custom_id="sb:mark")
    async def mark_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = self.sessions.guild(self.guild_id)
        await interaction.response.send_message(
            f"Bookmark saved at {format_elapsed(session.elapsed())} - {session.title or session.current_url}",
            ephemeral=False,
        )

    @discord.ui.button(label="🧹 Clear chat", style=discord.ButtonStyle.secondary, row=3, custom_id="sb:clear")
    async def clear_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Panel belongs to another guild.", ephemeral=True)
            return
        user_id = interaction.user.id if interaction.user else 0
        now = time.time()
        step, timestamp = self.clear_guard.get(user_id, (0, 0.0))
        if now - timestamp > 25:
            step = 0
        step += 1
        self.clear_guard[user_id] = (step, now)
        if step < 3:
            await interaction.response.send_message(f"Confirmation {step}/3.", ephemeral=True)
            return
        self.clear_guard.pop(user_id, None)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            deleted = await interaction.channel.purge(limit=50)
            await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Clear failed: {exc}", ephemeral=True)


class DiscordPanelGateway:
    def __init__(self, sessions, voice_gateway):
        self.sessions = sessions
        self.voice_gateway = voice_gateway

    async def upsert(self, guild, channel, note: str = "") -> tuple:
        if not guild or not channel or not hasattr(channel, "history"):
            return None, False
        panel_key = f"{guild.id}:{channel.id}"
        panel_id = self.sessions.panel_messages.get(panel_key, 0)
        view = PanelView(guild.id, self.voice_gateway, self.sessions)
        embed = build_panel_embed(self.sessions, guild, note=note)
        target_message = None
        if panel_id:
            try:
                target_message = await channel.fetch_message(panel_id)
            except Exception:
                target_message = None
        if target_message is None:
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
                        target_message = message
                        self.sessions.panel_messages[panel_key] = message.id
                        break
        if target_message is not None:
            await target_message.edit(embed=embed, view=view)
            self.sessions.panel_signatures[panel_key] = panel_signature(self.sessions, guild.id)
            try:
                if not getattr(target_message, "pinned", False):
                    await target_message.pin(reason="akuma_bot persistent panel")
            except Exception:
                pass
            return target_message, True
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

