"""Itinerary synthesis node for the travel planner."""

from __future__ import annotations

import re
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
            if key == "flights_logistics":
                blocks.append(
                    "## Travel & getting around\n"
                    "- (no priced flight/transit options found — still include a "
                    "Getting there / Getting around section and note that prices "
                    "should be verified before booking)"
                )
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


def _travel_cost_appendix(
    outputs: dict[str, list[dict[str, Any]]], requirements: dict[str, Any]
) -> str:
    """Deterministic fallback block so flights / lodging / costs are never omitted."""
    flights = [i for i in (outputs.get("flights_logistics") or []) if isinstance(i, dict)]
    hotels = [i for i in (outputs.get("hotels") or []) if isinstance(i, dict)]
    days = requirements.get("num_days")
    budget = requirements.get("budget") or "your budget"
    lines: list[str] = ["## Getting there, getting around & costs"]

    if flights:
        lines.append("### Getting there & around")
        lines.extend(_format_item(i) for i in flights)
    else:
        lines.append(
            "### Getting there & around\n"
            "- I didn't get solid priced flight options this round — "
            "double-check routes and fares before you book."
        )

    if hotels:
        lines.append("### Where to stay")
        lines.extend(_format_item(i) for i in hotels)

    cost_bits: list[str] = []
    flight_prices = [i["price_usd"] for i in flights if i.get("price_usd") is not None]
    hotel_rates = [i["nightly_rate_usd"] for i in hotels if i.get("nightly_rate_usd") is not None]
    if flight_prices:
        cost_bits.append(f"flights from ~${min(flight_prices):g}")
    if hotel_rates and days:
        try:
            nights = max(int(days) - 1, 1)
        except (TypeError, ValueError):
            nights = 1
        mid = sorted(hotel_rates)[len(hotel_rates) // 2]
        cost_bits.append(f"lodging ~${mid:g}/night × {nights} nights (~${mid * nights:g})")
    elif hotel_rates:
        cost_bits.append(f"lodging from ~${min(hotel_rates):g}/night")

    lines.append("### Rough cost sketch")
    if cost_bits:
        lines.append(f"- Ballpark: {'; '.join(cost_bits)} (against {budget}).")
    else:
        lines.append(
            f"- Keep an eye on flights + lodging + local transit vs {budget}; "
            "I can refine numbers once you pick options."
        )
    return "\n".join(lines)


_TRAVEL_HINTS = re.compile(
    r"\b(flight|flights|getting there|airport|train|ferry|transit|metro|uber|taxi)\b",
    re.I,
)
_COST_HINTS = re.compile(r"(\$\s?\d|\busd\b|\bcost\b|\bbudget\b|\b/night\b|\bprice\b)", re.I)


def ensure_travel_and_costs(
    content: str,
    outputs: dict[str, list[dict[str, Any]]],
    requirements: dict[str, Any],
) -> str:
    """Append a logistics/cost block if the LLM draft skipped them."""
    text = (content or "").strip()
    has_travel = bool(_TRAVEL_HINTS.search(text))
    has_cost = bool(_COST_HINTS.search(text))
    flights = outputs.get("flights_logistics") or []
    hotels = outputs.get("hotels") or []
    if has_travel and has_cost:
        return text
    if not flights and not hotels and has_travel:
        return text
    appendix = _travel_cost_appendix(outputs, requirements)
    if not text:
        return appendix
    return f"{text}\n\n---\n\n{appendix}"


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
                HumanMessage(
                    content=(
                        "Write the full draft plan now. You MUST include Getting there, "
                        "Getting around, Where to stay, a Rough cost sketch with $ figures "
                        "when the inputs have them, and a day-by-day plan — then invite tweaks."
                    )
                ),
            ],
            config=trace_run_config_from_metadata(rendered.metadata),
        )
        content = ensure_travel_and_costs(str(response.content), outputs, requirements)
        return {
            "itinerary": content,
            "messages": [AIMessage(content=content)],
            **phases.phase_update(
                phases.DONE, "Here's a draft plan — we can tweak it together."
            ),
        }

    return synthesize_itinerary
