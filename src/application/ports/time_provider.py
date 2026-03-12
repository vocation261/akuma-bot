from __future__ import annotations

from typing import Protocol


class TimeProvider(Protocol):
    def now(self) -> float:
        ...

