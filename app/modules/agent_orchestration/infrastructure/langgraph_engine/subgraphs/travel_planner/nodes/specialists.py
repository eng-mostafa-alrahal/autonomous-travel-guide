"""Specialist nodes for the travel planner (hotels, flights/logistics, food, city expert)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import BaseTool

from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.kb_destination import build_destination_key
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_run_config_from_metadata,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.helpers import (  # noqa: E501
    destination_label,
    format_requirements,
    run_web_search,
)

logger = logging.getLogger(__name__)

_EVIDENCE_CAP = 6000

_QUERY_TEMPLATES: dict[str, str] = {
    "hotels": "best places to stay and accommodation areas in {dest} for a {budget} budget",
    "flights_logistics": "how to get to {dest} and get around locally (transport options, passes)",
    "food": "best restaurants, street food, and local cuisine to try in {dest}",
}

RetrieverProvider = Callable[[str | None], BaseRetriever | None]


def make_specialist_node(
    role: str,
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    web_search_tool: BaseTool | None,
):
    async def specialist(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        dest = destination_label(requirements)
        budget = str(requirements.get("budget") or "any")
        template = _QUERY_TEMPLATES.get(role, "{role} recommendations for a trip to {dest}")
        query = template.format(dest=dest, budget=budget, role=role)

        evidence = await run_web_search(web_search_tool, query)
        rendered = prompt_provider.resolve_prompt(
            PromptIntent.TRAVEL_SPECIALIST,
            PromptContext(
                role=role,
                requirements_text=format_requirements(requirements),
                retrieved_evidence=evidence[:_EVIDENCE_CAP],
            ),
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=rendered.content),
                HumanMessage(content="Provide your recommendations."),
            ],
            config=trace_run_config_from_metadata(rendered.metadata),
        )
        return {"specialist_outputs": {role: str(response.content)}}

    return specialist


def make_city_expert_node(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    retriever_provider: RetrieverProvider | None,
    web_search_tool: BaseTool | None,
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

        rendered = prompt_provider.resolve_prompt(
            PromptIntent.TRAVEL_CITY_EXPERT,
            PromptContext(
                destination=dest,
                requirements_text=format_requirements(requirements),
                retrieved_evidence=evidence[:_EVIDENCE_CAP],
            ),
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=rendered.content),
                HumanMessage(content="Share the key local insights."),
            ],
            config=trace_run_config_from_metadata(rendered.metadata),
        )
        return {"specialist_outputs": {"city_expert": str(response.content)}}

    return city_expert
