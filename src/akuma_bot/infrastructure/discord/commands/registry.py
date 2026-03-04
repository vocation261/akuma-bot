from __future__ import annotations

import datetime
import asyncio
import logging
import time
from pathlib import Path

import discord
from discord import app_commands

from akuma_bot.infrastructure.runtime.text_utils import embed_color, extract_space_id, format_elapsed, validate_playable_url

logger = logging.getLogger("akuma_bot")


def register_commands(tree: app_commands.CommandTree, deps) -> None:
    voice_gateway = deps.voice_gateway
    panel_gateway = deps.panel_gateway
    alert_monitor = deps.alert_monitor
    sessions = deps.sessions
    history = deps.history_repository
    start_ts = deps.start_ts

    @tree.command(name="live", description="Play X Space live in your voice channel")
    @app_commands.describe(url="X Space URL (x.com/i/spaces/...)")
    async def live_command(interaction: discord.Interaction, url: str):
        await interaction.response.defer(thinking=True)
        ok_url, error = validate_playable_url(url)
        if not ok_url:
            await interaction.followup.send(error, ephemeral=True)
            return
        result = await voice_gateway.play(
            interaction.guild,
            interaction.user,
            url.strip(),
            mode="live",
            text_channel_id=int(interaction.channel_id or 0),
        )
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

    @tree.command(name="rec", description="Play recorded X Space in voice channel")
    @app_commands.describe(url="Recorded X Space URL (x.com/i/spaces/...)")
    async def rec_command(interaction: discord.Interaction, url: str):
        await interaction.response.defer(thinking=True)
        ok_url, error = validate_playable_url(url)
        if not ok_url:
            await interaction.followup.send(error, ephemeral=True)
            return
        result = await voice_gateway.play(
            interaction.guild,
            interaction.user,
            url.strip(),
            mode="recorded",
            text_channel_id=int(interaction.channel_id or 0),
        )
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
    @tree.command(name="participants", description="Show scraped participants for the current Space")
    async def participants_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Use this command in a guild.", ephemeral=True)
            return

        session = sessions.guild(interaction.guild_id)
        current_url = str(session.current_url or "")
        space_id = extract_space_id(current_url)
        if not space_id:
            await interaction.followup.send("No active X Space in this guild.", ephemeral=True)
            return

        payload = await asyncio.to_thread(alert_monitor.scraper.get_space_participants, space_id)
        if not payload.get("ok"):
            await interaction.followup.send(str(payload.get("error") or "Failed to fetch participants."), ephemeral=True)
            return

        def render_users(items: list[dict], limit: int = 15) -> str:
            if not items:
                return "—"
            lines: list[str] = []
            for idx, user in enumerate(items[:limit], start=1):
                username = str(user.get("username") or "").strip()
                name = str(user.get("name") or "").strip()
                user_id = str(user.get("id") or "")
                profile_url = f"https://x.com/{username}" if username else ""
                if username and name and name.lower() != username.lower():
                    tag = f"{name} ([@{username}]({profile_url}))"
                elif username:
                    tag = f"[@{username}]({profile_url})"
                else:
                    tag = name or user_id or "unknown"
                lines.append(f"{idx}. {tag}")
            remaining = len(items) - len(lines)
            if remaining > 0:
                lines.append(f"... and {remaining} more")
            joined = "\n".join(lines)
            return joined[:1024]

        host = payload.get("host") or {}
        host_name = str(host.get("name") or "").strip()
        host_username = str(host.get("username") or "").strip()
        host_profile_url = f"https://x.com/{host_username}" if host_username else ""
        host_value = "—"
        if host_name or host_username:
            if host_name and host_username:
                host_value = f"{host_name} ([@{host_username}]({host_profile_url}))"
            elif host_username:
                host_value = f"[@{host_username}]({host_profile_url})"
            else:
                host_value = host_name

        cohosts = list(payload.get("cohosts") or [])
        speakers = list(payload.get("speakers") or [])
        listeners = list(payload.get("listeners") or [])
        session.listeners = int(payload.get("listener_count") or 0)
        session.participants = int(payload.get("participant_count") or 0)

        embed = discord.Embed(
            title=f"Participants · {payload.get('title', '(Sin título)')}",
            url=current_url,
            color=0x5865F2,
        )
        embed.add_field(name="Host", value=host_value[:1024], inline=False)
        embed.add_field(name=f"Co-hosts ({len(cohosts)})", value=render_users(cohosts), inline=False)
        embed.add_field(name=f"Speakers ({len(speakers)})", value=render_users(speakers), inline=False)
        embed.add_field(name=f"Listeners sampled ({len(listeners)})", value=render_users(listeners, limit=20), inline=False)
        embed.add_field(
            name="Counts",
            value=(
                f"Listeners now: {int(payload.get('listener_count') or 0)}\n"
                f"Participants total: {int(payload.get('participant_count') or 0)}\n"
                f"State: {str(payload.get('state') or 'unknown').upper()}"
            )[:1024],
            inline=False,
        )
        embed.set_footer(text=f"Space ID: {space_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

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
    @app_commands.describe(title="Optional bookmark title")
    async def mark_command(interaction: discord.Interaction, title: str = ""):
        await interaction.response.defer(thinking=True, ephemeral=False)
        session = sessions.guild(interaction.guild_id)
        now_utc = datetime.datetime.now(datetime.UTC)
        elapsed = session.elapsed()
        started_at_utc: datetime.datetime | None = None
        space_id = extract_space_id(session.current_url)
        if space_id:
            timing = await asyncio.to_thread(alert_monitor.scraper.get_space_timing, space_id)
            if timing.get("ok"):
                started_at_ms = int(timing.get("started_at_ms") or 0)
                if started_at_ms > 0:
                    started_at_utc = datetime.datetime.fromtimestamp(started_at_ms / 1000.0, datetime.UTC)
                    now_ms = int(now_utc.timestamp() * 1000)
                    elapsed = max(0, (now_ms - started_at_ms) // 1000)
        embed = discord.Embed(title="Bookmark saved", color=0xFEE75C)
        embed.add_field(name="Position", value=format_elapsed(elapsed), inline=True)
        if started_at_utc:
            embed.add_field(name="Space started (UTC)", value=started_at_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
            embed.add_field(name="Bookmarked (UTC)", value=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
        bookmark_title = str(title or "").strip() or session.title or "Untitled"
        embed.add_field(name="Title", value=bookmark_title[:250], inline=False)
        embed.add_field(name="URL", value=session.current_url or "—", inline=False)
        embed.timestamp = now_utc
        history.add_bookmark(
            guild_id=interaction.guild_id,
            channel_id=int(interaction.channel_id or 0),
            user_id=int(interaction.user.id),
            url=session.current_url or "",
            title=bookmark_title,
            position_sec=int(elapsed),
            note="Bookmark from /mark (space UTC delta)",
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

    @tree.command(name="bookmarks", description="List, delete or clear persistent bookmarks")
    @app_commands.describe(
        action="Action to perform",
        bookmark_id="Bookmark ID to delete (required for delete action)",
        limit="Number of bookmarks to list (1-20)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="list", value="list"),
            app_commands.Choice(name="delete", value="delete"),
            app_commands.Choice(name="clear", value="clear"),
        ]
    )
    async def bookmarks_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str] | None = None,
        bookmark_id: int = 0,
        limit: int = 10,
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        selected_action = (action.value if action else "list").strip().lower()

        if selected_action == "delete":
            if bookmark_id <= 0:
                await interaction.followup.send("Provide a valid `bookmark_id` to delete.", ephemeral=True)
                return
            deleted = history.delete_bookmark(interaction.guild_id, bookmark_id)
            if deleted:
                await interaction.followup.send(f"Bookmark `{bookmark_id}` deleted.", ephemeral=True)
            else:
                await interaction.followup.send(f"Bookmark `{bookmark_id}` not found.", ephemeral=True)
            return

        if selected_action == "clear":
            deleted_count = history.clear_bookmarks(interaction.guild_id)
            await interaction.followup.send(f"Cleared `{deleted_count}` bookmark(s).", ephemeral=True)
            return

        rows = history.latest_bookmarks(interaction.guild_id, limit=max(1, min(20, int(limit or 10))))
        if not rows:
            await interaction.followup.send("No bookmarks found.", ephemeral=True)
            return
        embed = discord.Embed(title="Bookmarks", color=0xFEE75C)
        for row_id, ts, channel_id, user_id, url, title, position_sec, note in rows:
            date_text = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")
            embed.add_field(
                name=f"ID {row_id} · {date_text} · {format_elapsed(position_sec)}",
                value=f"{title[:80]}\n{(url or '—')[:90]}\nUser {user_id} · Channel {channel_id}",
                inline=False,
            )
        embed.set_footer(text="Use /bookmarks action:delete bookmark_id:<id> to remove one.")
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

    @tree.command(name="alert_add", description="Add an X account to alert monitoring")
    @app_commands.describe(handle="X handle (@user) or numeric user ID")
    async def alert_add_command(interaction: discord.Interaction, handle: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        channel_id = int(interaction.channel_id or 0)
        ok, message = await alert_monitor.add_account(handle, channel_id=channel_id)
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="alert_remove", description="Remove monitored account by index, ID or handle")
    @app_commands.describe(value="List index (1..N), numeric user ID or @handle")
    async def alert_remove_command(interaction: discord.Interaction, value: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        channel_id = int(interaction.channel_id or 0)
        ok, message = alert_monitor.remove_account(value, channel_id=channel_id)
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="alert_list", description="Show monitored X accounts for alerts")
    async def alert_list_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        user_ids, username_map = alert_monitor.list_accounts_for_guild(int(interaction.guild_id or 0))
        if not user_ids:
            await interaction.followup.send("No hay cuentas monitoreadas en este servidor. Usa `/alert_add`.", ephemeral=True)
            return
        lines = []
        for idx, user_id in enumerate(user_ids, start=1):
            username = username_map.get(user_id, "")
            if username:
                lines.append(f"{idx}. @{username} | `{user_id}`")
            else:
                lines.append(f"{idx}. `{user_id}`")
        await interaction.followup.send("Cuentas monitoreadas en este servidor:\n" + "\n".join(lines), ephemeral=True)

    @tree.command(name="alert_map", description="Map user ID to @handle to improve live detection")
    @app_commands.describe(user_id="Numeric user ID", handle="X handle without @")
    async def alert_map_command(interaction: discord.Interaction, user_id: str, handle: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        ok, message = alert_monitor.map_username(user_id, handle)
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="alert_interval", description="Set alert polling interval in seconds")
    @app_commands.describe(seconds="Minimum 10 seconds")
    async def alert_interval_command(interaction: discord.Interaction, seconds: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if seconds < 10:
            await interaction.followup.send("⚠️ Minimum is 10 seconds.", ephemeral=True)
            return
        ok, message = alert_monitor.set_interval(seconds)
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="alert_status", description="Show current alert monitor status")
    async def alert_status_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        await interaction.followup.send(alert_monitor.status_text(), ephemeral=True)

    @tree.command(name="alert_check", description="Run an alert scan immediately")
    async def alert_check_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        result = await alert_monitor.poll_once(force=True)
        await interaction.followup.send(
            f"Scan done. sent={result['sent']} failed={result['failed']} skipped={result['skipped']}",
            ephemeral=True,
        )


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

