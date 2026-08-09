"""Pure routing rules for the travel-planner subgraph."""

from __future__ import annotations

from typing import Literal

from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState

SPECIALISTS: list[str] = ["city_expert", "hotels", "flights_logistics", "food"]

SpecialistRoute = Literal[
    "city_expert", "hotels", "flights_logistics", "food", "cluster", "end"
]


def route_after_requirements(
    state: TravelPlannerState,
) -> Literal["delegate", "ask_requirements", "end"]:
    if state.get("error"):
        return "end"
    return "delegate" if state.get("requirements_complete") else "ask_requirements"


def route_specialist(state: TravelPlannerState) -> SpecialistRoute:
    if state.get("error"):
        return "end"
    nxt = state.get("next_specialist")
    if nxt in SPECIALISTS:
        return nxt  # type: ignore[return-value]
    # Queue exhausted -> group POIs into days before writing the itinerary.
    return "cluster"


def route_after_city_expert(state: TravelPlannerState) -> Literal["delegate", "end"]:
    """End the planner early when a KB miss needs the knowledge builder first."""
    if state.get("kb_miss") and not state.get("kb_build_attempted"):
        return "end"
    return "delegate"
