# BotkumaX

Discord bot for:
- playing X Spaces in a voice channel;
- scraping participants from the current Space (host, co-hosts, speakers, listeners);
- controlling playback with slash commands;
- storing history in SQLite;
- monitoring X accounts and sending automatic live Space alerts.

## Quick overview

BotkumaX runs two flows in one process:
1. **Voice player**: joins voice channels and plays live/recorded Spaces.
2. **Alert monitor**: watches X accounts and posts alert embeds in Discord channels.

This avoids running separate bots/services for audio and alerts.

## Slash commands (current)

### Playback and utilities

- `/live <url>`: play a live X Space in your voice channel.
- `/transcript <url>`: download and transcribe a recorded X Space to MP3 + TXT.
- `/participants`: scrape and show host, co-hosts, speakers, and listeners for the active Space.
- `/dash`: create/update the interactive bot control panel.
- `/dc`: disconnect the bot from voice.
- `/mute`: toggle bot audio mute.
- `/resume`: resume playback when paused.
- `/forward <minutes>`: skip forward by 1, 5, 10, 30, or 60 minutes.
- `/rewind <minutes>`: rewind by 1, 5, or 30 minutes.
- `/now`: show currently playing item.
- `/mark`: save a bookmark at current position.
- `/bookmarks`: list (`action:list`), delete (`action:delete bookmark_id:<id>`), or clear (`action:clear`) bookmarks.
- `/health`: full diagnostics (latency, uptime, voice, queue, current session details, etc.).

### Alerts and audit

- `/alert_add <@handle|id>`: add an X account to monitoring and bind the current channel.
- `/alert_remove <index|id|@handle>`: remove account for current channel; fully remove if no channels remain.
- `/alert_list`: list monitored accounts in this server.
- `/alert_interval <seconds>`: set polling interval.
- `/audit_log`: show audit events (bookmarks, alerts, transcripts, etc.).

## Supported URL format

- Valid: `https://x.com/i/spaces/<id>`
- Example: `https://x.com/i/spaces/1RKjpzpmXpLJw`
- Not valid for playback: links like `.../status/...` or other X routes.

## Environment configuration

Configuration files are auto-created when the bot starts. If a mounted volume path points to a directory with the same file name, the bot will remove that directory and replace it with an empty JSON file.

Example `config.json` (or `config.dev.json`):
```json
{
  "user_ids": ["1542216927296225281", "64032321"],
  "username_map": {"1542216927296225281": "_ebnd1"},
  "user_channels": {"1542216927296225281": [123456789012345678]},
  "check_interval": 600
}
```

Example `alertados.json` (or `alertados.dev.json`):
```json
["1vKpPrPdoroKE", "1DxLdvdRdEvxm"]
```

Minimum required:
- `DISCORD_TOKEN`

Main optional variables:
- `SYNC_GUILD_ID`: instant slash sync to a specific guild.
- `HISTORY_DB_PATH`: default `data/history.db`.
- `IDLE_DISCONNECT_SECONDS`: default `60`.
- `DISCORD_ALERT_CHANNEL_IDS`: fallback alert channels (comma-separated).
- `DISCORD_ALERT_CHANNEL_ID`: single fallback channel.
- `DISCORD_ADMIN_CHANNEL_ID`: channel for delivery/error notices.
- `DISCORD_ALERT_MENTION_EVERYONE`: default `true`.
- `ALERT_CONFIG_PATH`: default `config.json`.
- `ALERTED_SPACES_PATH`: default `alertados.json`.
- `X_AUTH_TOKEN`, `X_CT0`, `X_TWID`: X/Twitter cookies for authenticated scraping.
- Advanced scraper variables (`X_PUBLIC_BEARER`, `X_WEB_BASE_URL`, `X_API_BASE_URL`, `X_GQL_*`, `X_HTTP_TIMEOUT_*`) to tune endpoints/query IDs without code changes.

Full reference:
- [`.env.example`](./.env.example)
- [`.env.dev`](./.env.dev)

## Local run (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
python -m akuma_bot.main
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m coverage run -m unittest discover -s tests -p "test_*.py"
python -m coverage report -m
```

## Development notes

- Layered architecture: `domain/`, `application/`, `infrastructure/`.
- DDD is applied strongly in history/audit (`PlayHistory`, `Bookmark`, `AuditLog`).
- Patterns: Value Objects, Use Cases, and ports/repositories.
- Discord command changes: `src/akuma_bot/infrastructure/discord/commands/registry.py`.
- Storage changes: `src/akuma_bot/infrastructure/persistence/sqlite_history_repository.py`.

## Audit system

- `audit_log` table centralizes administrative events (`bookmark_add`, `alert_add`, `transcript`, etc.).
- `play_history` and `bookmarks` store `user_name` and `user_tag` for traceability.
- `/audit_log` supports filtering by event type and limit.
- All inserts use parameterized queries.

## Project structure

- `src/akuma_bot/domain/`: domain logic (DDD)
  - `alerts/`: alert entities and rules
  - `playback/`: playback entities and rules
- `src/akuma_bot/application/`: use cases and orchestration
- `src/akuma_bot/infrastructure/`: technical adapters (Discord, DB, scraper)
- `tests/`: test suite (unittest + pytest)

## Docker: development

This repo includes separate development setup to keep prod and dev state isolated:
- `docker-compose.dev.yml`
- `.env.dev`
- `config.dev.json`
- `alertados.dev.json`

Commands:

```bash
docker compose -f docker-compose.dev.yml up --build -d
docker compose -f docker-compose.dev.yml logs -f bot-dev
docker compose -f docker-compose.dev.yml down
```

## Docker/OCI: production

1. Prepare server (Docker installed).
2. Create deployment folder (for example `/opt/akuma-bot`).
3. Place `docker-compose.yml` + production `.env`.
4. If GHCR image is private, authenticate with PAT (`read:packages`).
5. Start:

```bash
docker compose -f docker-compose.yml down --remove-orphans
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml logs -f bot
```

> Note: `--force-recreate` recreates containers but does **not** rebuild images. Use `--build` when code changes.

## Slash sync note

If `SYNC_GUILD_ID` is set, slash commands update almost instantly in that guild.
If not set, sync is global and can take longer.

## Changelog

See [CHANGELOG.md](./CHANGELOG.md) for detailed release notes.
