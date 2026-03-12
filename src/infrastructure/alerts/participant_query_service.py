from __future__ import annotations

from infrastructure.alerts.services.space_query_service import XSpacesScraper


class ParticipantQueryService(XSpacesScraper):
    """Compatibility adapter to query participants and timing from Spaces."""
