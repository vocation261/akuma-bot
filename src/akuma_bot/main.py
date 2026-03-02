from __future__ import annotations

import atexit
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import app_commands

from akuma_bot.infrastructure.discord.command_handlers import register_commands, register_tree_error_handler
from akuma_bot.infrastructure.discord.panel_gateway import DiscordPanelGateway
from akuma_bot.infrastructure.discord.voice_gateway import DiscordVoiceGateway
from akuma_bot.infrastructure.media.yt_dlp_resolver import YtDlpResolver
from akuma_bot.infrastructure.persistence.sqlite_history_repository import SqliteHistoryRepository
from akuma_bot.infrastructure.runtime.config import AppConfig, load_config
from akuma_bot.infrastructure.runtime.logging import setup_logging
from akuma_bot.infrastructure.runtime.session_store import SessionStore

logger = logging.getLogger("akuma_bot")
LOCK_FILE = Path(__file__).resolve().parents[2] / ".bot.lock"


@dataclass
class AppDeps:
    client: discord.Client
    tree: app_commands.CommandTree
    config: AppConfig
    sessions: SessionStore
    history_repository: SqliteHistoryRepository
    media_resolver: YtDlpResolver
    voice_gateway: DiscordVoiceGateway
    panel_gateway: DiscordPanelGateway
    start_ts: float


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_instance_lock() -> tuple[bool, int]:
    owner_pid = 0
    try:
        if LOCK_FILE.exists():
            raw = LOCK_FILE.read_text(encoding="utf-8").strip()
            owner_pid = int(raw) if raw.isdigit() else 0
            if owner_pid and owner_pid != os.getpid() and pid_exists(owner_pid):
                return False, owner_pid
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True, 0
    except Exception:
        return True, 0


def release_instance_lock() -> None:
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        return


def build_app() -> AppDeps:
    config = load_config()
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.guilds = True
    intents.members = False
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    sessions = SessionStore()
    history_repository = SqliteHistoryRepository(config.history_db_path)
    media_resolver = YtDlpResolver()
    voice_gateway = DiscordVoiceGateway(config=config, sessions=sessions, media_resolver=media_resolver)
    panel_gateway = DiscordPanelGateway(sessions=sessions, voice_gateway=voice_gateway)
    deps = AppDeps(
        client=client,
        tree=tree,
        config=config,
        sessions=sessions,
        history_repository=history_repository,
        media_resolver=media_resolver,
        voice_gateway=voice_gateway,
        panel_gateway=panel_gateway,
        start_ts=time.time(),
    )
    register_commands(tree, deps)
    register_tree_error_handler(tree)
    return deps


async def idle_disconnect_loop(deps: AppDeps, idle_seconds: int = 60, interval: float = 5.0):
    while True:
        try:
            await asyncio.sleep(interval)
            if not deps.client.is_ready():
                continue
            now = time.time()
            for guild in list(deps.client.guilds):
                session = deps.sessions.guild(guild.id)
                voice_client = session.voice_client or getattr(guild, "voice_client", None)
                if not voice_client or not voice_client.is_connected():
                    session.idle_since = None
                    continue
                if voice_client.is_playing() or voice_client.is_paused():
                    session.idle_since = None
                    continue
                if session.idle_since is None:
                    session.idle_since = now
                    continue
                if (now - session.idle_since) >= float(idle_seconds):
                    _, message = await deps.voice_gateway.stop(guild)
                    logger.info("Auto-disconnect in guild %s: %s", guild.id, message)
                    session.idle_since = None
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("idle_disconnect_loop error: %s", exc)


async def run_bot(deps: AppDeps):
    idle_task: asyncio.Task | None = None

    @deps.client.event
    async def on_ready():
        nonlocal idle_task
        if deps.config.sync_guild_id:
            guild_obj = discord.Object(id=int(deps.config.sync_guild_id))
            await deps.tree.sync(guild=guild_obj)
        else:
            await deps.tree.sync()
        asyncio.create_task(deps.panel_gateway.autorefresh_loop(deps.client))
        if idle_task is None or idle_task.done():
            idle_task = asyncio.create_task(idle_disconnect_loop(deps, deps.config.idle_disconnect_seconds))
        logger.info("Bot ready: %s (ID: %s)", deps.client.user, deps.client.user.id if deps.client.user else "-")
        logger.info("Guilds: %s", len(deps.client.guilds))

    logger.info("Starting Discord bot...")
    await deps.client.start(deps.config.discord_token)


async def main():
    setup_logging()
    lock_ok, owner_pid = acquire_instance_lock()
    if not lock_ok:
        print(f"Another bot instance is already running (PID: {owner_pid}).")
        sys.exit(1)
    atexit.register(release_instance_lock)
    try:
        deps = build_app()
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)
    try:
        await run_bot(deps)
    finally:
        release_instance_lock()


if __name__ == "__main__":
    asyncio.run(main())

