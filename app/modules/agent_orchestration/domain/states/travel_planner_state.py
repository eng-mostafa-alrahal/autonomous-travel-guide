"""State schema for the travel-planner subgraph."""

from __future__ import annotations

from typing import Annotated, Any

from app.modules.agent_orchestration.domain.states.base_state import BaseAgentState


def merge_specialist_outputs(
    existing: dict[str, list[dict[str, Any]]] | None,
    new: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Reducer that accumulates per-specialist structured outputs as they complete.

    Each value is a validated, JSON-serialisable list (``model_dump()`` of the
    specialist's Pydantic list), not raw text.
    """
    return {**(existing or {}), **(new or {})}


class TravelPlannerState(BaseAgentState):
    requirements: dict[str, Any]
    requirements_complete: bool
    missing_slots: list[str]
    pending_specialists: list[str]
    next_specialist: str | None
    specialist_outputs: Annotated[dict[str, list[dict[str, Any]]], merge_specialist_outputs]
    clusters: list[dict[str, Any]]
    itinerary: str | None
    # Progress reporting (streamed as `stream_detail=phases` SSE events).
    phase: str | None
    phase_status: str | None
    # Cross-graph handoff (knowledge-builder auto-trigger). Also present on
    # KnowledgeBuilderState / TravelRootState so they flow through the master graph.
    destination_key: str
    city: str | None
    country: str | None
    kb_miss: bool
    kb_build_attempted: bool
