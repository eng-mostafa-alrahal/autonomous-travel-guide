"""Travel-planner subgraph.

Flow: collect_requirements (extract) <-> ask_requirements (HITL) until complete,
then city_expert (the KB-miss gate) fans hotels / flights_logistics / food out to
run in parallel via ``Send``. Their outputs merge under the ``specialist_outputs``
reducer; once all three finish, spatial_cluster groups the POIs by day and
synthesize_itinerary writes the plan. Returns an UNCOMPILED ``StateGraph``.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph

from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IFlightsProvider,
    IHotelsProvider,
    IPlacesProvider,
    ITransitProvider,
)
from app.modules.agent_orchestration.application.use_cases.kb_status_service import KBStatusService
from app.modules.agent_orchestration.domain.routing_rules.travel_planner_router import (
    fan_out_specialists,
    route_after_requirements,
)
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.itinerary import (  # noqa: E501
    make_itinerary_node,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.requirements import (  # noqa: E501
    ask_requirements,
    make_collect_requirements_node,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.spatial import (  # noqa: E501
    make_spatial_cluster_node,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.specialists import (  # noqa: E501
    RetrieverProvider,
    make_city_expert_node,
    make_specialist_node,
)

logger = logging.getLogger(__name__)


def build_travel_planner_graph(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    web_search_tool: BaseTool | None = None,
    retriever_provider: RetrieverProvider | None = None,
    kb_status_service: KBStatusService | None = None,
    requirements_llm: BaseChatModel | None = None,
    logistician_llm: BaseChatModel | None = None,
    transit_provider: ITransitProvider | None = None,
    places_provider: IPlacesProvider | None = None,
    hotels_provider: IHotelsProvider | None = None,
    flights_provider: IFlightsProvider | None = None,
) -> StateGraph:
    req_llm = requirements_llm or llm
    logistics_llm = logistician_llm or llm

    graph = StateGraph(TravelPlannerState)
    graph.add_node(
        "collect_requirements",
        make_collect_requirements_node(req_llm, prompt_provider=prompt_provider),
    )
    graph.add_node("ask_requirements", ask_requirements)
    graph.add_node(
        "city_expert",
        make_city_expert_node(
            llm,
            prompt_provider=prompt_provider,
            retriever_provider=retriever_provider,
            web_search_tool=web_search_tool,
            places_provider=places_provider,
            kb_status_service=kb_status_service,
        ),
    )
    graph.add_node(
        "hotels",
        make_specialist_node(
            "hotels",
            llm=llm,
            prompt_provider=prompt_provider,
            web_search_tool=web_search_tool,
            hotels_provider=hotels_provider,
        ),
    )
    graph.add_node(
        "flights_logistics",
        make_specialist_node(
            "flights_logistics",
            llm=logistics_llm,
            prompt_provider=prompt_provider,
            web_search_tool=web_search_tool,
            flights_provider=flights_provider,
        ),
    )
    graph.add_node(
        "food",
        make_specialist_node(
            "food",
            llm=llm,
            prompt_provider=prompt_provider,
            web_search_tool=web_search_tool,
            places_provider=places_provider,
        ),
    )
    graph.add_node("spatial_cluster", make_spatial_cluster_node(transit_provider))
    graph.add_node(
        "synthesize_itinerary",
        make_itinerary_node(llm, prompt_provider=prompt_provider),
    )

    graph.set_entry_point("collect_requirements")
    graph.add_conditional_edges(
        "collect_requirements",
        route_after_requirements,
        {"city_expert": "city_expert", "ask_requirements": "ask_requirements", "end": END},
    )
    graph.add_edge("ask_requirements", "collect_requirements")
    # city_expert gates on a KB miss; otherwise it fans the remaining specialists
    # out to run in parallel via Send. Each converges on spatial_cluster, which
    # LangGraph runs only once all three (and the Send branch itself) have settled.
    graph.add_conditional_edges(
        "city_expert",
        fan_out_specialists,
        ["hotels", "flights_logistics", "food", END],
    )
    graph.add_edge("hotels", "spatial_cluster")
    graph.add_edge("flights_logistics", "spatial_cluster")
    graph.add_edge("food", "spatial_cluster")
    graph.add_edge("spatial_cluster", "synthesize_itinerary")
    graph.add_edge("synthesize_itinerary", END)
    return graph
