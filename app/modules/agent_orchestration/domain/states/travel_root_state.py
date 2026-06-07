"""Unified master state for the travel graph.

Superset of ``TravelPlannerState`` and ``KnowledgeBuilderState`` so both
compiled subgraphs can read/write their channels when wired into one master
graph (LangGraph shares only keys present in both the parent and the subgraph).
"""

from __future__ import annotations

from typing import Annotated, Any

from app.modules.agent_orchestration.domain.states.base_state import BaseAgentState
from app.modules.agent_orchestration.domain.states.travel_planner_state import (
    merge_specialist_outputs,
)


class TravelRootState(BaseAgentState):
    # ── planner ──────────────────────────────────────────────────
    requirements: dict[str, Any]
    requirements_complete: bool
    missing_slots: list[str]
    pending_specialists: list[str]
    next_specialist: str | None
    specialist_outputs: Annotated[dict[str, str], merge_specialist_outputs]
    itinerary: str | None
    # ── knowledge builder ───────────────────────────────────────
    destination_key: str
    city: str | None
    country: str | None
    topics: list[str]
    approved: bool | None
    raw_research: str | None
    research_sources: list[str]
    prepared_segments: list[dict[str, str]]
    doc_count: int
    # ── cross-graph control ─────────────────────────────────────
    kb_miss: bool
    kb_build_attempted: bool
