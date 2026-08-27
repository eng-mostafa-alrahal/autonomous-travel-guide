"""Itinerary synthesis node for the travel planner."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain import phases
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
    "city_expert": "Local insights (points of interest)",
    "hotels": "Lodging",
    "flights_logistics": "Travel & getting around",
    "food": "Food & dining",
}


def _format_item(item: dict[str, Any]) -> str:
    """Render one structured specialist option as a compact bullet line."""
    name = item.get("name") or item.get("summary") or "(unnamed)"
    extras: list[str] = []
    category = item.get("category")
    if category:
        extras.append(str(category))
    if item.get("lat") is not None and item.get("lng") is not None:
        extras.append(f"({item['lat']:.3f}, {item['lng']:.3f})")
    if item.get("area"):
        extras.append(str(item["area"]))
    if item.get("nightly_rate_usd") is not None:
        extras.append(f"~${item['nightly_rate_usd']:g}/night")
    if item.get("price_usd") is not None:
        extras.append(f"~${item['price_usd']:g}")
    if item.get("estimated_duration_min") is not None:
        extras.append(f"~{item['estimated_duration_min']} min")
    meta = f" [{', '.join(extras)}]" if extras else ""
    note = item.get("notes") or item.get("details") or ""
    note = f" — {note.strip()}" if note.strip() else ""
    return f"- {name}{meta}{note}"


def _format_notes(outputs: dict[str, list[dict[str, Any]]]) -> str:
    blocks: list[str] = []
    for key in _ORDER:
        items = outputs.get(key) or []
        if not items:
            continue
        lines = "\n".join(_format_item(i) for i in items if isinstance(i, dict))
        if lines:
            blocks.append(f"## {_TITLES.get(key, key)}\n{lines}")
    return "\n\n".join(blocks) if blocks else "(no specialist input available)"


def _format_day_plan(clusters: list[dict[str, Any]]) -> str:
    """Render the deterministic day clusters as a suggested per-day outline."""
    if not clusters:
        return ""
    blocks: list[str] = []
    for day in clusters:
        stops = day.get("stops") or []
        if not stops:
            continue
        header = f"### Day {day.get('day')}"
        anchor = day.get("anchor_name")
        if anchor:
            header += f" (start from {anchor})"
        lines = [f"- {s.get('name')}" for s in stops if isinstance(s, dict)]
        leg_lines = []
        for leg in day.get("legs") or []:
            if isinstance(leg, dict):
                leg_lines.append(
                    f"  · {leg.get('from_name')} → {leg.get('to_name')}: "
                    f"~{leg.get('travel_minutes')} min ({leg.get('distance_km')} km)"
                )
        body = "\n".join(lines + leg_lines)
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


def make_itinerary_node(llm: BaseChatModel, *, prompt_provider: IPromptProvider):
    async def synthesize_itinerary(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        outputs = state.get("specialist_outputs", {})
        clusters = state.get("clusters") or []
        day_plan = _format_day_plan(clusters)
        specialist_notes = _format_notes(outputs)
        if day_plan:
            specialist_notes += f"\n\n## Suggested day grouping (by location)\n{day_plan}"
        rendered = prompt_provider.resolve_prompt(
            PromptIntent.TRAVEL_ITINERARY,
            PromptContext(
                requirements_text=format_requirements(requirements),
                specialist_notes=specialist_notes,
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
        return {
            "itinerary": content,
            "messages": [AIMessage(content=content)],
            **phases.phase_update(phases.DONE, "Your itinerary is ready."),
        }

    return synthesize_itinerary
