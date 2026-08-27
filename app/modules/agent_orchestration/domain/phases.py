"""Coarse execution phases and user-facing status lines for the travel graphs.

Nodes attach a ``phase`` plus a human-readable ``phase_status`` to their state
updates; the SSE layer turns those into ``stream_detail=phases`` events.

LangGraph emits a node's updates only *after* that node returns, so a node
announces the work that comes **next** rather than what it just finished. The
cheap nodes (``travel_root``, ``confirm_build``, ``after_build``) therefore carry
the announcements that sit in front of the slow LLM and deep-research steps; the
parallel specialists each announce themselves as they complete.
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


def keep_true(current: bool | None, incoming: bool | None) -> bool:
    """OR-merge for sticky flags (e.g. ``kb_build_attempted``).

    Each new ``/chat`` turn re-seeds travel state with ``False`` defaults; without
    this reducer a completed KB build would be forgotten and city_expert would
    ask to research the same destination again.
    """
    return bool(current) or bool(incoming)


def merge_phase(current: str | None, incoming: str | list[str] | None) -> str | None:
    """Reducer for the ``phase`` / ``phase_status`` channels.

    The parallel specialists (Stage 8) each finish in the same super-step and all
    write their own announcement, so the channel receives several values at once.
    ``specialist_outputs`` is a real merged reducer, but the phase line is a single
    user-facing string — so we deterministically surface the first write of the
    step (the graph is deterministic, so this is stable run-to-run). Keeping one
    string preserves the existing SSE shape.
    """
    if isinstance(incoming, list):
        return incoming[0] if incoming else current
    return incoming if incoming is not None else current


def specialist_status(role: str, destination: str) -> str:
    """Status line announcing the specialist that is about to run."""
    template = _SPECIALIST_STATUS.get(role, _FALLBACK_SPECIALIST_STATUS)
    return template.format(role=role.replace("_", " "), destination=destination)
