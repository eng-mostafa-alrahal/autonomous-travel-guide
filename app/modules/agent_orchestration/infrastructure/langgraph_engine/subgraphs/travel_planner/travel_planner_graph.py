"""Travel-planner subgraph.

Flow: collect_requirements (extract) <-> ask_requirements (HITL) until complete,
then delegate walks a specialist queue (city_expert, hotels, flights_logistics,
food) and finally synthesize_itinerary. Returns an UNCOMPILED ``StateGraph``.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph

from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.routing_rules.travel_planner_router import (
    route_after_city_expert,
    route_after_requirements,
    route_specialist,
)
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.helpers import (  # noqa: E501
    destination_label,
)
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
    requirements_llm: BaseChatModel | None = None,
    logistician_llm: BaseChatModel | None = None,
) -> StateGraph:
    req_llm = requirements_llm or llm
    logistics_llm = logistician_llm or llm

    def delegate(state: TravelPlannerState) -> dict[str, Any]:
        pending = list(state.get("pending_specialists") or [])
        if not pending:
            return {
                "next_specialist": None,
                **phases.phase_update(
                    phases.ITINERARY, "Writing your day-by-day itinerary."
                ),
            }
        nxt = pending[0]
        destination = destination_label(state.get("requirements") or {})
        return {
            "next_specialist": nxt,
            "pending_specialists": pending[1:],
            **phases.phase_update(phases.PLANNING, phases.specialist_status(nxt, destination)),
        }

    graph = StateGraph(TravelPlannerState)
    graph.add_node(
        "collect_requirements",
        make_collect_requirements_node(req_llm, prompt_provider=prompt_provider),
    )
    graph.add_node("ask_requirements", ask_requirements)
    graph.add_node("delegate", delegate)
    graph.add_node(
        "city_expert",
        make_city_expert_node(
            llm,
            prompt_provider=prompt_provider,
            retriever_provider=retriever_provider,
            web_search_tool=web_search_tool,
        ),
    )
    graph.add_node(
        "hotels",
        make_specialist_node(
            "hotels", llm, prompt_provider=prompt_provider, web_search_tool=web_search_tool
        ),
    )
    graph.add_node(
        "flights_logistics",
        make_specialist_node(
            "flights_logistics",
            logistics_llm,
            prompt_provider=prompt_provider,
            web_search_tool=web_search_tool,
        ),
    )
    graph.add_node(
        "food",
        make_specialist_node(
            "food", llm, prompt_provider=prompt_provider, web_search_tool=web_search_tool
        ),
    )
    graph.add_node("spatial_cluster", make_spatial_cluster_node())
    graph.add_node(
        "synthesize_itinerary",
        make_itinerary_node(llm, prompt_provider=prompt_provider),
    )

    graph.set_entry_point("collect_requirements")
    graph.add_conditional_edges(
        "collect_requirements",
        route_after_requirements,
        {"delegate": "delegate", "ask_requirements": "ask_requirements", "end": END},
    )
    graph.add_edge("ask_requirements", "collect_requirements")
    graph.add_conditional_edges(
        "delegate",
        route_specialist,
        {
            "city_expert": "city_expert",
            "hotels": "hotels",
            "flights_logistics": "flights_logistics",
            "food": "food",
            "cluster": "spatial_cluster",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "city_expert",
        route_after_city_expert,
        {"delegate": "delegate", "end": END},
    )
    graph.add_edge("hotels", "delegate")
    graph.add_edge("flights_logistics", "delegate")
    graph.add_edge("food", "delegate")
    # Once every specialist has run, delegate routes here to group POIs by day
    # before the itinerary is written.
    graph.add_edge("spatial_cluster", "synthesize_itinerary")
    graph.add_edge("synthesize_itinerary", END)
    return graph
