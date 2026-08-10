"""Itinerary entity — a persisted travel plan for a conversation session.

Written when the planner finishes a run (Stage 9). Keeps the rendered markdown
plus the structured per-day clusters and the requirements that produced it, so a
later revision turn can diff requirements and re-run only the affected
specialists/days.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.shared.domain_models.base_model import DomainModel


class Itinerary(DomainModel):
    session_id: UUID
    user_id: UUID
    content: str = Field(description="Rendered day-by-day markdown plan.")
    requirements: dict[str, Any] = Field(
        default_factory=dict,
        description="TripRequirements dump that produced this itinerary (for revision diffs).",
    )
    clusters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-day DayCluster dumps (stops + travel legs).",
    )
    num_days: int | None = None
    destination_label: str | None = Field(default=None, max_length=255)
