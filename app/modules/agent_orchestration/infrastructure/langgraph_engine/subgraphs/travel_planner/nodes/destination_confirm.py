"""Confirm / disambiguate the trip destination before planning.

Handles misspellings, same-name cities in different countries, and names that
could be either a city or a country. Uses the places provider when available;
falls back to a light LLM resolve so CI stays offline-friendly.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.llm_gateways.structured_output import with_pydantic_output
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.application.ports.travel_providers_port import IPlacesProvider
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.destination_resolve import (
    PlaceCandidate,
    apply_destination_answer,
    destination_query,
    evaluate_destination,
)
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.prompts.schema_compact import compact_schema_for_llm
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_config_for_structured_pair,
)

logger = logging.getLogger(__name__)


class _LlmCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    city: str | None = None
    country: str | None = None
    label: str = ""


class _LlmResolve(BaseModel):
    """LLM fallback when no places provider / geocoder is available."""

    model_config = ConfigDict(extra="ignore")

    needs_confirmation: bool = False
    reason: str = "ok"
    message: str = ""
    candidates: list[_LlmCandidate] = Field(default_factory=list)
    canonical_city: str | None = None
    canonical_country: str | None = None


async def _candidates_from_places(
    places: IPlacesProvider | None, *, city: str | None, country: str | None
) -> list[PlaceCandidate]:
    if places is None:
        return []
    query = destination_query(city=city, country=country)
    if not query:
        return []
    try:
        raw = await places.search_destinations(query, limit=5)
    except Exception:
        logger.warning("destination search failed for %r", query, exc_info=True)
        return []
    if not raw:
        # Retry with city-only if both were set (typo in country, etc.).
        if city and country:
            try:
                raw = await places.search_destinations(city, limit=5)
            except Exception:
                return []
        if not raw:
            return []
    out: list[PlaceCandidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        c_city = item.get("city")
        c_country = item.get("country")
        if not label:
            label = destination_query(city=c_city, country=c_country)
        if not label:
            continue
        out.append(
            PlaceCandidate(
                city=str(c_city).strip() if c_city else None,
                country=str(c_country).strip() if c_country else None,
                label=label,
            )
        )
    return out


async def _llm_resolve(
    llm: BaseChatModel,
    prompt_provider: IPromptProvider,
    *,
    city: str | None,
    country: str | None,
) -> dict[str, Any]:
    structured = with_pydantic_output(llm, _LlmResolve)
    user_label = destination_query(city=city, country=country) or "(unknown)"
    system = prompt_provider.resolve_prompt(PromptIntent.STRUCTURED_OUTPUT_SYSTEM, PromptContext())
    human = (
        "The traveller named this destination. Fix obvious misspellings, and list "
        "distinct real-world places if the name is ambiguous (same city name in "
        "different countries, or a name that is both a city and a country).\n\n"
        f"User destination: city={city!r}, country={country!r}, label={user_label!r}\n\n"
        "Set needs_confirmation=true when you are unsure, there are multiple plausible "
        "places, or the spelling looks wrong. Otherwise set needs_confirmation=false and "
        "fill canonical_city / canonical_country.\n\n"
        f"Return only this structured object:\n{compact_schema_for_llm(_LlmResolve)}"
    )
    result: _LlmResolve = await structured.ainvoke(
        [SystemMessage(content=system.content), HumanMessage(content=human)],
        config=trace_config_for_structured_pair(system.metadata, {"prompt_key": "dest_resolve"}),
    )  # type: ignore[assignment]
    candidates = [
        {
            "city": c.city,
            "country": c.country,
            "label": c.label or destination_query(city=c.city, country=c.country),
        }
        for c in result.candidates
        if c.city or c.country or c.label
    ]
    if result.needs_confirmation:
        message = result.message.strip() or (
            f"Just checking — which place did you mean for \"{user_label}\"?"
        )
        return {
            "needs_confirmation": True,
            "reason": result.reason or "ambiguous",
            "message": message,
            "canonical_city": result.canonical_city or city,
            "canonical_country": result.canonical_country or country,
            "candidates": candidates,
        }
    return {
        "needs_confirmation": False,
        "reason": "ok",
        "message": "",
        "canonical_city": result.canonical_city or city,
        "canonical_country": result.canonical_country or country,
        "candidates": candidates,
    }


def make_confirm_destination_node(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    places_provider: IPlacesProvider | None = None,
):
    async def confirm_destination(state: TravelPlannerState) -> dict[str, Any]:
        if state.get("destination_confirmed"):
            return {}

        requirements = dict(state.get("requirements") or {})
        city = requirements.get("destination_city")
        country = requirements.get("destination_country")
        if isinstance(city, str):
            city = city.strip() or None
        if isinstance(country, str):
            country = country.strip() or None

        places_hits = await _candidates_from_places(
            places_provider, city=city, country=country
        )
        if places_hits:
            decision = evaluate_destination(
                user_city=city, user_country=country, candidates=places_hits
            )
        else:
            decision = await _llm_resolve(
                llm, prompt_provider, city=city, country=country
            )

        if not decision.get("needs_confirmation"):
            requirements["destination_city"] = decision.get("canonical_city") or city
            requirements["destination_country"] = (
                decision.get("canonical_country") or country
            )
            logger.info(
                "destination auto-confirmed city=%r country=%r",
                requirements.get("destination_city"),
                requirements.get("destination_country"),
            )
            return {
                "requirements": requirements,
                "destination_confirmed": True,
                **phases.phase_update(
                    phases.PLANNING, "Got it — looking into the best options for you."
                ),
            }

        candidates = decision.get("candidates") or []
        answer = interrupt(
            {
                "kind": "destination_confirm",
                "message": decision.get("message")
                or "Which place did you mean?",
                "reason": decision.get("reason"),
                "candidates": candidates,
                "suggested_city": decision.get("canonical_city"),
                "suggested_country": decision.get("canonical_country"),
            }
        )
        new_city, new_country = apply_destination_answer(
            answer,
            candidates=candidates,
            fallback_city=decision.get("canonical_city") or city,
            fallback_country=decision.get("canonical_country") or country,
        )
        requirements["destination_city"] = new_city
        requirements["destination_country"] = new_country
        logger.info(
            "destination confirmed via HITL city=%r country=%r",
            new_city,
            new_country,
        )
        return {
            "requirements": requirements,
            "destination_confirmed": True,
            "messages": [
                HumanMessage(
                    content=str(
                        answer.get("feedback")
                        if isinstance(answer, dict)
                        else answer
                        or destination_query(city=new_city, country=new_country)
                    )
                )
            ],
            **phases.phase_update(
                phases.PLANNING, "Perfect — planning around that place now."
            ),
        }

    return confirm_destination
