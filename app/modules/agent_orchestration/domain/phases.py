"""Coarse execution phases and user-facing status lines for the travel graphs.

Nodes attach a ``phase`` plus a human-readable ``phase_status`` to their state
updates; the SSE layer turns those into ``stream_detail=phases`` events.

LangGraph emits a node's updates only *after* that node returns, so a node
announces the work that comes **next** rather than what it just finished. The
cheap nodes (``travel_root``, ``delegate``, ``confirm_build``, ``after_build``)
therefore carry the announcements that sit in front of the slow LLM and
deep-research steps.
"""

from __future__ import annotations

from typing import Literal

Phase = Literal["requirements", "planning", "knowledge_build", "itinerary", "done"]

REQUIREMENTS: Phase = "requirements"
PLANNING: Phase = "planning"
KNOWLEDGE_BUILD: Phase = "knowledge_build"
ITINERARY: Phase = "itinerary"
DONE: Phase = "done"

_SPECIALIST_STATUS: dict[str, str] = {
    "city_expert": "Researching local insights for {destination}.",
    "hotels": "Looking into places to stay in {destination}.",
    "flights_logistics": "Working out how to reach and get around {destination}.",
    "food": "Finding the best food in {destination}.",
}

_FALLBACK_SPECIALIST_STATUS = "Consulting the {role} specialist for {destination}."


def phase_update(phase: Phase, status: str) -> dict[str, str]:
    """State-update fragment carrying a phase and its user-facing status line."""
    return {"phase": phase, "phase_status": status}


def specialist_status(role: str, destination: str) -> str:
    """Status line announcing the specialist that is about to run."""
    template = _SPECIALIST_STATUS.get(role, _FALLBACK_SPECIALIST_STATUS)
    return template.format(role=role.replace("_", " "), destination=destination)
