from __future__ import annotations

import requests


class XApiClient:
    def __init__(self) -> None:
        self.session = requests.Session()
