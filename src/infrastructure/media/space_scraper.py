from __future__ import annotations

import re
from html import unescape
from urllib.request import Request, urlopen


def scrape_space_html(url: str) -> dict:
    info: dict = {}
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return info

    def extract_og(prop: str) -> str:
        match = re.search(rf'property="og:{prop}"\s+content="([^"]+)"', html)
        if not match:
            match = re.search(rf'content="([^"]+)"\s+property="og:{prop}"', html)
        return unescape(match.group(1)).strip() if match else ""

    title = extract_og("title")
    if title:
        info["title"] = title
    description = extract_og("description")
    if description:
        lowered = description.lower()
        if any(key in lowered for key in ("is live", "live now", "en vivo")):
            info["live"] = True
        elif any(key in lowered for key in ("recorded", "recording available", "listen to")):
            info["live"] = False
            info["has_recording"] = True
        handles = re.findall(r"@(\w+)", description)
        if handles:
            info["uploader_id"] = handles[0]
    return info

