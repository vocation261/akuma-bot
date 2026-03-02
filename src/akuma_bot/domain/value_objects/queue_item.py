from dataclasses import dataclass


@dataclass(slots=True)
class QueueItem:
    url: str
    mode: str = "recorded"

