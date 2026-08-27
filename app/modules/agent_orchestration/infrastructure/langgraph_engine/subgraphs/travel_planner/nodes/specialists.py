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
    IFlightsProvider,
    IHotelsProvider,
    IPlacesProvider,
)
from app.modules.agent_orchestration.application.use_cases.kb_status_service import KBStatusService
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
    "flights_logistics": (
        "flights and travel options from {origin} to {dest}, "
        "plus local transport, airport transfers, and passes in {dest}"
    ),
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
    hotels_provider: IHotelsProvider | None = None,
    flights_provider: IFlightsProvider | None = None,
):
    schema = ROLE_SCHEMAS[role]

    async def specialist(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        dest = destination_label(requirements)
        budget = str(requirements.get("budget") or "any")
        origin = str(
            requirements.get("origin_city")
            or requirements.get("origin")
            or requirements.get("departure_city")
            or ""
        ).strip()
        template = ROLE_QUERIES.get(role, "{role} recommendations for a trip to {dest}")
        query = template.format(
            dest=dest,
            budget=budget,
            role=role,
            origin=origin or "the traveller's home city",
        )

        # Stage 10: try a real/mock provider first. A hit becomes the structured
        # output directly (offline mocks / live APIs). None → web-search + LLM.
        # Knowledge-builder path is untouched (city_expert owns KB misses).
        provider_items = await _provider_items_for_role(
            role,
            dest=dest,
            budget=budget,
            origin=origin,
            query=query,
            places_provider=places_provider,
            hotels_provider=hotels_provider,
            flights_provider=flights_provider,
        )
        if provider_items is not None:
            return {
                "specialist_outputs": {role: provider_items},
                **phases.phase_update(phases.PLANNING, phases.specialist_status(role, dest)),
            }

        evidence = await run_web_search(web_search_tool, query)
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
        return {
            "specialist_outputs": {role: items},
            # With no delegate turn between parallel specialists, each announces
            # itself (this also covers the KB re-plan, where Send args are dropped).
            **phases.phase_update(phases.PLANNING, phases.specialist_status(role, dest)),
        }

    return specialist


async def _provider_items_for_role(
    role: str,
    *,
    dest: str,
    budget: str,
    origin: str,
    query: str,
    places_provider: IPlacesProvider | None,
    hotels_provider: IHotelsProvider | None,
    flights_provider: IFlightsProvider | None,
) -> list[dict[str, Any]] | None:
    if role == "hotels" and hotels_provider is not None:
        found = await hotels_provider.search(destination=dest, budget=budget)
        return [h.model_dump() for h in found] if found else None
    if role == "flights_logistics" and flights_provider is not None:
        if not origin:
            return None
        found = await flights_provider.search(origin=origin, destination=dest)
        return [f.model_dump() for f in found] if found else None
    if role == "food" and places_provider is not None:
        found = await places_provider.search_pois(query)
        return [p.model_dump() for p in found] if found else None
    return None


def make_city_expert_node(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    retriever_provider: RetrieverProvider | None,
    web_search_tool: BaseTool | None,
    places_provider: IPlacesProvider | None = None,
    kb_status_service: KBStatusService | None = None,
):
    async def city_expert(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        dest = destination_label(requirements)
        city = requirements.get("destination_city")
        country = requirements.get("destination_country")
        destination_key = build_destination_key(city=city, country=country)

        kb_row = None
        if kb_status_service is not None and destination_key:
            try:
                kb_row = await kb_status_service.get_status(destination_key)
                # LLM sometimes omits/adds country across turns ("lisbon|portugal"
                # vs "lisbon|"). Prefer a ready city-only row over a false miss.
                if kb_row is None and city:
                    alt_key = build_destination_key(city=city, country=None)
                    if alt_key != destination_key:
                        alt_row = await kb_status_service.get_status(alt_key)
                        if alt_row and alt_row.status == "ready" and (alt_row.doc_count or 0) > 0:
                            logger.info(
                                "city_expert using ready KB key %s instead of %s",
                                alt_key,
                                destination_key,
                            )
                            kb_row = alt_row
                            destination_key = alt_key
            except Exception:
                logger.exception("city_expert kb status lookup failed for %s", destination_key)

        kb_ready = bool(kb_row and kb_row.status == "ready" and (kb_row.doc_count or 0) > 0)

        evidence = ""
        retrieval_error = False
        retriever = retriever_provider(destination_key) if retriever_provider else None
        if retriever is not None:
            try:
                docs = await asyncio.to_thread(
                    retriever.invoke, f"travel guide overview of {dest}"
                )
                evidence = "\n\n".join(getattr(d, "page_content", "") for d in docs)
                logger.info(
                    "city_expert retrieval destination=%s hits=%d evidence_chars=%d",
                    destination_key,
                    len(docs or []),
                    len(evidence),
                )
            except Exception:
                retrieval_error = True
                logger.exception("city_expert retrieval failed destination=%s", destination_key)
                evidence = ""

        # KB miss: only when retrieval is empty AND we have no ready row yet.
        # A ready row with empty/failed retrieval (embedder glitch) must not force
        # another deep-research build — fall through to web search instead.
        if (
            not evidence.strip()
            and not kb_ready
            and retriever is not None
            and not state.get("kb_build_attempted")
        ):
            logger.info("city_expert KB miss for %s — requesting knowledge build", destination_key)
            return {
                "kb_miss": True,
                "destination_key": destination_key,
                "city": city,
                "country": country,
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
            if kb_ready:
                logger.warning(
                    "city_expert KB ready for %s but retrieval empty "
                    "(error=%s) — using web search instead of rebuilding",
                    destination_key,
                    retrieval_error,
                )
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
