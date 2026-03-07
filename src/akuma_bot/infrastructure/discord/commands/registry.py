from __future__ import annotations

import datetime
import asyncio
import logging
import time
import shutil
import tempfile
from pathlib import Path

import discord
from discord import app_commands

from akuma_bot.infrastructure.runtime.text_utils import (
    build_filename_from_display_label,
    embed_color,
    extract_space_id,
    format_duration_hms,
    format_elapsed,
    probe_audio_duration_seconds,
    safe_filename,
    validate_playable_url,
)
from akuma_bot.infrastructure.transcription import download_space_audio, transcribe_audio_batch
from akuma_bot.infrastructure.transcription.downloader import fetch_space_metadata
from akuma_bot.infrastructure.transcription.transcriber import split_audio_max_1h
from akuma_bot.infrastructure.security import InputValidator, ValidationError

logger = logging.getLogger("akuma_bot")


def _build_base_label(meta: dict[str, object]) -> str:
    account = safe_filename(str(meta.get("twitter_account") or "@unknown"), 40, "unknown")
    title = safe_filename(str(meta.get("space_title") or "Untitled Space"), 80, "untitled")
    date_text = safe_filename(str(meta.get("space_date") or "unknown-date"), 20, "unknown")
    space_id = safe_filename(str(meta.get("space_id") or "unknown-space"), 40, "unknown")
    return f"[{account}]-[{title}]-[{date_text}]-[{space_id}]"


def _build_display_label(meta: dict[str, object], part_index: int | None = None, total_parts: int | None = None, part_start_sec: int = 0, part_duration_sec: int = 3600) -> str:
    host = str(meta.get("twitter_account") or "unknown").lstrip("@")
    title = str(meta.get("space_title") or "Untitled Space")
    date_text = str(meta.get("space_date") or "unknown-date")
    start_text = str(meta.get("space_started_at") or "unknown")
    space_id = str(meta.get("space_id") or "unknown-space")
    duration_text = format_duration_hms(int(meta.get("duration_sec") or 0))

    base = (
        f"HOST: {host} - TITLE: {title} - SPACE ID: {space_id} - DATE: {start_text} - "
        f"DURATION: {duration_text}"
    )

    if part_index is not None and total_parts is not None and total_parts > 1:
        part_end_sec = part_start_sec + part_duration_sec
        part_start_text = format_duration_hms(part_start_sec)
        part_end_text = format_duration_hms(part_end_sec)
        return f"{base} - PART {part_index}/{total_parts} - {part_start_text} - {part_end_text}"
    return base


async def _safe_message_update(
    message: discord.WebhookMessage | discord.Message,
    content: str,
    channel: discord.abc.Messageable | None = None,
) -> discord.WebhookMessage | discord.Message:
    try:
        await message.edit(content=content)
        return message
    except discord.errors.HTTPException as e:
        if channel and (e.code == 50027 or e.status == 401):
            try:
                new_msg = await channel.send(content)
                return new_msg
            except Exception:
                pass
        raise


async def _safe_followup_send(
    interaction: discord.Interaction,
    content: str,
    channel: discord.abc.Messageable | None = None,
    *,
    ephemeral: bool = False,
    file: discord.File | None = None,
    file_path: str | Path | None = None,
    filename: str | None = None,
) -> discord.WebhookMessage | discord.Message:
    try:
        kwargs = {"ephemeral": ephemeral}
        if file_path is not None:
            path_obj = Path(file_path)
            kwargs["file"] = discord.File(str(path_obj), filename=filename or path_obj.name)
        elif file is not None:
            kwargs["file"] = file
        return await interaction.followup.send(content, **kwargs)
    except discord.errors.HTTPException as e:
        if channel and (e.code == 50027 or e.status == 401):
            channel_kwargs = {}
            if file_path is not None:
                path_obj = Path(file_path)
                channel_kwargs["file"] = discord.File(str(path_obj), filename=filename or path_obj.name)
            elif file is not None:
                channel_kwargs["file"] = file
            return await channel.send(content, **channel_kwargs)
        raise


