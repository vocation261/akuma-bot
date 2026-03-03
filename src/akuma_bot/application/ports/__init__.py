"""Protocol definitions used by application use cases."""

from .history_repository import HistoryRepository
from .media_resolver import MediaResolver
from .panel_gateway import PanelGateway
from .time_provider import TimeProvider
from .voice_gateway import VoiceGateway

__all__ = [
    "HistoryRepository",
    "MediaResolver",
    "PanelGateway",
    "TimeProvider",
    "VoiceGateway",
]
