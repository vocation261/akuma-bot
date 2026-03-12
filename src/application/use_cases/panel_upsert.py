class UpsertPanelUseCase:
    def __init__(self, panel_gateway):
        self.panel_gateway = panel_gateway

    async def run(self, guild, channel, note: str = ""):
        return await self.panel_gateway.upsert(guild, channel, note=note)