def _write_transcript_txt(
    output_dir: Path,
    base_label: str,
    display_label: str,
    transcription_results: list[tuple[str, str]],
    max_bytes: int = 10 * 1024 * 1024,
) -> tuple[Path, bool]:
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = safe_filename(f"{display_label}_{timestamp}", 150, "transcript") + ".txt"
    txt_path = output_dir / filename

    sections: list[str] = [
        "======= AUTOMATIC TRANSCRIPTION REPORT=======\n",
        f"GENERATED AT (DATETIME):\n",
        f"{datetime.datetime.now().isoformat()}\n",
        f"GENERATED AT (UTC):\n",
        f"{datetime.datetime.utcnow().isoformat()}\n",
        f"GENERATED AT (DATETIME): {datetime.datetime.now().isoformat()}\n",
        f"GENERATED AT (UTC): {datetime.datetime.utcnow().isoformat()}\n",
        f"SOURCE:\n",
        f"{display_label}\n",
        "=============================================\n\n",
    ]
    for display_label, transcript_body in transcription_results:
        body = transcript_body.strip() or "(no content detected)"
        sections.append(f"\n{body}\n")

    full_text = "".join(sections)
    full_bytes = full_text.encode("utf-8")
    was_truncated = False

    if len(full_bytes) > max_bytes:
        truncation_note = "\n\n[TRUNCATED] Transcript was limited to 10MB.\n"
        truncation_note_bytes = truncation_note.encode("utf-8")
        allowed = max(0, max_bytes - len(truncation_note_bytes))
        trimmed = full_bytes[:allowed]
        trimmed_text = trimmed.decode("utf-8", errors="ignore")
        full_text = trimmed_text + truncation_note
        was_truncated = True

    txt_path.write_text(full_text, encoding="utf-8")
    return txt_path, was_truncated


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
        user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
        history.log("discord:live", url, "ok", "Playback started", guild_id=interaction.guild_id, channel_id=interaction.channel_id, user_id=interaction.user.id, user_name=interaction.user.name or "", user_tag=user_tag, event_type="play_audio")
        try:
            panel_message, updated = await panel_gateway.upsert(interaction.guild, interaction.channel, note="Playback started (LIVE)")
            if panel_message:
                status = "updated" if updated else "sent"
                await interaction.followup.send(f"Panel {status}: {panel_message.jump_url}", ephemeral=True)
        except Exception:
            pass

    @tree.command(name="transcript", description="Download and transcribe recorded X Space")
    @app_commands.describe(url="Recorded X Space URL (x.com/i/spaces/...)")
    async def transcript_command(interaction: discord.Interaction, url: str):
        await interaction.response.defer(thinking=True)
        event_loop = asyncio.get_running_loop()

        try:
            validated_url = InputValidator.validate_url(url)
        except ValidationError as e:
            await interaction.followup.send(f"❌ Invalid URL: {str(e)}", ephemeral=True)
            return

        ok_url, error = validate_playable_url(validated_url)
        if not ok_url:
            await interaction.followup.send(error, ephemeral=True)
            return

        temp_dir = Path(tempfile.mkdtemp(prefix="transcript_"))
        channel = interaction.channel

        try:
            status_msg = await interaction.followup.send("⏬ Resolving Space metadata...", ephemeral=False)

            ok_meta, meta_message, metadata = await asyncio.to_thread(fetch_space_metadata, validated_url)
            if not ok_meta or not metadata:
                status_msg = await _safe_message_update(status_msg, f"❌ {meta_message}", channel)
                return

            base_label = _build_base_label(metadata)
            
            space_info = {
                "twitter_account": str(metadata.get("twitter_account") or "unknown"),
                "space_title": str(metadata.get("space_title") or "Untitled"),
                "space_date": str(metadata.get("space_date") or "unknown"),
                "space_started_at": str(metadata.get("space_started_at") or "unknown"),
                "space_id": str(metadata.get("space_id") or "unknown"),
                "duration_sec": int(metadata.get("duration_sec", 0)),
            }
            
            def get_space_info_short() -> str:
                return _build_display_label(space_info)

            status_msg = await _safe_message_update(status_msg, f"⏬ Downloading Space audio...\n{get_space_info_short()}", channel)

            msg_state = {"current_msg": status_msg}
            download_progress_state = {"step": -1, "last_percent": 0}

            def report_download_progress(percent: int):
                bounded = max(0, min(100, int(percent)))
                download_progress_state["last_percent"] = bounded
                step = bounded // 5
                if step <= download_progress_state["step"]:
                    return
                download_progress_state["step"] = step
                message = f"⏬ Space download: {step * 5}%\n{get_space_info_short()}"
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        _safe_message_update(msg_state["current_msg"], message, channel),
                        event_loop,
                    )
                    msg_state["current_msg"] = future.result(timeout=10)
                except Exception:
                    pass

            download_task = asyncio.create_task(
                asyncio.to_thread(
                    download_space_audio,
                    validated_url,
                    temp_dir,
                    audio_format="mp3",
                    progress_callback=report_download_progress,
                )
            )

            started_download_ts = time.time()
            while not download_task.done():
                await asyncio.sleep(60)
                if download_task.done():
                    break
                elapsed = int(time.time() - started_download_ts)
                last_percent = int(download_progress_state.get("last_percent", 0))
                try:
                    status_msg = await _safe_message_update(
                        msg_state["current_msg"],
                        f"⏳ Download in progress... {last_percent}% · {format_elapsed(elapsed)}\n{get_space_info_short()}",
                        channel,
                    )
                    msg_state["current_msg"] = status_msg
                except Exception:
                    pass

            success, message, audio_path = await download_task

            if not success or not audio_path:
                status_msg = await _safe_message_update(msg_state["current_msg"], f"❌ {message}", channel)
                return

            if space_info["duration_sec"] <= 0:
                probed_duration = await asyncio.to_thread(probe_audio_duration_seconds, audio_path)
                if probed_duration > 0:
                    space_info["duration_sec"] = probed_duration
                    metadata["duration_sec"] = probed_duration

            status_msg = await _safe_message_update(msg_state["current_msg"], f"⏬ Space download: 100%\n{get_space_info_short()}", channel)
            msg_state["current_msg"] = status_msg

            # Split audio
            status_msg = await _safe_message_update(status_msg, f"✂️ Splitting audio into max 1-hour parts...\n{get_space_info_short()}", channel)
            split_dir = temp_dir / "parts"
            ok_split, split_message, parts, total_duration = await asyncio.to_thread(
                split_audio_max_1h,
                audio_path,
                split_dir,
                3600,
                96,
            )
            if not ok_split or not parts:
                status_msg = await _safe_message_update(status_msg, f"❌ {split_message}", channel)
                return

            total_parts = len(parts)

            if space_info["duration_sec"] == 0 and total_duration:
                space_info["duration_sec"] = int(total_duration)
                metadata["duration_sec"] = int(total_duration)

            duration_text = format_duration_hms(space_info["duration_sec"])
            status_msg = await _safe_message_update(
                status_msg,
                f"✅ Audio prepared in {total_parts} part(s). Duration: {duration_text}. Starting upload...",
                channel,
            )

            part_files: list[tuple[int, Path, str]] = []
            for idx, part_path in enumerate(parts, start=1):
                is_single = total_parts == 1
                part_start_sec = (idx - 1) * 3600
                if idx == total_parts:
                    remaining_sec = space_info["duration_sec"] - part_start_sec
                    part_duration_sec = min(3600, max(1, remaining_sec))
                else:
                    part_duration_sec = 3600

                display_label = _build_display_label(
                    metadata,
                    part_index=(None if is_single else idx),
                    total_parts=(None if is_single else total_parts),
                    part_start_sec=part_start_sec,
                    part_duration_sec=part_duration_sec,
                )
                part_filename = build_filename_from_display_label(display_label)
                if total_parts > 1:
                    part_filename = f"part_{idx:02d}_{part_filename}"

                named_part_path = part_path.with_name(part_filename)
                part_path.rename(named_part_path)

                part_size_mb = named_part_path.stat().st_size / (1024 * 1024)
                if part_size_mb > 50:
                    await _safe_followup_send(
                        interaction,
                        f"❌ Part {idx} exceeds 50MB ({part_size_mb:.1f}MB).",
                        channel,
                        ephemeral=True,
                    )
                    return

                await _safe_followup_send(
                    interaction,
                    f"📤 Uploading audio {idx}/{total_parts}:\n{display_label}",
                    channel,
                    file_path=named_part_path,
                    filename=part_filename,
                    ephemeral=False,
                )
                
                part_files.append((idx, named_part_path, display_label))

            transcription_results = []
            total_segments = 0
            
            # Create new message for transcription progress
            transcribe_msg = await _safe_followup_send(
                interaction,
                f"🎤 Starting transcription ({total_parts} part(s))...\n{get_space_info_short()}",
                channel,
                ephemeral=False,
            )
            transcribe_msg_state = {"current_msg": transcribe_msg}
            
            # Prepare batch for transcription
            audio_batch: list[tuple[Path, int]] = [
                (named_part_path, (idx - 1) * 3600)
                for idx, named_part_path, _ in part_files
            ]

            def report_batch_progress(part_idx: int, total: int, percent: int):
                bounded = max(0, min(100, int(percent)))
                step = bounded // 10
                message = f"⏳ Transcription: part {part_idx}/{total} at {step * 10}%\n{get_space_info_short()}"
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        _safe_message_update(transcribe_msg_state["current_msg"], message, channel),
                        event_loop,
                    )
                    transcribe_msg_state["current_msg"] = future.result(timeout=10)
                except Exception:
                    pass

            # Transcribe all parts with single model instance
            batch_results = await asyncio.to_thread(
                transcribe_audio_batch,
                audio_batch,
                temp_dir,
                model_size="tiny",
                language="es",
                device="cpu",
                compute_type="int8",
                progress_callback=report_batch_progress,
            )

            # Process results
            for (idx, named_part_path, display_label), (success, transcribe_message, result) in zip(part_files, batch_results):
                if not success or not result:
                    await _safe_message_update(transcribe_msg_state["current_msg"], f"❌ {transcribe_message}", channel)
                    return
                total_segments += int(result.line_count)
                transcription_results.append((display_label, result.full_text.strip() or "(no content detected)"))

            transcript_txt_path, was_truncated = await asyncio.to_thread(
                _write_transcript_txt,
                temp_dir,
                base_label,
                get_space_info_short(),
                transcription_results,
                10 * 1024 * 1024,
            )

            await _safe_followup_send(
                interaction,
                f"✅ Transcription completed.\n{get_space_info_short()}",
                channel,
                file_path=transcript_txt_path,
                filename=transcript_txt_path.name,
                ephemeral=False,
            )

            safe_duration = float(total_duration or metadata.get("duration_sec") or 0)
            user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
            history.log_audit_event(
                event_type="transcript",
                guild_id=interaction.guild_id,
                channel_id=int(interaction.channel_id or 0),
                user_id=int(interaction.user.id),
                user_name=interaction.user.name or "",
                user_tag=user_tag,
                resource_name=url,
                details=(
                    f"Space: {base_label}, Duration: {safe_duration:.1f}s, "
                    f"Parts: {total_parts}, Segments: {total_segments}"
                ),
            )

            await _safe_followup_send(
                interaction,
                f"✅ Process complete. Segments transcribed: {total_segments}.",
                channel,
                ephemeral=False,
            )

        except Exception as e:
            logger.exception(f"Transcript command error: {e}")
            try:
                await _safe_followup_send(interaction, f"❌ Error: {str(e)[:200]}", channel, ephemeral=True)
            except discord.errors.HTTPException:
                if channel:
                    try:
                        await channel.send(f"❌ Transcription error: {str(e)[:200]}")
                    except Exception:
                        pass

        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
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
            title=f"Participants · {payload.get('title', '(Untitled)')}",
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

    @tree.command(name="mark", description="Save bookmark at current position")
    @app_commands.describe(title="Optional bookmark title")
    async def mark_command(interaction: discord.Interaction, title: str = ""):
        await interaction.response.defer(thinking=True, ephemeral=False)
        
        # Validate title
        try:
            bookmark_title = InputValidator.validate_bookmark_title(title)
        except ValidationError as e:
            await interaction.followup.send(f"❌ Invalid title: {str(e)}", ephemeral=True)
            return
        
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
        user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
        history.add_bookmark(
            guild_id=interaction.guild_id,
            channel_id=int(interaction.channel_id or 0),
            user_id=int(interaction.user.id),
            url=session.current_url or "",
            title=bookmark_title,
            position_sec=int(elapsed),
            note="Bookmark from /mark (space UTC delta)",
            user_name=interaction.user.name or "",
            user_tag=user_tag,
        )
        # Log audit event for bookmark creation
        history.log_audit_event(
            event_type="bookmark_add",
            guild_id=interaction.guild_id,
            channel_id=int(interaction.channel_id or 0),
            user_id=int(interaction.user.id),
            user_name=interaction.user.name or "",
            user_tag=user_tag,
            resource_name=bookmark_title,
            details=f"Position: {elapsed}s, URL: {session.current_url or 'N/A'}",
        )
        await interaction.followup.send(embed=embed)

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
            # Validate bookmark ID
            try:
                validated_bookmark_id = InputValidator.validate_bookmark_id(bookmark_id)
            except ValidationError as e:
                await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
                return
            
            deleted = history.delete_bookmark(interaction.guild_id, validated_bookmark_id)
            if deleted:
                user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
                history.log_audit_event(
                    event_type="bookmark_delete",
                    guild_id=interaction.guild_id,
                    channel_id=int(interaction.channel_id or 0),
                    user_id=int(interaction.user.id),
                    user_name=interaction.user.name or "",
                    user_tag=user_tag,
                    resource_id=str(validated_bookmark_id),
                    details=f"Bookmark {validated_bookmark_id} deleted",
                )
                await interaction.followup.send(f"Bookmark `{validated_bookmark_id}` deleted.", ephemeral=True)
            else:
                await interaction.followup.send(f"Bookmark `{validated_bookmark_id}` not found.", ephemeral=True)
            return

        if selected_action == "clear":
            deleted_count = history.clear_bookmarks(interaction.guild_id)
            if deleted_count > 0:
                user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
                history.log_audit_event(
                    event_type="bookmark_clear",
                    guild_id=interaction.guild_id,
                    channel_id=int(interaction.channel_id or 0),
                    user_id=int(interaction.user.id),
                    user_name=interaction.user.name or "",
                    user_tag=user_tag,
                    details=f"Cleared {deleted_count} bookmarks",
                )
            await interaction.followup.send(f"Cleared `{deleted_count}` bookmark(s).", ephemeral=True)
            return

        # Validate limit
        try:
            validated_limit = InputValidator.validate_limit(limit, max_limit=20)
        except ValidationError as e:
            await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
            return

        rows = history.latest_bookmarks(interaction.guild_id, limit=validated_limit)
        if not rows:
            await interaction.followup.send("No bookmarks found.", ephemeral=True)
            return
        embed = discord.Embed(title="Bookmarks", color=0xFEE75C)
        for row_id, ts, channel_id, user_id, url, title, position_sec, note, user_name, user_tag in rows:
            date_text = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")
            user_display = user_tag if user_tag else f"ID {user_id}" if user_id else "Unknown"
            embed.add_field(
                name=f"ID {row_id} · {date_text} · {format_elapsed(position_sec)}",
                value=f"{title[:80]}\n{(url or '—')[:90]}\n{user_display} · Channel {channel_id}",
                inline=False,
            )
        embed.set_footer(text="Use /bookmarks action:delete bookmark_id:<id> to remove one.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="health", description="Operational health snapshot and bot diagnostics")
    async def health_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = sessions.guild(interaction.guild_id)
        voice_client = session.voice_client
        uptime = int(time.time() - start_ts)
        embed = discord.Embed(title="Health & Diagnostics", color=0x57F287)
        
        # Bot & System Info
        embed.add_field(name="Bot", value=str(deps.client.user), inline=True)
        embed.add_field(name="Uptime", value=format_elapsed(uptime), inline=True)
        embed.add_field(name="Latency", value=f"{round(deps.client.latency * 1000)}ms", inline=True)
        embed.add_field(name="Guilds", value=str(len(deps.client.guilds)), inline=True)
        
        # Voice & Audio Status
        embed.add_field(name="Voice", value="connected" if (voice_client and voice_client.is_connected()) else "disconnected", inline=True)
        embed.add_field(name="Audio", value="playing" if (voice_client and voice_client.is_playing()) else ("paused" if (voice_client and voice_client.is_paused()) else "stopped"), inline=True)
        embed.add_field(name="Queue", value=str(len(session.queue)), inline=True)
        embed.add_field(name="Retries", value=f"{session.play_retry_count}/{session.max_play_retries}", inline=True)
        embed.add_field(name="Channel status", value="on" if session.channel_status_enabled else "off", inline=True)
        
        # Current Session Details (if playing)
        if voice_client and voice_client.is_connected() and session.current_url:
            embed.add_field(name="Mode", value="LIVE" if session.is_live else "REC", inline=True)
            embed.add_field(name="Title", value=(session.title or "—")[:100], inline=False)
            embed.add_field(name="Elapsed", value=format_elapsed(session.elapsed()), inline=True)
            embed.add_field(name="Duration", value=session.duration_str or "—", inline=True)
            embed.add_field(name="URL", value=(session.current_url or "—")[:100], inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="alert_add", description="Add an X account to alert monitoring")
    @app_commands.describe(handle="X handle (@user) or numeric user ID")
    async def alert_add_command(interaction: discord.Interaction, handle: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # Validate handle
        try:
            validated_handle = InputValidator.validate_handle(handle)
        except ValidationError as e:
            await interaction.followup.send(f"❌ Invalid handle: {str(e)}", ephemeral=True)
            return
        
        channel_id = int(interaction.channel_id or 0)
        ok, message = await alert_monitor.add_account(validated_handle, channel_id=channel_id)
        if ok:
            user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
            history.log_audit_event(
                event_type="alert_add",
                guild_id=interaction.guild_id,
                channel_id=channel_id,
                user_id=int(interaction.user.id),
                user_name=interaction.user.name or "",
                user_tag=user_tag,
                resource_name=str(handle),
                details=message,
            )
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="alert_remove", description="Remove monitored account by index, ID or handle")
    @app_commands.describe(value="List index (1..N), numeric user ID or @handle")
    async def alert_remove_command(interaction: discord.Interaction, value: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # Validate value (index, ID or handle)
        try:
            validated_value = InputValidator.validate_string(value, "Value", max_length=200, allow_empty=False)
        except ValidationError as e:
            await interaction.followup.send(f"❌ Invalid value: {str(e)}", ephemeral=True)
            return
        
        channel_id = int(interaction.channel_id or 0)
        ok, message = alert_monitor.remove_account(validated_value, channel_id=channel_id)
        if ok:
            user_tag = f"@{interaction.user.name}" if interaction.user.name else ""
            history.log_audit_event(
                event_type="alert_remove",
                guild_id=interaction.guild_id,
                channel_id=channel_id,
                user_id=int(interaction.user.id),
                user_name=interaction.user.name or "",
                user_tag=user_tag,
                resource_id=str(value),
                details=message,
            )
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="alert_list", description="Show monitored X accounts for alerts")
    async def alert_list_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        user_ids, username_map = alert_monitor.list_accounts_for_guild(int(interaction.guild_id or 0))
        if not user_ids:
            await interaction.followup.send("No monitored accounts in this server. Use `/alert_add`.", ephemeral=True)
            return
        lines = []
        for idx, user_id in enumerate(user_ids, start=1):
            username = username_map.get(user_id, "")
            if username:
                lines.append(f"{idx}. @{username} | `{user_id}`")
            else:
                lines.append(f"{idx}. `{user_id}`")
        await interaction.followup.send("Monitored accounts in this server:\n" + "\n".join(lines), ephemeral=True)

    @tree.command(name="alert_interval", description="Set alert polling interval in seconds")
    @app_commands.describe(seconds="Minimum 10 seconds")
    async def alert_interval_command(interaction: discord.Interaction, seconds: int):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # Validate interval
        try:
            validated_seconds = InputValidator.validate_alert_interval(seconds)
        except ValidationError as e:
            await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
            return
        
        ok, message = alert_monitor.set_interval(validated_seconds)
        await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

    @tree.command(name="audit_log", description="Show audit log of recent actions (bookmarks, alerts, etc.)")
    @app_commands.describe(
        event_type="Filter by event type (bookmark_add, bookmark_delete, alert_add, alert_remove, etc.)",
        limit="Number of entries to show (1-30)",
    )
    async def audit_log_command(interaction: discord.Interaction, event_type: str = "", limit: int = 10):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # Validate event_type
        validated_event_type: str | None = None
        if event_type:
            try:
                validated_event_type = InputValidator.validate_event_type(event_type)
            except ValidationError as e:
                await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
                return
        
        # Validate limit
        try:
            validated_limit = InputValidator.validate_limit(limit, max_limit=30)
        except ValidationError as e:
            await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
            return
        
        evt_filter = validated_event_type or None
        rows = history.latest_audit_events(guild_id=interaction.guild_id, event_type=evt_filter, limit=validated_limit)
        if not rows:
            await interaction.followup.send("No audit log entries.", ephemeral=True)
            return
        embed = discord.Embed(title="Audit Log", color=0x9C27B0)
        for entry_id, ts, evt_type, gid, cid, uid, uname, utag, res_id, res_name, details in rows:
            date_text = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M:%S")
            user_display = utag if utag else f"ID {uid}" if uid else "System"
            embed.add_field(
                name=f"{evt_type} · {date_text}",
                value=f"{user_display}\n{res_name or res_id or '—'}\n{details[:80] if details else '—'}",
                inline=False,
            )
        embed.set_footer(text="Audit log for administrative actions")
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

