"""Master-graph routing for the travel root (planner <-> knowledge builder)."""

from __future__ import annotations

from typing import Literal

from app.modules.agent_orchestration.domain.states.travel_root_state import TravelRootState


def route_after_planner(state: TravelRootState) -> Literal["knowledge_builder", "finalize"]:
    """Route to the knowledge builder when the planner reported a fresh KB miss."""
    if state.get("kb_miss") and not state.get("kb_build_attempted"):
        return "knowledge_builder"
    return "finalize"
