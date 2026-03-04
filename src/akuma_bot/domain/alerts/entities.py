from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AlertSubscription:
    user_id: str
    channel_id: int


@dataclass(slots=True)
class MonitoredAccount:
    user_id: str
    username: str = ""


@dataclass(slots=True)
class SpaceEvent:
    space_id: str
    creator_id: str
    state: str
