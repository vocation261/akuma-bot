from __future__ import annotations

import datetime
import logging
import time
from pathlib import Path

import discord
from discord import app_commands

from akuma_bot.infrastructure.runtime.text_utils import embed_color, format_elapsed, validate_playable_url

logger = logging.getLogger("akuma_bot")


def register_commands(tree: app_commands.CommandTree, deps) -> None:
    voice_gateway = deps.voice_gateway
    panel_gateway = deps.panel_gateway
    sessions = deps.sessions
    history = deps.history_repository
    start_ts = deps.start_ts

    @tree.command(name="live", description="Play X Space or YouTube Live in your voice channel")
    @app_commands.describe(url="Space URL (x.com/i/spaces/...) or YouTube live URL")
    async def live_command(interaction: discord.Interaction, url: str):
        await interaction.response.defer(thinking=True)
        ok_url, error = validate_playable_url(url)
        if not ok_url:
            await interaction.followup.send(error, ephemeral=True)
            return
        result = await voice_gateway.play(interaction.guild, interaction.user, url.strip(), mode="live")
        if not result.get("ok"):
            await interaction.followup.send(result.get("message", "Error"), ephemeral=True)
            return
        if result.get("embed"):
            await interaction.edit_original_response(embed=result["embed"])
        else:
            await interaction.followup.send(result.get("message", "Started"))
        history.log("discord:live", url, "ok", "Playback started", guild_id=interaction.guild_id, channel_id=interaction.channel_id, user_id=interaction.user.id)
        try:
            panel_message, updated = await panel_gateway.upsert(interaction.guild, interaction.channel, note="Playback started (LIVE)")
            if panel_message:
                status = "updated" if updated else "sent"
                await interaction.followup.send(f"Panel {status}: {panel_message.jump_url}", ephemeral=True)
        except Exception:
            pass

    @tree.command(name="rec", description="Play recording, YouTube or playlist in voice channel")
    @app_commands.describe(url="Space recording URL, YouTube URL, playlist URL, etc")
    async def rec_command(interaction: discord.Interaction, url: str):
        await interaction.response.defer(thinking=True)
        ok_url, error = validate_playable_url(url)
        if not ok_url:
            await interaction.followup.send(error, ephemeral=True)
            return
        result = await voice_gateway.play(interaction.guild, interaction.user, url.strip(), mode="recorded")
        if not result.get("ok"):
            await interaction.followup.send(result.get("message", "Error"), ephemeral=True)
            return
        if result.get("status") == "queued":
            await interaction.edit_original_response(content=result.get("message", "Added to queue"))
        elif result.get("embed"):
            await interaction.edit_original_response(embed=result["embed"])
        else:
            await interaction.followup.send(result.get("message", "Started"))
        history.log("discord:rec", url, "ok", "Playback started", guild_id=interaction.guild_id, channel_id=interaction.channel_id, user_id=interaction.user.id)
        try:
            panel_message, updated = await panel_gateway.upsert(interaction.guild, interaction.channel, note="Playback started (REC)")
            if panel_message:
                status = "updated" if updated else "sent"
                await interaction.followup.send(f"Panel {status}: {panel_message.jump_url}", ephemeral=True)
        except Exception:
            pass
        added = result.get("playlist_added", 0)
        if added:
            await interaction.followup.send(f"Playlist: {added} extra item(s) queued.", ephemeral=True)

    @tree.command(name="dash", description="Show the bot control panel in this guild")
    async def dash_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=False)
        if not interaction.guild:
            await interaction.followup.send("Use this command in a guild.", ephemeral=True)
            return
        try:
            message, updated = await panel_gateway.upsert(interaction.guild, interaction.channel)
            jump = getattr(message, "jump_url", "") or ""
            label = "Panel updated" if updated else "Panel sent"
            await interaction.followup.send(f"{label}: {jump}" if jump else label, ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Panel error: {exc}", ephemeral=True)

    @tree.command(name="dc", description="Disconnect bot from voice channel")
    async def disconnect_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        _, message = await voice_gateway.stop(interaction.guild)
        await interaction.followup.send(message)

    @tree.command(name="mute", description="Toggle bot audio mute")
    async def mute_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        _, message = await voice_gateway.mute_toggle(interaction.guild)
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="pause", description="Pause or resume playback")
    async def pause_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        _, message = await voice_gateway.pause_toggle(interaction.guild)
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="resume", description="Resume playback")
    async def resume_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = sessions.guild(interaction.guild_id)
        voice_client = session.voice_client
        if voice_client and voice_client.is_paused():
            _, message = await voice_gateway.pause_toggle(interaction.guild)
        else:
            message = "No paused track."
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="forward", description="Forward: 1, 5, 10, 30 or 60 minutes")
    @app_commands.describe(minutes="Minutes to skip forward")
    @app_commands.choices(
        minutes=[
            app_commands.Choice(name="1 min", value=1),
            app_commands.Choice(name="5 min", value=5),
            app_commands.Choice(name="10 min", value=10),
            app_commands.Choice(name="30 min", value=30),
            app_commands.Choice(name="60 min", value=60),
        ]
    )
    async def forward_command(interaction: discord.Interaction, minutes: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        _, message = await voice_gateway.seek(interaction.guild, minutes * 60)
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="rewind", description="Rewind: 1, 5 or 30 minutes")
    @app_commands.describe(minutes="Minutes to rewind")
    @app_commands.choices(
        minutes=[
            app_commands.Choice(name="1 min", value=1),
            app_commands.Choice(name="5 min", value=5),
            app_commands.Choice(name="30 min", value=30),
        ]
    )
    async def rewind_command(interaction: discord.Interaction, minutes: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        _, message = await voice_gateway.seek(interaction.guild, -minutes * 60)
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="seek", description="Forward N seconds on current track")
    @app_commands.describe(seconds="Seconds to move forward")
    async def seek_command(interaction: discord.Interaction, seconds: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        _, message = await voice_gateway.seek(interaction.guild, max(1, seconds))
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="seekback", description="Rewind N seconds on current track")
    @app_commands.describe(seconds="Seconds to rewind")
    async def seekback_command(interaction: discord.Interaction, seconds: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        _, message = await voice_gateway.seek(interaction.guild, -max(1, seconds))
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="seekto", description="Seek to exact position by hour/minute/second")
    @app_commands.describe(hour="Hours", minute="Minutes", second="Seconds")
    async def seekto_command(interaction: discord.Interaction, hour: int = 0, minute: int = 0, second: int = 0):
        await interaction.response.defer(thinking=True, ephemeral=True)
        target = hour * 3600 + minute * 60 + second
        _, message = await voice_gateway.seek_to(interaction.guild, target)
        await interaction.followup.send(message, ephemeral=True)

    @tree.command(name="history", description="Show latest playback history")
    @app_commands.describe(limit="Rows to show (1-30)", user_id="Filter by user id", channel_id="Filter by channel id")
    async def history_command(interaction: discord.Interaction, limit: int = 10, user_id: str = "", channel_id: str = ""):
        await interaction.response.defer(thinking=True, ephemeral=True)
        uid = int(user_id) if str(user_id).isdigit() else None
        cid = int(channel_id) if str(channel_id).isdigit() else None
        rows = history.latest(limit=max(1, min(30, int(limit or 10))), guild_id=interaction.guild_id, channel_id=cid, user_id=uid)
        if not rows:
            await interaction.followup.send("No history.", ephemeral=True)
            return
        embed = discord.Embed(title="Latest playback history", color=0x5865F2)
        for ts, source, url, status, message, gid, cid_value, uid_value in rows:
            date_text = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")
            short_url = url[:60] + "…" if len(url) > 60 else url
            embed.add_field(
                name=f"{date_text} - {source}",
                value=f"`{status}` {short_url}\n{message[:80]}\nUser {uid_value or '—'} · Channel {cid_value or '—'}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="diag", description="Quick bot diagnostics")
    async def diag_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        session = sessions.guild(guild.id) if guild else None
        voice_client = session.voice_client if session else None
        lines = [
            f"Bot: {deps.client.user}",
            f"Guilds: {len(deps.client.guilds)}",
            f"Latency: {round(deps.client.latency * 1000)}ms",
        ]
        if session and voice_client:
            lines.extend(
                [
                    f"Voice connected: {voice_client.is_connected()}",
                    f"Playing: {voice_client.is_playing()}",
                    f"Paused: {voice_client.is_paused()}",
                    f"Mode: {'LIVE' if session.is_live else 'REC'}",
                    f"Title: {session.title or '—'}",
                    f"Elapsed: {format_elapsed(session.elapsed())}",
                    f"URL: {(session.current_url or '—')[:80]}",
                ]
            )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @tree.command(name="mark", description="Save bookmark at current position")
    async def mark_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=False)
        session = sessions.guild(interaction.guild_id)
        elapsed = session.elapsed()
        embed = discord.Embed(title="Bookmark saved", color=0xFEE75C)
        embed.add_field(name="Position", value=format_elapsed(elapsed), inline=True)
        embed.add_field(name="Title", value=session.title or "—", inline=False)
        embed.add_field(name="URL", value=session.current_url or "—", inline=False)
        embed.timestamp = datetime.datetime.now(datetime.UTC)
        history.add_bookmark(
            guild_id=interaction.guild_id,
            channel_id=int(interaction.channel_id or 0),
            user_id=int(interaction.user.id),
            url=session.current_url or "",
            title=session.title or "Untitled",
            position_sec=int(elapsed),
            note="Bookmark from /mark",
        )
        await interaction.followup.send(embed=embed)

    @tree.command(name="skip", description="Skip current track if queue has items")
    async def skip_command(interaction: discord.Interaction):
        session = sessions.guild(interaction.guild_id)
        voice_client = session.voice_client
        if not voice_client or not voice_client.is_connected() or not (voice_client.is_playing() or voice_client.is_paused()):
            await interaction.response.send_message("No active playback.", ephemeral=True)
            return
        if not session.queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        session.suppress_after_events += 1
        voice_client.stop()
        await interaction.response.send_message(f"Skipped. Remaining queue: {len(session.queue)}", ephemeral=True)

    @tree.command(name="cq", description="Clear playback queue")
    async def clear_queue_command(interaction: discord.Interaction):
        session = sessions.guild(interaction.guild_id)
        deleted = len(session.queue)
        session.queue.clear()
        await interaction.response.send_message(f"Queue cleared ({deleted} removed).", ephemeral=True)

    @tree.command(name="now", description="Show currently playing item")
    async def now_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = sessions.guild(interaction.guild_id)
        voice_client = session.voice_client
        if not voice_client or not voice_client.is_connected() or not session.current_url:
            await interaction.followup.send("No active playback.", ephemeral=True)
            return
        embed = discord.Embed(title="Now playing", color=embed_color(session.is_live, voice_client.is_playing(), voice_client.is_paused()))
        embed.add_field(name="Title", value=session.title or "—", inline=False)
        embed.add_field(name="URL", value=session.current_url[:200], inline=False)
        embed.add_field(name="Elapsed", value=format_elapsed(session.elapsed()), inline=True)
        embed.add_field(name="Duration", value=session.duration_str or "—", inline=True)
        embed.add_field(name="Queue", value=str(len(session.queue)), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="queue", description="Show queued items")
    @app_commands.describe(limit="Number of items to display (1-20)")
    async def queue_command(interaction: discord.Interaction, limit: int = 10):
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = sessions.guild(interaction.guild_id)
        if not session.queue:
            await interaction.followup.send("Queue is empty.", ephemeral=True)
            return
        count = max(1, min(20, int(limit or 10)))
        lines = []
        for index, item in enumerate(session.queue[:count], start=1):
            lines.append(f"{index}. {str(item.url)[:90]}")
        remaining = len(session.queue) - len(lines)
        if remaining > 0:
            lines.append(f"... and {remaining} more")
        await interaction.followup.send("Queue:\n" + "\n".join(lines), ephemeral=True)

    @tree.command(name="bookmarks", description="Show persistent bookmarks for this guild")
    @app_commands.describe(limit="Number of bookmarks (1-20)")
    async def bookmarks_command(interaction: discord.Interaction, limit: int = 10):
        await interaction.response.defer(thinking=True, ephemeral=True)
        rows = history.latest_bookmarks(interaction.guild_id, limit=max(1, min(20, int(limit or 10))))
        if not rows:
            await interaction.followup.send("No bookmarks found.", ephemeral=True)
            return
        embed = discord.Embed(title="Bookmarks", color=0xFEE75C)
        for ts, channel_id, user_id, url, title, position_sec, note in rows:
            date_text = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")
            embed.add_field(
                name=f"{date_text} · {format_elapsed(position_sec)}",
                value=f"{title[:80]}\n{(url or '—')[:90]}\nUser {user_id} · Channel {channel_id}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="historycsv", description="Export history to CSV")
    @app_commands.describe(limit="Max rows (1-5000)", user_id="Filter by user id", channel_id="Filter by channel id")
    async def history_csv_command(interaction: discord.Interaction, limit: int = 1000, user_id: str = "", channel_id: str = ""):
        await interaction.response.defer(thinking=True, ephemeral=True)
        uid = int(user_id) if str(user_id).isdigit() else None
        cid = int(channel_id) if str(channel_id).isdigit() else None
        max_rows = max(1, min(5000, int(limit or 1000)))
        output_dir = Path("data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"history_export_{interaction.guild_id}_{int(time.time())}.csv"
        count = history.export_csv(str(output_path), guild_id=interaction.guild_id, channel_id=cid, user_id=uid, limit=max_rows)
        await interaction.followup.send(content=f"CSV generated with {count} row(s).", file=discord.File(str(output_path)), ephemeral=True)

    @tree.command(name="health", description="Operational health snapshot")
    async def health_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = sessions.guild(interaction.guild_id)
        voice_client = session.voice_client
        uptime = int(time.time() - start_ts)
        embed = discord.Embed(title="Health", color=0x57F287)
        embed.add_field(name="Uptime", value=format_elapsed(uptime), inline=True)
        embed.add_field(name="Latency", value=f"{round(deps.client.latency * 1000)}ms", inline=True)
        embed.add_field(name="Guilds", value=str(len(deps.client.guilds)), inline=True)
        embed.add_field(name="Voice", value="connected" if (voice_client and voice_client.is_connected()) else "disconnected", inline=True)
        embed.add_field(name="Audio", value="playing" if (voice_client and voice_client.is_playing()) else ("paused" if (voice_client and voice_client.is_paused()) else "stopped"), inline=True)
        embed.add_field(name="Queue", value=str(len(session.queue)), inline=True)
        embed.add_field(name="Retries", value=f"{session.play_retry_count}/{session.max_play_retries}", inline=True)
        embed.add_field(name="Channel status", value="on" if session.channel_status_enabled else "off", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


def register_tree_error_handler(tree: app_commands.CommandTree):
    @tree.error
    async def on_tree_error(interaction: discord.Interaction, error: Exception):
        command_name = getattr(interaction.command, "name", "?")
        logger.error("Slash command error /%s: %s: %s", command_name, type(error).__name__, error, exc_info=True)
        message = f"Error in /{command_name}: {error}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception:
            pass

