from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import discord

from akuma_bot.application.alerts.use_cases import (
    add_account_to_channel,
    compute_delivery_key,
    list_accounts,
    list_accounts_for_guild,
    map_username as map_account_username,
    remove_account_from_channel,
    resolve_target_channels,
    set_interval as set_alert_interval,
)
from akuma_bot.infrastructure.alerts.config_store import AlertConfigRepository, AlertedSpaceRepository, sanitize_alert_config
from akuma_bot.infrastructure.alerts.services.space_query_service import XSpacesScraper

logger = logging.getLogger("akuma_bot")


def _format_count(value: Any) -> str:
    try:
        return str(int(value))
    except Exception:
        return "No disponible"


def build_space_alert_embed(space: dict[str, Any]) -> discord.Embed:
    state = str(space.get("state") or "").lower()
    if state in {"running", "live", ""}:
        state_label = "LIVE"
        title = "🚨 SPACE EN VIVO"
        description = "Se detectó un Space activo."
        color = 0x57F287
    elif state == "ended":
        state_label = "ENDED"
        title = "✅ SPACE FINALIZADO"
        description = "El Space terminó."
        color = 0xFEE75C
    else:
        state_label = state.upper() if state else "LIVE"
        title = "🚨 SPACE EN VIVO"
        description = "Se detectó actividad de Space."
        color = 0x57F287

    space_id = str(space.get("id") or "")
    space_url = f"https://x.com/i/spaces/{space_id}" if space_id else "https://x.com"
    username = str(space.get("username") or "").strip().lstrip("@")
    name = str(space.get("name") or "").strip() or username or "desconocido"
    creator_id = str(space.get("creator_id") or "desconocido")
    listeners = _format_count(space.get("listener_count"))
    followers = _format_count(space.get("followers_count"))
    title_value = str(space.get("title") or "(Sin título)")
    profile_url = f"https://x.com/{username}" if username else "https://x.com"

    embed = discord.Embed(title=title, description=description, url=space_url, color=color)
    embed.add_field(name="📡 Estado", value=state_label, inline=True)
    embed.add_field(name="👤 Host", value=f"[{name}]({profile_url})", inline=True)
    embed.add_field(name="🔖 Usuario", value=f"@{username}" if username else "desconocido", inline=True)
    embed.add_field(name="🆔 Host ID", value=creator_id, inline=True)
    embed.add_field(name="👥 Seguidores host", value=followers, inline=True)
    embed.add_field(name="🎧 Oyentes ahora", value=listeners, inline=True)
    embed.add_field(name="📝 Título", value=title_value[:1024], inline=False)
    embed.add_field(name="🔗 Enlace", value=space_url, inline=False)
    embed.set_footer(text="BotkumaX Alerts")
    embed.timestamp = datetime.now(timezone.utc)

    image_url = str(space.get("profile_image_url") or "").strip()
    if image_url:
        embed.set_thumbnail(url=image_url)
    return embed


