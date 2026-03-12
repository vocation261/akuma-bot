import time


class DiagnosticsUseCase:
    def __init__(self, client, sessions, start_ts: float):
        self.client = client
        self.sessions = sessions
        self.start_ts = start_ts

    def guild_snapshot(self, guild):
        session = self.sessions.guild(guild.id) if guild else None
        voice_client = session.voice_client if session else None
        return {
            "bot": str(self.client.user),
            "guilds": len(self.client.guilds),
            "latency_ms": round(self.client.latency * 1000),
            "voice_connected": bool(voice_client and voice_client.is_connected()),
            "playing": bool(voice_client and voice_client.is_playing()),
            "paused": bool(voice_client and voice_client.is_paused()),
            "mode": "LIVE" if (session and session.is_live) else "REC",
            "title": session.title if session else "",
            "elapsed": session.elapsed() if session else 0,
            "url": session.current_url if session else "",
            "uptime": int(time.time() - self.start_ts),
            "queue_size": len(session.queue) if session else 0,
            "retries": f"{session.play_retry_count}/{session.max_play_retries}" if session else "0/0",
            "channel_status": "on" if (session and session.channel_status_enabled) else "off",
        }
