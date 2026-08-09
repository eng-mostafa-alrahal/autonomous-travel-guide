"""Knowledge-builder subgraph.

Pipeline: confirm_build (HITL) -> deep_research (Jina) -> deduplicate (LLM)
-> ingest (pgvector) -> notify_complete. Linear with an approve/reject branch
and short-circuit to END on errors.

This builder returns an UNCOMPILED ``StateGraph``; the caller compiles it (and
attaches a checkpointer) when wiring it into the master graph.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.modules.agent_orchestration.application.ports.deep_research_port import (
    IDeepResearchClient,
)
from app.modules.agent_orchestration.application.ports.ingestion_port import (
    DestinationRef,
    IIngestionService,
    IngestionSegment,
)
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.application.use_cases.kb_status_service import KBStatusService
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.routing_rules.knowledge_builder_router import (
    route_after_confirm,
    route_after_ingest,
    route_after_research,
)
from app.modules.agent_orchestration.domain.states.knowledge_builder_state import (
    KnowledgeBuilderState,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.knowledge_builder.nodes.deduplicate import (  # noqa: E501
    make_deduplicate_node,
)

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "history",
    "culture",
    "food and cuisine",
    "top attractions and landmarks",
    "local customs and etiquette",
    "transportation and getting around",
    "safety and practical tips",
    "best time to visit",
]


def _where(state: KnowledgeBuilderState) -> str:
    parts = [p for p in (state.get("city"), state.get("country")) if p]
    return ", ".join(parts) or "this destination"


def _compose_brief(state: KnowledgeBuilderState, default_topics: list[str]) -> str:
    topics = state.get("topics") or default_topics
    topic_lines = "\n".join(f"- {t}" for t in topics)
    return (
        f"Research {_where(state)} for a travel knowledge base. "
        "Provide detailed, factual, up-to-date information covering:\n"
        f"{topic_lines}\n\n"
        "Prefer authoritative sources. Include concrete specifics (place names, "
        "neighborhoods, dishes, transit options, seasons, costs where relevant)."
    )


def build_knowledge_builder_graph(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    deep_research_client: IDeepResearchClient,
    ingestion_service: IIngestionService,
    kb_status_service: KBStatusService,
    default_topics: list[str] | None = None,
) -> StateGraph:
    topics = default_topics or DEFAULT_TOPICS

    def confirm_build(state: KnowledgeBuilderState) -> dict[str, Any]:
        decision = interrupt(
            {
                "kind": "kb_build",
                "message": (
                    f"I don't have a knowledge base for {_where(state)} yet. "
                    "I can research it now, but deep research may take a few minutes. "
                    "Want me to start?"
                ),
                "destination_key": state.get("destination_key"),
                "city": state.get("city"),
                "country": state.get("country"),
            }
        )
        action = (
            decision.get("action", "rejected") if isinstance(decision, dict) else str(decision)
        )
        approved = str(action).lower() in {"approve", "approved", "yes", "accept"}
        updates: dict[str, Any] = {"approved": approved, "human_feedback": str(action)}
        if approved:
            updates.update(
                phases.phase_update(
                    phases.KNOWLEDGE_BUILD,
                    f"Researching {_where(state)} in depth — this can take a few minutes.",
                )
            )
        else:
            updates["messages"] = [
                AIMessage(content="No problem — I won't build that knowledge base right now.")
            ]
            updates.update(
                phases.phase_update(
                    phases.PLANNING, "Skipping the knowledge build — using web search instead."
                )
            )
        return updates

    async def deep_research(state: KnowledgeBuilderState) -> dict[str, Any]:
        await kb_status_service.mark_building(
            destination_key=state["destination_key"],
            city=state.get("city"),
            country=state.get("country"),
        )
        try:
            result = await deep_research_client.research(_compose_brief(state, topics))
        except Exception as exc:
            logger.exception("deep_research failed")
            await kb_status_service.mark_failed(
                destination_key=state["destination_key"],
                city=state.get("city"),
                country=state.get("country"),
                error_message=str(exc),
            )
            return {
                "error": f"deep research failed: {exc}",
                "messages": [
                    AIMessage(content="The deep research step failed. Please try again later.")
                ],
                **phases.phase_update(phases.KNOWLEDGE_BUILD, "Deep research failed."),
            }
        return {
            "raw_research": result.content,
            "research_sources": result.sources,
            **phases.phase_update(
                phases.KNOWLEDGE_BUILD, "Sorting through the research findings."
            ),
        }

    async def ingest(state: KnowledgeBuilderState) -> dict[str, Any]:
        segments = [
            IngestionSegment(topic=s["topic"], content=s["content"], source="deep_research")
            for s in state.get("prepared_segments", [])
        ]
        destination = DestinationRef(
            destination_key=state["destination_key"],
            city=state.get("city"),
            country=state.get("country"),
        )
        try:
            result = await ingestion_service.ingest(segments, destination=destination)
        except Exception as exc:
            logger.exception("ingestion failed")
            await kb_status_service.mark_failed(
                destination_key=state["destination_key"],
                city=state.get("city"),
                country=state.get("country"),
                error_message=str(exc),
            )
            return {
                "error": f"ingestion failed: {exc}",
                "messages": [
                    AIMessage(content="I researched the destination but couldn't store it. "
                              "Please try again later.")
                ],
                **phases.phase_update(
                    phases.KNOWLEDGE_BUILD, "Couldn't store the research in the knowledge base."
                ),
            }
        await kb_status_service.mark_ready(
            destination_key=state["destination_key"],
            city=state.get("city"),
            country=state.get("country"),
            doc_count=result.doc_count,
        )
        return {
            "doc_count": result.doc_count,
            **phases.phase_update(
                phases.KNOWLEDGE_BUILD,
                f"Knowledge base ready ({result.doc_count} entries).",
            ),
        }

    def notify_complete(state: KnowledgeBuilderState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        count = state.get("doc_count", 0)
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"The knowledge base for {_where(state)} is ready "
                        f"({count} entries). Ask me anything about it!"
                    )
                )
            ]
        }

    graph = StateGraph(KnowledgeBuilderState)
    graph.add_node("confirm_build", confirm_build)
    graph.add_node("deep_research", deep_research)
    graph.add_node("deduplicate", make_deduplicate_node(llm, prompt_provider=prompt_provider))
    graph.add_node("ingest", ingest)
    graph.add_node("notify_complete", notify_complete)

    graph.set_entry_point("confirm_build")
    graph.add_conditional_edges(
        "confirm_build", route_after_confirm, {"deep_research": "deep_research", "end": END}
    )
    graph.add_conditional_edges(
        "deep_research", route_after_research, {"deduplicate": "deduplicate", "end": END}
    )
    graph.add_edge("deduplicate", "ingest")
    graph.add_conditional_edges(
        "ingest", route_after_ingest, {"notify_complete": "notify_complete", "end": END}
    )
    graph.add_edge("notify_complete", END)
    return graph
