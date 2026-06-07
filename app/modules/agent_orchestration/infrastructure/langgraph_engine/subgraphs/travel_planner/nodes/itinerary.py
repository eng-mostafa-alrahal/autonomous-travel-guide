"""Itinerary synthesis node for the travel planner."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_run_config_from_metadata,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.helpers import (  # noqa: E501
    format_requirements,
)

_ORDER = ["city_expert", "hotels", "flights_logistics", "food"]
_TITLES = {
    "city_expert": "Local insights",
    "hotels": "Lodging",
    "flights_logistics": "Travel & getting around",
    "food": "Food & dining",
}


def _format_notes(outputs: dict[str, str]) -> str:
    blocks: list[str] = []
    for key in _ORDER:
        text = outputs.get(key)
        if text and text.strip():
            blocks.append(f"## {_TITLES.get(key, key)}\n{text.strip()}")
    return "\n\n".join(blocks) if blocks else "(no specialist input available)"


def make_itinerary_node(llm: BaseChatModel, *, prompt_provider: IPromptProvider):
    async def synthesize_itinerary(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        outputs = state.get("specialist_outputs", {})
        rendered = prompt_provider.resolve_prompt(
            PromptIntent.TRAVEL_ITINERARY,
            PromptContext(
                requirements_text=format_requirements(requirements),
                specialist_notes=_format_notes(outputs),
                num_days=str(requirements.get("num_days") or ""),
            ),
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=rendered.content),
                HumanMessage(content="Create the itinerary now."),
            ],
            config=trace_run_config_from_metadata(rendered.metadata),
        )
        content = str(response.content)
        return {"itinerary": content, "messages": [AIMessage(content=content)]}

    return synthesize_itinerary
