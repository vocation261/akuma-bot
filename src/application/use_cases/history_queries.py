class HistoryQueryUseCases:
    def __init__(self, history_repository):
        self.history_repository = history_repository

    def latest(self, limit: int = 10, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None):
        return self.history_repository.latest(limit=limit, guild_id=guild_id, channel_id=channel_id, user_id=user_id)

    def latest_bookmarks(self, guild_id: int, limit: int = 10):
        return self.history_repository.latest_bookmarks(guild_id=guild_id, limit=limit)

    def export_csv(self, output_path: str, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None, limit: int = 1000):
        return self.history_repository.export_csv(output_path, guild_id=guild_id, channel_id=channel_id, user_id=user_id, limit=limit)

