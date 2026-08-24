"""Specialist nodes for the travel planner (hotels, flights/logistics, food, city expert).

Each specialist returns a validated, JSON-serialisable list (a Pydantic list
schema's ``model_dump()["items"]``) into ``specialist_outputs[role]`` — not free
text — so downstream stages can use the lat/lng and cost fields.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.infrastructure.llm_gateways.structured_output import with_pydantic_output
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IPlacesProvider,
)
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.kb_destination import build_destination_key
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.prompts.schema_compact import compact_schema_for_llm
from app.modules.agent_orchestration.domain.schemas.travel_plan import (
    FlightOptionList,
    HotelOptionList,
    POIList,
)
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_config_for_structured_pair,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.helpers import (  # noqa: E501
    destination_label,
    format_requirements,
    run_web_search,
)

logger = logging.getLogger(__name__)

_EVIDENCE_CAP = 6000

# Each parallel specialist's web-search query template, keyed by role.
ROLE_QUERIES: dict[str, str] = {
    "hotels": "best places to stay and accommodation areas in {dest} for a {budget} budget",
    "flights_logistics": "how to get to {dest} and get around locally (transport options, passes)",
    "food": "best restaurants, street food, and local cuisine to try in {dest}",
}

# Which structured list each specialist role produces.
ROLE_SCHEMAS: dict[str, type[BaseModel]] = {
    "city_expert": POIList,
    "hotels": HotelOptionList,
    "flights_logistics": FlightOptionList,
    "food": POIList,
}

RetrieverProvider = Callable[[str | None], BaseRetriever | None]


def _merge_coords(items: list[dict[str, Any]], geo: dict[str, tuple[float, float]]) -> None:
    """Fill missing lat/lng in-place from a name -> (lat, lng) lookup."""
    for item in items:
        if item.get("lat") is not None and item.get("lng") is not None:
            continue
        key = str(item.get("name") or "").strip().lower()
        if key in geo:
            item["lat"], item["lng"] = geo[key]


async def _structured_items(
    llm: BaseChatModel,
    prompt_provider: IPromptProvider,
    intent: PromptIntent,
    schema: type[BaseModel],
    context: PromptContext,
    human: str,
) -> list[dict[str, Any]]:
    """Run a structured-output call and return the validated ``items`` list."""
    structured_llm = with_pydantic_output(llm, schema)
    system_rendered = prompt_provider.resolve_prompt(
        PromptIntent.STRUCTURED_OUTPUT_SYSTEM, PromptContext()
    )
    human_rendered = prompt_provider.resolve_prompt(intent, context)
    trace_cfg = trace_config_for_structured_pair(
        system_rendered.metadata, human_rendered.metadata
    )
    result = await structured_llm.ainvoke(
        [
            SystemMessage(content=system_rendered.content),
            HumanMessage(content=human_rendered.content),
        ],
        config=trace_cfg,
    )
    return [item.model_dump() for item in getattr(result, "items", [])]


def make_specialist_node(
    role: str,
    *,
    llm: BaseChatModel,
    prompt_provider: IPromptProvider,
    web_search_tool: BaseTool | None,
    places_provider: IPlacesProvider | None = None,
):
    schema = ROLE_SCHEMAS[role]

    async def specialist(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        dest = destination_label(requirements)
        budget = str(requirements.get("budget") or "any")
        template = ROLE_QUERIES.get(role, "{role} recommendations for a trip to {dest}")
        query = template.format(dest=dest, budget=budget, role=role)

        # Stage 10: for the food specialist, try real POI data (with coords) first;
        # fall back to web-search evidence + LLM when the provider yields nothing.
        provider_pois: list[dict[str, Any]] | None = None
        if role == "food" and places_provider is not None:
            found = await places_provider.search_pois(query)
            if found:
                provider_pois = [p.model_dump() for p in found]

        evidence = "" if provider_pois is not None else await run_web_search(web_search_tool, query)
        items = await _structured_items(
            llm,
            prompt_provider,
            PromptIntent.TRAVEL_SPECIALIST,
            schema,
            PromptContext(
                role=role,
                requirements_text=format_requirements(requirements),
                retrieved_evidence=evidence[:_EVIDENCE_CAP],
                compact_schema=compact_schema_for_llm(schema),
            ),
            "Provide your recommendations.",
        )
        if provider_pois is not None:
            # Real coordinates win; keep any LLM notes for colour.
            geo = {p["name"].strip().lower(): (p["lat"], p["lng"]) for p in provider_pois}
            _merge_coords(items, geo)
        return {
            "specialist_outputs": {role: items},
            # With no delegate turn between parallel specialists, each announces
            # itself (this also covers the KB re-plan, where Send args are dropped).
            **phases.phase_update(phases.PLANNING, phases.specialist_status(role, dest)),
        }

    return specialist


def make_city_expert_node(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    retriever_provider: RetrieverProvider | None,
    web_search_tool: BaseTool | None,
    places_provider: IPlacesProvider | None = None,
):
    async def city_expert(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        dest = destination_label(requirements)
        destination_key = build_destination_key(
            city=requirements.get("destination_city"),
            country=requirements.get("destination_country"),
        )

        evidence = ""
        retriever = retriever_provider(destination_key) if retriever_provider else None
        if retriever is not None:
            try:
                docs = await asyncio.to_thread(
                    retriever.invoke, f"travel guide overview of {dest}"
                )
                evidence = "\n\n".join(getattr(d, "page_content", "") for d in docs)
            except Exception:
                logger.exception("city_expert retrieval failed")
                evidence = ""

        # KB miss: if the knowledge base is operational but has nothing for this
        # destination (and we haven't tried yet), hand off to the knowledge builder.
        if (
            not evidence.strip()
            and retriever is not None
            and not state.get("kb_build_attempted")
        ):
            logger.info("city_expert KB miss for %s — requesting knowledge build", destination_key)
            return {
                "kb_miss": True,
                "destination_key": destination_key,
                "city": requirements.get("destination_city"),
                "country": requirements.get("destination_country"),
                "messages": [
                    AIMessage(
                        content=(
                            f"I don't have a knowledge base for {dest} yet. I'd like to run a "
                            "deep search to learn about it (this can take a few minutes). "
                            "I'll ask you to approve it next."
                        )
                    )
                ],
                **phases.phase_update(
                    phases.KNOWLEDGE_BUILD,
                    f"No knowledge base for {dest} yet — asking to run deep research.",
                ),
            }

        if not evidence.strip():
            evidence = await run_web_search(
                web_search_tool, f"travel guide culture history attractions {dest}"
            )

        items = await _structured_items(
            llm,
            prompt_provider,
            PromptIntent.TRAVEL_CITY_EXPERT,
            POIList,
            PromptContext(
                destination=dest,
                requirements_text=format_requirements(requirements),
                retrieved_evidence=evidence[:_EVIDENCE_CAP],
                compact_schema=compact_schema_for_llm(POIList),
            ),
            "Share the key local insights.",
        )
        # Stage 10: enrich LLM best-estimate coordinates with real geocoding.
        if places_provider is not None:
            geo = await _geocode_items(places_provider, items, dest)
            _merge_coords(items, geo)
        return {
            "specialist_outputs": {"city_expert": items},
            # The three remaining specialists are about to fan out and run in
            # parallel; they announce themselves as each finishes.
            **phases.phase_update(
                phases.PLANNING, f"Local insights ready — now covering {dest} in depth."
            ),
        }

    return city_expert


async def _geocode_items(
    provider: IPlacesProvider, items: list[dict[str, Any]], dest: str
) -> dict[str, tuple[float, float]]:
    """Geocode items missing coordinates via the places provider (best-effort)."""
    geo: dict[str, tuple[float, float]] = {}
    for item in items:
        if item.get("lat") is not None and item.get("lng") is not None:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        match = await provider.geocode(f"{name}, {dest}")
        if match and match.lat is not None and match.lng is not None:
            geo[name.lower()] = (match.lat, match.lng)
    return geo
