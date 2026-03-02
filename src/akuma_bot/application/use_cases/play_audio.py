class PlayAudioUseCase:
    def __init__(self, voice_gateway):
        self.voice_gateway = voice_gateway

    async def run(self, guild, user, url: str, mode: str = "recorded", force_vc_channel_id: int = 0) -> dict:
        return await self.voice_gateway.play(guild, user, url, mode=mode, force_vc_channel_id=force_vc_channel_id)

