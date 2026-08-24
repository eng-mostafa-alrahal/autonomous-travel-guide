"""Assemble the travel master graph (planner <-> knowledge builder).

Active when ``TRAVEL_PLANNER_ENABLED`` is true. The planner runs first; when its
city-expert reports a KB miss, the master runs the knowledge builder (with its
HITL approval), then re-plans with the fresh KB. On rejection the planner falls
back to web search and nothing is written to the KB.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph

from app.modules.agent_orchestration.application.ports.deep_research_port import (
    IDeepResearchClient,
)
from app.modules.agent_orchestration.application.ports.ingestion_port import IIngestionService
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IPlacesProvider,
    ITransitProvider,
)
from app.modules.agent_orchestration.application.use_cases.kb_status_service import KBStatusService
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.routing_rules.travel_root_router import (
    route_after_planner,
)
from app.modules.agent_orchestration.domain.states.travel_root_state import TravelRootState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.shared_nodes.error_handler_node import (  # noqa: E501
    error_handler_node,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.knowledge_builder.knowledge_builder_graph import (  # noqa: E501
    build_knowledge_builder_graph,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.specialists import (  # noqa: E501
    RetrieverProvider,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.travel_planner_graph import (  # noqa: E501
    build_travel_planner_graph,
)

logger = logging.getLogger(__name__)


def build_travel_master_graph(
    *,
    llm: BaseChatModel,
    prompt_provider: IPromptProvider,
    deep_research_client: IDeepResearchClient,
    ingestion_service: IIngestionService,
    kb_status_service: KBStatusService,
    web_search_tool: BaseTool | None = None,
    retriever_provider: RetrieverProvider | None = None,
    validator_llm: BaseChatModel | None = None,
    requirements_llm: BaseChatModel | None = None,
    logistician_llm: BaseChatModel | None = None,
    transit_provider: ITransitProvider | None = None,
    places_provider: IPlacesProvider | None = None,
) -> StateGraph:
    planner_subgraph = build_travel_planner_graph(
        llm,
        prompt_provider=prompt_provider,
        web_search_tool=web_search_tool,
        retriever_provider=retriever_provider,
        requirements_llm=requirements_llm,
        logistician_llm=logistician_llm,
        transit_provider=transit_provider,
        places_provider=places_provider,
    ).compile()

    knowledge_builder_subgraph = build_knowledge_builder_graph(
        validator_llm or llm,
        prompt_provider=prompt_provider,
        deep_research_client=deep_research_client,
        ingestion_service=ingestion_service,
        kb_status_service=kb_status_service,
    ).compile()

    def travel_root(_state: TravelRootState) -> dict[str, Any]:
        # Entry dispatch. Currently always plans first; extensible to detect a
        # direct "build knowledge" intent later.
        return phases.phase_update(phases.REQUIREMENTS, "Getting started on your trip plan.")

    def after_build(_state: TravelRootState) -> dict[str, Any]:
        # Mark that we tried building so the re-plan won't trigger another build,
        # whether the user approved (KB now ready) or rejected (web fallback).
        return {
            "kb_build_attempted": True,
            "kb_miss": False,
            **phases.phase_update(phases.PLANNING, "Re-planning with what I just learned."),
        }

    master = StateGraph(TravelRootState)
    master.add_node("travel_root", travel_root)
    master.add_node("planner", planner_subgraph)
    master.add_node("knowledge_builder", knowledge_builder_subgraph)
    master.add_node("after_build", after_build)
    master.add_node("error_handler", error_handler_node)

    master.set_entry_point("travel_root")
    master.add_edge("travel_root", "planner")
    master.add_conditional_edges(
        "planner",
        route_after_planner,
        {"knowledge_builder": "knowledge_builder", "finalize": "error_handler"},
    )
    master.add_edge("knowledge_builder", "after_build")
    master.add_edge("after_build", "planner")
    master.add_edge("error_handler", END)
    return master
