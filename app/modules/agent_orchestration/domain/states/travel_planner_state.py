"""State schema for the travel-planner subgraph."""

from __future__ import annotations

from typing import Annotated, Any

from app.modules.agent_orchestration.domain.states.base_state import BaseAgentState


def merge_specialist_outputs(
    existing: dict[str, str] | None, new: dict[str, str] | None
) -> dict[str, str]:
    """Reducer that accumulates per-specialist outputs as they complete."""
    return {**(existing or {}), **(new or {})}


class TravelPlannerState(BaseAgentState):
    requirements: dict[str, Any]
    requirements_complete: bool
    missing_slots: list[str]
    pending_specialists: list[str]
    next_specialist: str | None
    specialist_outputs: Annotated[dict[str, str], merge_specialist_outputs]
    itinerary: str | None
    # Cross-graph handoff (knowledge-builder auto-trigger). Also present on
    # KnowledgeBuilderState / TravelRootState so they flow through the master graph.
    destination_key: str
    city: str | None
    country: str | None
    kb_miss: bool
    kb_build_attempted: bool
