"""Pure routing rules for the travel-planner subgraph."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END
from langgraph.types import Send

from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState

# city_expert runs first, alone, because it's the only specialist that can trigger
# the knowledge builder on a KB miss. The remaining specialists then fan out and
# run concurrently via Send.
CITY_EXPERT = "city_expert"
PARALLEL_SPECIALISTS: list[str] = ["hotels", "flights_logistics", "food"]
SPECIALISTS: list[str] = [CITY_EXPERT, *PARALLEL_SPECIALISTS]


def route_after_requirements(
    state: TravelPlannerState,
) -> Literal["city_expert", "ask_requirements", "end"]:
    if state.get("error"):
        return "end"
    return "city_expert" if state.get("requirements_complete") else "ask_requirements"


def fan_out_specialists(state: TravelPlannerState) -> list[Send] | Literal["__end__"]:
    """After the city expert, fan the remaining specialists out to run in parallel.

    Each Send invokes its specialist node once with the current state; LangGraph
    runs the three concurrently and merges each ``specialist_outputs[role]`` under
    the channel reducer. A KB miss ends the planner early instead so the knowledge
    builder can run first (the planner re-runs afterwards with the fresh KB).
    """
    if state.get("error"):
        return END
    if state.get("kb_miss") and not state.get("kb_build_attempted"):
        return END
    return [Send(role, dict(state)) for role in PARALLEL_SPECIALISTS]
