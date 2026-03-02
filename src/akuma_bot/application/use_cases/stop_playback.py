class StopUseCase:
    def __init__(self, voice_gateway):
        self.voice_gateway = voice_gateway

    async def run(self, guild):
        return await self.voice_gateway.stop(guild)

