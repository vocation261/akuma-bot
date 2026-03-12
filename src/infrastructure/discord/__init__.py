"""Discord integration layer."""

from .command_handlers import register_commands, register_tree_error_handler
from .panel_gateway import DiscordPanelGateway
from .voice_gateway import DiscordVoiceGateway

__all__ = [
    "DiscordPanelGateway",
    "DiscordVoiceGateway",
    "register_commands",
    "register_tree_error_handler",
]