class SpaceAlertMonitor:
    def __init__(
        self,
        client: discord.Client,
        config_repo: AlertConfigRepository | None = None,
        alerted_repo: AlertedSpaceRepository | None = None,
        scraper: XSpacesScraper | None = None,
    ) -> None:
        self.client = client
        self.config_repo = config_repo or AlertConfigRepository()
        self.alerted_repo = alerted_repo or AlertedSpaceRepository()
        self.scraper = scraper or XSpacesScraper()
        self._poll_lock = asyncio.Lock()
        self._loop_task: asyncio.Task | None = None
        self._last_check = 0.0

    def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if not self._loop_task:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    def _channel_ids(self) -> list[int]:
        raw_multi = (
            os.environ.get("DISCORD_ALERT_CHANNEL_IDS", "").strip()
            or os.environ.get("DISCORD_CHANNEL_IDS", "").strip()
        )
        raw_single = (
            os.environ.get("DISCORD_ALERT_CHANNEL_ID", "").strip()
            or os.environ.get("DISCORD_CHANNEL_ID", "").strip()
        )
        values: list[str] = []
        if raw_multi:
            values.extend([item.strip() for item in raw_multi.split(",") if item.strip()])
        if raw_single:
            values.append(raw_single)

        ids: list[int] = []
        for value in values:
            try:
                channel_id = int(value)
            except Exception:
                continue
            if channel_id and channel_id not in ids:
                ids.append(channel_id)
        return ids

    def _admin_channel_id(self) -> int:
        value = os.environ.get("DISCORD_ADMIN_CHANNEL_ID", "").strip()
        if not value:
            return 0
        try:
            return int(value)
        except Exception:
            return 0

    def _mention_everyone(self) -> bool:
        value = os.environ.get("DISCORD_ALERT_MENTION_EVERYONE", "true").strip().lower()
        return value in {"1", "true", "yes", "on"}

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("alert loop error: %s", exc, exc_info=True)

    async def poll_once(self, force: bool = False) -> dict[str, int]:
        if self._poll_lock.locked():
            return {"sent": 0, "failed": 0, "skipped": 0}

        async with self._poll_lock:
            config = self.config_repo.load()
            interval = int(config.get("check_interval", 600) or 600)
            user_ids = list(config.get("user_ids", []))
            now = time.monotonic()
            if not force and (now - self._last_check < interval):
                return {"sent": 0, "failed": 0, "skipped": 0}
            self._last_check = now
            if not user_ids:
                return {"sent": 0, "failed": 0, "skipped": 0}

            fallback_channel_ids = self._channel_ids()

            spaces = await self._fetch_spaces_with_retry(
                user_ids=user_ids,
                username_map=config.get("username_map", {}),
                attempts=int(config.get("retry_attempts", 3) or 3),
                backoff_seconds=float(config.get("retry_backoff_seconds", 1.0) or 1.0),
            )
            if not spaces:
                return {"sent": 0, "failed": 0, "skipped": 0}

            sent = 0
            failed = 0
            skipped = 0
            for item in spaces:
                space_id = str(item.get("id") or "")
                if not space_id:
                    skipped += 1
                    continue
                should_send, dedupe_key = compute_delivery_key(item, self.alerted_repo)

                if not should_send:
                    skipped += 1
                    continue

                channels = resolve_target_channels(
                    self.client,
                    item,
                    user_channels=config.get("user_channels", {}),
                    fallback_channel_ids=fallback_channel_ids,
                )
                if not channels:
                    logger.warning("Alert monitor: no valid channels for space %s", space_id)
                    skipped += 1
                    continue

                ok = await self._send_alert_to_channels(item, channels)
                if ok:
                    self.alerted_repo.add(dedupe_key)
                    sent += 1
                else:
                    failed += 1

            return {"sent": sent, "failed": failed, "skipped": skipped}

    def _target_channels_for_space(
        self,
        space: dict[str, Any],
        user_channels: dict[str, list[int]],
        fallback_channel_ids: list[int],
    ) -> list[discord.abc.Messageable]:
        return resolve_target_channels(self.client, space, user_channels, fallback_channel_ids)

    async def _fetch_spaces_with_retry(
        self,
        user_ids: list[str],
        username_map: dict[str, str],
        attempts: int,
        backoff_seconds: float,
    ) -> list[dict]:
        retries = max(1, min(6, int(attempts or 1)))
        backoff = max(0.0, min(10.0, float(backoff_seconds or 0.0)))
        for attempt in range(1, retries + 1):
            try:
                return await asyncio.to_thread(self.scraper.find_live_spaces_for_accounts, user_ids, username_map)
            except Exception as exc:
                logger.warning("check_spaces attempt %s/%s failed: %s", attempt, retries, exc)
                if attempt >= retries:
                    break
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
        return []

    async def _send_alert_to_channels(self, space: dict[str, Any], channels: list[discord.abc.Messageable]) -> bool:
        space_id = str(space.get("id") or "")
        embed = build_space_alert_embed(space)
        content = "@everyone 🚨🎙️🔥" if self._mention_everyone() else "🚨🎙️🔥"
        results = await asyncio.gather(
            *[
                channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(everyone=self._mention_everyone()),
                )
                for channel in channels
            ],
            return_exceptions=True,
        )
        ok_count = sum(1 for item in results if not isinstance(item, Exception))
        if ok_count == len(channels):
            logger.info("Alert sent for space %s to %s channel(s)", space_id, ok_count)
            return True

        logger.warning("Alert delivery partial/failed for %s: %s/%s", space_id, ok_count, len(channels))
        admin_channel_id = self._admin_channel_id()
        if admin_channel_id:
            admin_channel = self.client.get_channel(admin_channel_id)
            if admin_channel:
                try:
                    await admin_channel.send(
                        f"⚠️ Alerta de Space `{space_id}` enviada parcialmente: {ok_count}/{len(channels)} canales."
                    )
                except Exception:
                    pass
        return ok_count > 0

    def list_accounts(self) -> tuple[list[str], dict[str, str]]:
        return list_accounts(self.config_repo)

    def list_accounts_for_guild(self, guild_id: int) -> tuple[list[str], dict[str, str]]:
        return list_accounts_for_guild(self.config_repo, self.client, guild_id)

    async def add_account(self, value: str, channel_id: int | None = None) -> tuple[bool, str]:
        return await add_account_to_channel(self.config_repo, self.scraper, value, channel_id)

    def remove_account(self, value: str, channel_id: int | None = None) -> tuple[bool, str]:
        return remove_account_from_channel(self.config_repo, value, channel_id)

    def map_username(self, user_id: str, username: str) -> tuple[bool, str]:
        return map_account_username(self.config_repo, user_id, username)

    def set_interval(self, seconds: int) -> tuple[bool, str]:
        return set_alert_interval(self.config_repo, seconds)

    def status_text(self) -> str:
        config = sanitize_alert_config(self.config_repo.load())
        channel_ids = self._channel_ids()
        user_channels = config.get("user_channels", {})
        mapped_channels = sum(len(channels) for channels in user_channels.values())
        return (
            f"Vigiladas: {len(config.get('user_ids', []))}\n"
            f"Intervalo: {config.get('check_interval', 600)}s\n"
            f"Canales por cuenta: {mapped_channels}\n"
            f"Canales alerta: {channel_ids or ['(sin configurar)']}\n"
            f"Config: {self.config_repo.path}\n"
            f"Alertados: {self.alerted_repo.path}"
        )
