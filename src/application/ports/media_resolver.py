from __future__ import annotations

from typing import Protocol


class MediaResolver(Protocol):
    def get_media_info(self, url: str, extra_args: str = "") -> dict:
        ...

    def get_stream_url(self, url: str, retries: int = 3, extra_args: str = "") -> str:
        ...

    def is_space_url(self, url: str) -> bool:
        ...

    def resolve_live_status(self, info: dict, source_is_space: bool) -> tuple[bool, str]:
        ...

    def host_avatar_url(self, handle: str) -> str:
        ...

    def scrape_space_html(self, url: str) -> dict:
        ...

