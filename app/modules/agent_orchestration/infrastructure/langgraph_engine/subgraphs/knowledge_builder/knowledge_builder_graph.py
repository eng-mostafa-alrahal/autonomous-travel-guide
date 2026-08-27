"""Knowledge-builder subgraph.

Pipeline: confirm_build (HITL) -> deep_research (Jina, one brief per topic
cluster, run concurrently) -> enrich (keep reports + LLM extra chapters) ->
ingest (pgvector) -> notify_complete. Linear with an approve/reject branch
and short-circuit to END on errors.

This builder returns an UNCOMPILED ``StateGraph``; the caller compiles it (and
attaches a checkpointer) when wiring it into the master graph.
"""

from __future__ import annotations

import asyncio
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

# Topic clusters used for multi-call deep research (KB_RESEARCH_CALLS > 1).
# Each cluster gets its own DeepSearch call so no single answer has to cover
# everything — one combined brief compresses into a shallow summary.
RESEARCH_TOPIC_CLUSTERS: list[tuple[str, str]] = [
    (
        "History, Culture & Identity",
        "history from founding to today; cultural identity and local mentality; "
        "art, architecture and signature styles; important museums and their "
        "must-see highlights; religious customs, traditions and culturally "
        "rooted festivals",
    ),
    (
        "Neighborhoods & Where to Stay",
        "character, atmosphere, safety and rough price level of the main "
        "neighborhoods; which areas suit families / nightlife seekers / budget / "
        "luxury travelers; typical accommodation types with rough nightly price "
        "ranges; areas travelers should avoid",
    ),
    (
        "Attractions, Itineraries & Day Trips",
        "top attractions and landmarks with practical details (typical ticket "
        "prices, opening patterns, booking / skip-the-line advice); lesser-known "
        "hidden gems; ready-made 1-day / 3-day / 1-week itinerary ideas; best "
        "day trips and exactly how to reach them",
    ),
    (
        "Food, Drink & Nightlife",
        "must-try local dishes and drinks using the names locals use; "
        "restaurant / street-food / market scene with rough price ranges; famous "
        "food markets; dining customs (meal times, reservations, tipping); bar "
        "and nightlife districts; signature shopping (souvenirs, local products)",
    ),
    (
        "Getting There & Getting Around",
        "airport(s) and every transfer option into the city with costs and "
        "durations; public transport network (metro / bus / tram) with ticket "
        "types, passes and prices; taxis and ride-hailing; walkability and "
        "cycling; regional trains/buses used for day trips; the reality of "
        "driving and parking",
    ),
    (
        "Practical Knowledge, Safety & Seasonality",
        "safety situation and common tourist scams with avoidance tips; "
        "emergency numbers and tourist healthcare access; local customs and "
        "etiquette (dress codes, greetings, gestures); useful local-language "
        "phrases; money: currency, cards vs cash, tipping norms; SIM/eSIM and "
        "connectivity; best time to visit, month-by-month weather, peak/low "
        "seasons, major annual events; accessibility notes; traveling with "
        "children; LGBTQ+ considerations",
    ),
]

_DEPTH_REQUIREMENTS = (
    "Write an exhaustive, long-form report — a thorough guidebook chapter, not "
    "a summary. Name many concrete specifics: place names, neighborhoods, dish "
    "names, transit lines and stops, ticket/pass names, typical costs, seasonal "
    "timing, exact warnings. Prefer authoritative sources. Do not compress lists "
    "of specific options into generic statements."
)


def _where(state: KnowledgeBuilderState) -> str:
    parts = [p for p in (state.get("city"), state.get("country")) if p]
    return ", ".join(parts) or "this destination"


def _compose_brief(state: KnowledgeBuilderState, default_topics: list[str]) -> str:
    topics = state.get("topics") or default_topics
    topic_lines = "\n".join(f"- {t}" for t in topics)
    return (
        f"Research {_where(state)} for a travel knowledge base that must answer "
        "any question a traveler might ask. Provide detailed, factual, "
        "up-to-date information covering:\n"
        f"{topic_lines}\n\n"
        f"{_DEPTH_REQUIREMENTS}"
    )


def _compose_cluster_brief(state: KnowledgeBuilderState, label: str, details: str) -> str:
    return (
        f"Research {_where(state)} for a travel knowledge base. "
        f"This report covers exactly one theme: {label}.\n\n"
        f"Cover in depth: {details}.\n\n"
        f"{_DEPTH_REQUIREMENTS}"
    )


def plan_research_briefs(
    state: KnowledgeBuilderState,
    default_topics: list[str],
    *,
    research_calls: int,
    clusters: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Return the (label, brief) pairs the deep_research node will execute.

    ``research_calls <= 1`` produces one combined brief; otherwise one brief
    per topic cluster (capped by ``research_calls``) so each DeepSearch run can
    go deep instead of shallow-wide.
    """
    if research_calls <= 1:
        return [("Full destination research", _compose_brief(state, default_topics))]
    available = clusters if clusters is not None else RESEARCH_TOPIC_CLUSTERS
    selected = available[: max(1, research_calls)]
    return [
        (label, _compose_cluster_brief(state, label, details))
        for label, details in selected
    ]


def build_knowledge_builder_graph(
    llm: BaseChatModel,
    *,
    prompt_provider: IPromptProvider,
    deep_research_client: IDeepResearchClient,
    ingestion_service: IIngestionService,
    kb_status_service: KBStatusService,
    default_topics: list[str] | None = None,
    research_calls: int = 1,
    research_max_concurrency: int = 3,
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
        briefs = plan_research_briefs(state, topics, research_calls=research_calls)
        semaphore = asyncio.Semaphore(max(1, research_max_concurrency))

        async def run_brief(label: str, brief: str):
            async with semaphore:
                return label, await deep_research_client.research(brief)

        outcomes = await asyncio.gather(
            *(run_brief(label, brief) for label, brief in briefs),
            return_exceptions=True,
        )

        sections: list[str] = []
        sources: list[str] = []
        failures: list[str] = []
        for (label, _), outcome in zip(briefs, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning("deep_research cluster %r failed: %s", label, outcome)
                failures.append(f"{label}: {outcome}")
                continue
            _, result = outcome
            if result.content.strip():
                heading = f"## {label}" if len(briefs) > 1 else ""
                sections.append(f"{heading}\n\n{result.content}".strip())
                sources.extend(result.sources)

        if not sections:
            exc_text = "; ".join(failures) or "empty research result"
            logger.error("deep_research failed for all %d briefs", len(briefs))
            await kb_status_service.mark_failed(
                destination_key=state["destination_key"],
                city=state.get("city"),
                country=state.get("country"),
                error_message=exc_text,
            )
            return {
                "error": f"deep research failed: {exc_text}",
                "messages": [
                    AIMessage(content="The deep research step failed. Please try again later.")
                ],
                **phases.phase_update(phases.KNOWLEDGE_BUILD, "Deep research failed."),
            }

        if failures:
            logger.warning(
                "deep_research partial: %d/%d clusters failed", len(failures), len(briefs)
            )

        return {
            "raw_research": "\n\n".join(sections),
            "research_sources": list(dict.fromkeys(sources)),
            **phases.phase_update(
                phases.KNOWLEDGE_BUILD, "Expanding the research with extra guidebook chapters, then storing it."
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
