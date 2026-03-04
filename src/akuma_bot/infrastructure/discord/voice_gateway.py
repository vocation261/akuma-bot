from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time

import discord

from akuma_bot.domain.value_objects.queue_item import QueueItem
from akuma_bot.infrastructure.runtime.text_utils import format_elapsed

logger = logging.getLogger("akuma_bot")


class DiscordVoiceGateway:
    def __init__(self, config, sessions, media_resolver):
        self.config = config
        self.sessions = sessions
        self.media_resolver = media_resolver

    async def play(
        self,
        guild,
        user,
        url: str,
        mode: str = "recorded",
        force_vc_channel_id: int = 0,
        text_channel_id: int = 0,
    ) -> dict:
        if not self.media_resolver.is_space_url(url):
            return {"ok": False, "status": "error", "message": "Only X Space URLs are supported."}
        session = self.sessions.guild(guild.id)
        lock = self.sessions.play_lock(guild.id)
        if lock.locked():
            return {"ok": False, "status": "error", "message": "Another playback action is still in progress."}

        target_channel = None
        if force_vc_channel_id:
            target_channel = guild.get_channel(force_vc_channel_id)
        if target_channel is None:
            voice_state = getattr(user, "voice", None)
            target_channel = getattr(voice_state, "channel", None)
        if not target_channel:
            return {"ok": False, "status": "error", "message": "Join a voice channel first."}

        async with lock:
            if session.channel_status_overridden and session.last_vc_channel_id and session.last_vc_channel_id != int(getattr(target_channel, "id", 0)):
                await self._restore_channel_status(session, guild)

            stream_url = self.sessions.get_cached_stream(url, self.config.stream_url_cache_ttl)
            if not stream_url:
                stream_url = await asyncio.to_thread(
                    self.media_resolver.get_stream_url,
                    url,
                    3,
                    self.config.ytdlp_args,
                )
                if stream_url:
                    self.sessions.set_cached_stream(url, stream_url)

            if not stream_url:
                return {"ok": False, "status": "error", "message": "Failed to resolve stream URL."}

            voice_client, error = await self._get_or_connect_voice(guild, target_channel)
            if not voice_client:
                return {"ok": False, "status": "error", "message": error}
            if not voice_client.is_connected():
                return {"ok": False, "status": "error", "message": "Voice connected but not ready yet. Try again in a few seconds."}
            await self._ensure_self_deaf(guild, voice_client)

            if (voice_client.is_playing() or voice_client.is_paused()) and not session.restarting_track:
                session.queue.append(QueueItem(url=url, mode=mode))
                return {
                    "ok": True,
                    "status": "queued",
                    "message": f"Added to queue. Pending: {len(session.queue)}",
                    "embed": None,
                }

            if voice_client.is_playing() or voice_client.is_paused():
                session.suppress_after_events += 1
                voice_client.stop()

            before_options = "-loglevel error"
            if stream_url.startswith(("http://", "https://")):
                before_options = "-loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

            raw_source = discord.FFmpegPCMAudio(stream_url, before_options=before_options)
            source = discord.PCMVolumeTransformer(raw_source, volume=session.volume)
            loop = asyncio.get_running_loop()

            def after_playback(err):
                try:
                    loop.call_soon_threadsafe(asyncio.create_task, self._on_playback_end(guild, err))
                except Exception:
                    return

            try:
                voice_client.play(source, after=after_playback)
            except discord.ClientException as exc:
                return {"ok": False, "status": "error", "message": f"Audio start failed: {exc}"}
            except Exception as exc:
                return {"ok": False, "status": "error", "message": f"Unexpected audio start error: {exc}"}

            session.voice_client = voice_client
            session.current_url = url
            session.current_stream_url = stream_url
            session.play_start_time = time.time()
            session.elapsed_accumulated = 0.0
            session.is_live = mode == "live"
            session.idle_since = None
            session.title = ""
            session.host = ""
            session.host_handle = ""
            session.host_image = ""
            session.listeners = 0
            session.participants = 0
            session.duration_sec = 0
            session.duration_str = "Live" if mode == "live" else "—"
            session.status_label = "Live" if mode == "live" else "Recorded"
            session.owner_user_id = user.id
            session.last_vc_channel_id = target_channel.id
            if text_channel_id:
                session.last_text_channel_id = int(text_channel_id)
            session.last_play_url = url
            session.last_play_mode = mode
            session.last_play_vc_channel_id = target_channel.id
            session.max_play_retries = max(0, int(self.config.player_max_retries or 0))
            session.active_ytdlp_args = str(self.config.ytdlp_args or "")
            session.active_stream_cache_ttl = int(self.config.stream_url_cache_ttl or 300)
            session.channel_status_enabled = bool(self.config.vc_channel_status_enabled)
            session.channel_status_prefix = str(self.config.vc_channel_status_prefix or "🎙️ Space: ")
            session.restarting_track = False
            session.channel_status_warning = ""

            await self._set_channel_status(session, target_channel, "Live" if mode == "live" else "Playing")
            asyncio.create_task(self._fetch_and_update_metadata(guild, target_channel.id, url, mode))

            return {
                "ok": True,
                "status": "started",
                "message": "Playback started.",
                "embed": self._build_play_embed(url, mode, target_channel, user),
            }

    async def pause_toggle(self, guild) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        voice_client = session.voice_client
        if not voice_client or not voice_client.is_connected():
            return False, "Not connected to voice."
        if voice_client.is_playing():
            voice_client.pause()
            if session.play_start_time:
                session.elapsed_accumulated += max(0.0, time.time() - session.play_start_time)
            session.play_start_time = None
            return True, "Playback paused."
        if voice_client.is_paused():
            voice_client.resume()
            session.play_start_time = time.time()
            return True, "Playback resumed."
        return False, "No active audio source."

    async def stop(self, guild) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        await self._restore_channel_status(session, guild)
        voice_client = session.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.is_playing() or voice_client.is_paused():
                session.suppress_after_events += 1
                voice_client.stop()
            await voice_client.disconnect()
        session.voice_client = None
        session.reset()
        return True, "Disconnected."

    async def stop_with_reason(self, guild, reason: str) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        details = self._session_details_snapshot(session)
        notify_channel_id = int(session.last_text_channel_id or 0)
        _, message = await self.stop(guild)
        notice = self._build_end_notice(reason, details)
        await self._notify_text_channel(guild, notice, preferred_channel_id=notify_channel_id)
        return True, message

    async def mute_toggle(self, guild) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        voice_client = session.voice_client
        if not voice_client or not voice_client.is_connected():
            return False, "Not connected to voice."
        source = getattr(voice_client, "source", None)
        if not source or not hasattr(source, "volume"):
            return False, "No active voice source."
        current = float(getattr(source, "volume", 1.0))
        if current <= 0:
            target = max(0.01, session.volume if session.volume > 0 else 1.0)
            source.volume = target
            return True, f"Unmuted ({int(target * 100)}%)."
        session.volume = current
        source.volume = 0.0
        return True, "Muted."

    async def seek(self, guild, seconds_delta: int) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        lock = self.sessions.seek_lock(guild.id)
        if lock.locked():
            return False, "Another seek action is running."
        voice_client = session.voice_client
        if not voice_client or not voice_client.is_connected():
            return False, "Not connected to voice."
        if session.is_live:
            return False, "Seek is not available in live mode."
        if not session.current_url or not (voice_client.is_playing() or voice_client.is_paused()):
            return False, "No active track."
        async with lock:
            current = session.elapsed()
            target = max(0, current + int(seconds_delta))
            if session.duration_sec > 0:
                target = min(target, session.duration_sec - 1)
            return await self._seek_to_position(guild, target)

    async def seek_to(self, guild, target_sec: int) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        lock = self.sessions.seek_lock(guild.id)
        if lock.locked():
            return False, "Another seek action is running."
        voice_client = session.voice_client
        if not voice_client or not voice_client.is_connected():
            return False, "Not connected to voice."
        if session.is_live:
            return False, "Seek is not available in live mode."
        if not session.current_url or not (voice_client.is_playing() or voice_client.is_paused()):
            return False, "No active track."
        async with lock:
            target = max(0, int(target_sec or 0))
            if session.duration_sec > 0:
                target = min(target, session.duration_sec - 1)
            return await self._seek_to_position(guild, target)

    async def _get_or_connect_voice(self, guild: discord.Guild, target_channel: discord.VoiceChannel):
        me = getattr(guild, "me", None)
        if me:
            permissions = target_channel.permissions_for(me)
            if not getattr(permissions, "connect", False):
                return None, "Missing Connect permission in voice channel."
            if not getattr(permissions, "speak", False):
                return None, "Missing Speak permission in voice channel."
        existing = guild.voice_client
        if existing:
            if existing.is_connected():
                if existing.channel.id != target_channel.id:
                    try:
                        await existing.move_to(target_channel)
                    except discord.Forbidden:
                        return None, "No permission to move into that voice channel."
                    except Exception as exc:
                        return None, f"Move failed: {exc}"
                return existing, ""
            try:
                await existing.disconnect(force=True)
            except Exception:
                pass
        try:
            connected = await target_channel.connect(reconnect=True, timeout=30.0)
            for _ in range(20):
                if connected.is_connected():
                    return connected, ""
                await asyncio.sleep(0.25)
            return None, "Voice gateway is not ready after connect."
        except discord.Forbidden:
            return None, "No permission to connect to voice."
        except Exception as exc:
            return None, f"Voice connect failed: {exc}"

    async def _fetch_and_update_metadata(self, guild: discord.Guild, voice_channel_id: int, url: str, mode: str):
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self.media_resolver.get_media_info, url, self.config.ytdlp_args),
                timeout=15.0,
            )
        except Exception:
            info = {}
        if not info and self.media_resolver.is_space_url(url):
            try:
                info = await asyncio.to_thread(self.media_resolver.scrape_space_html, url)
            except Exception:
                info = {}
        session = self.sessions.guild(guild.id)
        if session.current_url != url:
            return
        if info.get("title"):
            session.title = info["title"]
        if info.get("uploader"):
            session.host = info["uploader"]
        if info.get("uploader_id"):
            session.host_handle = str(info["uploader_id"]).lstrip("@")
            if not session.host_image:
                session.host_image = self.media_resolver.host_avatar_url(session.host_handle)
        session.listeners = int(info.get("viewcount") or 0)
        duration = int(info.get("duration") or 0)
        is_live_flag, status_key = self.media_resolver.resolve_live_status(info, self.media_resolver.is_space_url(url))
        if mode == "live":
            if duration > 0 and status_key in ("ended", "unknown"):
                is_live_flag = False
                status_key = "ended"
            else:
                is_live_flag = True
                status_key = "live"
        elif mode == "recorded":
            is_live_flag = False
            if status_key == "live":
                status_key = "ended"
        session.is_live = is_live_flag
        session.duration_sec = duration
        status_map = {
            "live": "Live",
            "ended": "Recorded",
            "scheduled": "Scheduled",
            "unknown": "Unknown",
        }
        session.status_label = status_map.get(status_key, "Unknown")
        if duration > 0:
            session.duration_str = format_elapsed(duration)
        elif is_live_flag:
            session.duration_str = "Live"
        title_for_status = session.title or ("Live" if mode == "live" else "Playing")
        channel = guild.get_channel(int(voice_channel_id or 0)) if voice_channel_id else None
        await self._set_channel_status(session, channel, title_for_status)

    async def _seek_to_position(self, guild: discord.Guild, target: int) -> tuple[bool, str]:
        session = self.sessions.guild(guild.id)
        voice_client = session.voice_client
        current_before = session.elapsed()

        stream_url = ""
        if session.current_local_path and os.path.exists(session.current_local_path):
            stream_url = session.current_local_path
        else:
            stream_url = self.sessions.get_cached_stream(session.current_url, session.active_stream_cache_ttl)
            if not stream_url:
                stream_url = await asyncio.to_thread(
                    self.media_resolver.get_stream_url,
                    session.current_url,
                    3,
                    session.active_ytdlp_args,
                )
                if stream_url:
                    self.sessions.set_cached_stream(session.current_url, stream_url)

        if not stream_url:
            return False, "Could not resolve stream for seek."

        was_paused = voice_client.is_paused()
        if voice_client.is_playing() or voice_client.is_paused():
            session.suppress_after_events += 1
            voice_client.stop()

        before_options = f"-loglevel error -ss {target}"
        if str(stream_url).startswith(("http://", "https://")):
            before_options = f"-loglevel error -ss {target} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

        raw_source = discord.FFmpegPCMAudio(stream_url, before_options=before_options)
        source = discord.PCMVolumeTransformer(raw_source, volume=session.volume)
        loop = asyncio.get_running_loop()

        def after_playback(err):
            try:
                loop.call_soon_threadsafe(asyncio.create_task, self._on_playback_end(guild, err))
            except Exception:
                return

        voice_client.play(source, after=after_playback)
        if was_paused:
            voice_client.pause()
            session.play_start_time = None
        else:
            session.play_start_time = time.time()
        session.elapsed_accumulated = float(target)
        arrow = "Fast-forward" if target >= current_before else "Rewind"
        return True, f"{arrow} to {format_elapsed(target)}."

    async def _on_playback_end(self, guild: discord.Guild, error: Exception | None):
        session = self.sessions.guild(guild.id)
        if session.suppress_after_events > 0:
            session.suppress_after_events = max(0, session.suppress_after_events - 1)
            return
        voice_client = session.voice_client or getattr(guild, "voice_client", None)
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            return
        if session.queue:
            next_item = session.queue.pop(0)
            session.restarting_track = True
            try:
                await self.play(
                    guild,
                    guild.me,
                    next_item.url,
                    mode=next_item.mode,
                    force_vc_channel_id=session.last_vc_channel_id,
                    text_channel_id=session.last_text_channel_id,
                )
                session.play_retry_count = 0
            finally:
                session.restarting_track = False
            return
        if error and session.current_url and session.play_retry_count < session.max_play_retries:
            session.play_retry_count += 1
            session.restarting_track = True
            try:
                await self.play(
                    guild,
                    guild.me,
                    session.current_url,
                    mode=session.last_play_mode or ("live" if session.is_live else "recorded"),
                    force_vc_channel_id=session.last_vc_channel_id,
                    text_channel_id=session.last_text_channel_id,
                )
            finally:
                session.restarting_track = False
            return
        if session.is_live and session.current_url:
            await self.stop_with_reason(guild, reason="space_ended")

    async def _set_channel_status(self, session, channel, text: str):
        if not session.channel_status_enabled:
            return
        if not channel:
            return
        status_text = (f"{session.channel_status_prefix}{text}".strip().replace("\n", " "))[:120]
        if not status_text:
            return
        if session.original_channel_status is None:
            session.original_channel_status = getattr(channel, "status", None)
        try:
            await channel.edit(status=status_text, reason="akuma_bot playback status")
            session.channel_status_overridden = True
            session.current_channel_status = status_text
            session.channel_status_warning = ""
        except Exception:
            session.channel_status_warning = "Missing Manage Channels permission for channel status."

    async def _restore_channel_status(self, session, guild):
        if not session.channel_status_overridden:
            return
        channel_id = int(session.last_vc_channel_id or 0)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not channel:
            session.original_channel_status = None
            session.channel_status_overridden = False
            session.current_channel_status = ""
            return
        try:
            await channel.edit(status=session.original_channel_status or "", reason="akuma_bot restore channel status")
        except Exception:
            logger.debug("Could not restore channel status for channel %s", channel_id)
        finally:
            session.original_channel_status = None
            session.channel_status_overridden = False
            session.current_channel_status = ""

    async def _ensure_self_deaf(self, guild: discord.Guild, voice_client: discord.VoiceClient) -> None:
        try:
            me = getattr(guild, "me", None)
            me_voice = getattr(me, "voice", None) if me else None
            if me_voice and getattr(me_voice, "self_deaf", False):
                return
            await guild.change_voice_state(channel=voice_client.channel, self_mute=False, self_deaf=True)
        except Exception:
            return

    def _session_details_snapshot(self, session) -> dict:
        host_value = "—"
        if session.host:
            host_value = str(session.host)
        elif session.host_handle:
            host_value = f"@{session.host_handle}"
        return {
            "title": str(session.title or "Unknown Space"),
            "host": host_value,
            "participants": int(session.participants or 0),
            "listeners": int(session.listeners or 0),
            "duration": format_elapsed(session.elapsed()),
            "url": str(session.current_url or ""),
        }

    def _build_end_notice(self, reason: str, details: dict) -> str:
        if reason == "inactivity":
            return (
                "Session ended by inactivity: bot was alone in voice channel for 5 minutes.\n"
                f"Space: {details['title']}\n"
                f"Host: {details['host']}\n"
                f"Participants: {details['participants']:,}\n"
                f"Listeners: {details['listeners']:,}\n"
                f"Duration played: {details['duration']}\n"
                f"URL: {details['url'] or '—'}"
            )
        if reason == "space_ended":
            return (
                "Session ended: the Space stream has finished.\n"
                f"Space: {details['title']}\n"
                f"Host: {details['host']}\n"
                f"Participants: {details['participants']:,}\n"
                f"Listeners: {details['listeners']:,}\n"
                f"Duration played: {details['duration']}\n"
                f"URL: {details['url'] or '—'}"
            )
        return "Session ended."

    async def _notify_text_channel(self, guild: discord.Guild, message: str, preferred_channel_id: int = 0) -> None:
        session = self.sessions.guild(guild.id)
        channel = None
        if preferred_channel_id:
            channel = guild.get_channel(int(preferred_channel_id))
        if not channel and session.last_text_channel_id:
            channel = guild.get_channel(int(session.last_text_channel_id))
        if not channel:
            prefix = f"{guild.id}:"
            for key in list(self.sessions.panel_messages.keys()):
                if key.startswith(prefix):
                    try:
                        _, channel_id_str = key.split(":", 1)
                        channel = guild.get_channel(int(channel_id_str))
                    except Exception:
                        channel = None
                    if channel:
                        break
        if channel and hasattr(channel, "send"):
            try:
                await channel.send(message)
            except Exception:
                return
            return

    def _build_play_embed(self, url: str, mode: str, channel, user):
        color = 0xED4245 if mode == "live" else 0x57F287
        title = "Live stream" if mode == "live" else "Now playing"
        embed = discord.Embed(title=title, url=url, color=color)
        embed.description = "Use /dash to control playback."
        embed.add_field(name="Source", value=url[:200], inline=False)
        embed.add_field(name="Voice channel", value=getattr(channel, "name", "—"), inline=True)
        embed.add_field(name="Requested by", value=getattr(user, "display_name", "—"), inline=True)
        embed.timestamp = datetime.datetime.now(datetime.UTC)
        return embed

