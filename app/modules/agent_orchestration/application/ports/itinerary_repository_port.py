"""Itinerary repository contract — extends the generic IRepository."""

from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.modules.agent_orchestration.domain.itinerary import Itinerary
from app.shared.ports.base_repository import IRepository


class IItineraryRepository(IRepository[Itinerary]):
    @abstractmethod
    async def get_latest_for_session(self, session_id: UUID) -> Itinerary | None:
        """Most recently created itinerary for a session, or None."""
        ...

    @abstractmethod
    async def list_for_session(self, session_id: UUID) -> list[Itinerary]:
        """All itineraries for a session, newest first (version history)."""
        ...
