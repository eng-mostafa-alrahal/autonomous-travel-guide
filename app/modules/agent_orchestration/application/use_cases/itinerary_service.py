"""Itinerary use-cases — persist and retrieve travel plans (Stage 9).

Written best-effort when the planner finishes a run; read back to fetch a
session's saved itinerary or to seed a future revision turn (diff requirements
to re-run only affected specialists/days).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.agent_orchestration.domain.itinerary import Itinerary
from app.shared.ports.unit_of_work import IUnitOfWork

logger = logging.getLogger(__name__)


def _destination_label(requirements: dict[str, Any]) -> str | None:
    parts = [
        requirements.get("destination_city"),
        requirements.get("destination_country"),
    ]
    label = ", ".join(str(p) for p in parts if p)
    return label or None


class ItineraryService:
    def __init__(self, uow_factory: Callable[[], IUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get_latest_for_session(self, session_id: UUID) -> Itinerary | None:
        async with self._uow_factory() as uow:
            return await uow.itineraries.get_latest_for_session(session_id)  # type: ignore[attr-defined]

    async def save_completed(
        self,
        *,
        session_id: str,
        user_id: str,
        itinerary: str | None,
        requirements: dict[str, Any] | None,
        clusters: list[dict[str, Any]] | None,
    ) -> Itinerary | None:
        """Persist a finished itinerary. Returns None (no-op) when there's no plan.

        Best-effort: any persistence error is logged and swallowed so a DB hiccup
        never fails an otherwise-successful trip-planning turn.
        """
        if not itinerary or not itinerary.strip():
            return None
        try:
            session_uuid = UUID(str(session_id))
            user_uuid = UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning(
                "itinerary save skipped: unparseable session_id/user_id (%r, %r)",
                session_id,
                user_id,
            )
            return None

        reqs = requirements or {}
        num_days_raw = reqs.get("num_days")
        try:
            num_days = int(num_days_raw) if num_days_raw is not None else None
        except (TypeError, ValueError):
            num_days = None

        entity = Itinerary(
            session_id=session_uuid,
            user_id=user_uuid,
            content=itinerary,
            requirements=reqs,
            clusters=clusters or [],
            num_days=num_days,
            destination_label=_destination_label(reqs),
        )
        try:
            async with self._uow_factory() as uow:
                saved = await uow.itineraries.add(entity)  # type: ignore[attr-defined]
                await uow.commit()
            logger.info(
                "itinerary saved session_id=%s id=%s days=%s",
                session_id,
                saved.id,
                saved.num_days,
            )
            return saved
        except Exception:
            logger.exception("itinerary save failed session_id=%s", session_id)
            return None
