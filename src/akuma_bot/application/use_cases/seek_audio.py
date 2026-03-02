class SeekUseCase:
    def __init__(self, voice_gateway):
        self.voice_gateway = voice_gateway

    async def run_delta(self, guild, delta_seconds: int):
        return await self.voice_gateway.seek(guild, delta_seconds)

    async def run_to(self, guild, target_seconds: int):
        return await self.voice_gateway.seek_to(guild, target_seconds)

