from __future__ import annotations

from infrastructure.alerts.services.space_query_service import XSpacesScraper


class SpaceQueryService(XSpacesScraper):
    """Compatibility adapter around the existing XSpaces scraper."""
