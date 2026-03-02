# Akuma Bot

Discord voice bot for X Spaces, YouTube streams and recordings, with queue controls, panel controls, retries, autorefresh, SQLite history and URL cache TTL.

## Commands

`/live /rec /dash /dc /mute /pause /resume /forward /rewind /seek /seekback /seekto /history /diag /skip /cq /now /queue /bookmarks /historycsv /health`

## Environment Variables

Required:
- `DISCORD_TOKEN`

Optional:
- `SYNC_GUILD_ID`
- `YTDLP_ARGS` default `""`
- `STREAM_URL_CACHE_TTL` default `300`
- `QUEUE_PLAYLIST_MAX_ITEMS` default `100`
- `PLAYER_MAX_RETRIES` default `2`
- `VC_CHANNEL_STATUS_ENABLED` default `true`
- `VC_CHANNEL_STATUS_PREFIX` default `🎙️ Space: `
- `HISTORY_DB_PATH` default `data/history.db`
- `IDLE_DISCONNECT_SECONDS` default `60`

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

Set `DISCORD_TOKEN` in `.env` and run:

```bash
python -m akuma_bot.main
```

## OCI Deployment

1. Create an Ubuntu VM in OCI.
2. Install Docker Engine using official docs: https://docs.docker.com/engine/install/ubuntu/
3. Login to GHCR from the VM:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u vocation261 --password-stdin
```

For private GHCR packages, PAT must include `read:packages`.

4. Prepare app directory:

```bash
sudo mkdir -p /opt/akuma-bot
sudo chown -R $USER:$USER /opt/akuma-bot
cd /opt/akuma-bot
```

5. Create `docker-compose.yml` and `.env` only on server.

Example `.env`:

```bash
DISCORD_TOKEN=your_discord_token
SYNC_GUILD_ID=
YTDLP_ARGS=
STREAM_URL_CACHE_TTL=300
QUEUE_PLAYLIST_MAX_ITEMS=100
PLAYER_MAX_RETRIES=2
VC_CHANNEL_STATUS_ENABLED=true
VC_CHANNEL_STATUS_PREFIX=🎙️ Space: 
HISTORY_DB_PATH=data/history.db
IDLE_DISCONNECT_SECONDS=60
```

6. Deploy:

```bash
docker compose pull
docker compose up -d
docker compose logs -f bot
```

## Slash Sync Note

Set `SYNC_GUILD_ID` to a guild id to force instant slash command sync in that guild. If unset, global sync is used.

## GHCR Visibility and Permissions

If the image is private, the server must authenticate with a PAT that has `read:packages` and access to the repository owner package.
