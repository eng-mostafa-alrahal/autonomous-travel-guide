"""End-to-end graph test for the travel master: KB miss -> approve -> re-plan.

Drives the *compiled* master graph (with an in-memory checkpointer) through a
full cycle using fakes — no DB, LLM, or network. It exercises the real
interrupt/resume + cross-graph routing wiring:

1. city_expert finds an empty (but operational) KB -> requests a build, planner ends.
2. master routes to the knowledge builder, which interrupts for approval.
3. resume with "approve" -> research -> dedup -> ingest (KB now populated).
4. master re-plans; city_expert now answers from RAG and the itinerary is produced.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.modules.agent_orchestration.application.ports.deep_research_port import (
    DeepResearchResult,
    IDeepResearchClient,
)
from app.modules.agent_orchestration.application.ports.ingestion_port import (
    DestinationRef,
    IIngestionService,
    IngestionResult,
    IngestionSegment,
)
from app.modules.agent_orchestration.domain.schemas.knowledge_prep import (
    KnowledgeSegment,
    PreparedKnowledge,
)
from app.modules.agent_orchestration.domain.schemas.travel_plan import (
    POI,
    FlightOption,
    FlightOptionList,
    HotelOption,
    HotelOptionList,
    POIList,
)
from app.modules.agent_orchestration.domain.schemas.trip_requirements import TripRequirements


class _Resp:
    content = "A wonderful 3-day itinerary for the destination."


class _FakeStructured:
    """Returns a schema-appropriate object for structured-output calls."""

    def __init__(self, schema: type) -> None:
        self._schema = schema

    async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
        if self._schema is TripRequirements:
            return TripRequirements(destination_city="Atlantis", num_days=3, budget="$1500")
        if self._schema is PreparedKnowledge:
            return PreparedKnowledge(
                segments=[KnowledgeSegment(topic="history", content="Atlantis lore.")]
            )
        if self._schema is POIList:
            return POIList(
                items=[POI(name="Poseidon Temple", category="landmark", lat=36.3, lng=25.4)]
            )
        if self._schema is HotelOptionList:
            return HotelOptionList(
                items=[HotelOption(name="Coral Suites", area="Harbor", nightly_rate_usd=180)]
            )
        if self._schema is FlightOptionList:
            return FlightOptionList(
                items=[FlightOption(summary="Ferry + flight via Athens", price_usd=320)]
            )
        return self._schema()


class _FakeLLM:
    async def ainvoke(self, *_a: Any, **_k: Any) -> _Resp:
        return _Resp()

    def with_structured_output(self, schema: type) -> _FakeStructured:
        return _FakeStructured(schema)


class _Doc:
    def __init__(self, content: str) -> None:
        self.page_content = content


class _Retriever:
    def __init__(self, docs: list[_Doc]) -> None:
        self._docs = docs

    def invoke(self, _query: str) -> list[_Doc]:
        return self._docs


class _FakeResearch(IDeepResearchClient):
    async def research(self, brief: str) -> DeepResearchResult:
        return DeepResearchResult(content="Atlantis is an ancient sea city.", sources=["src://1"])


class _FakeKBStatus:
    """Duck-typed stand-in for KBStatusService (no DB)."""

    async def mark_building(self, **_k: Any) -> None: ...
    async def mark_ready(self, **_k: Any) -> None: ...
    async def mark_failed(self, **_k: Any) -> None: ...
    async def get_status(self, _key: str) -> None:
        return None


def _build_compiled(ingest_state: dict[str, bool]):
    from app.core.config.settings import get_settings
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.travel_master_builder import (  # noqa: E501
        build_travel_master_graph,
    )
    from app.modules.agent_orchestration.infrastructure.registries.file_prompt_registry import (
        FilePromptRegistry,
    )

    class _FakeIngest(IIngestionService):
        async def ingest(
            self, segments: list[IngestionSegment], *, destination: DestinationRef
        ) -> IngestionResult:
            ingest_state["ingested"] = True
            return IngestionResult(doc_count=len(segments), ids=["doc-1"])

    def retriever_provider(_key: str) -> _Retriever:
        # Operational KB: empty before ingestion, populated afterwards.
        if ingest_state["ingested"]:
            return _Retriever([_Doc("Atlantis history, culture, and cuisine.")])
        return _Retriever([])

    settings = get_settings()
    prompt_provider = FilePromptRegistry(
        assets_dir=settings.resolve_prompt_assets_dir(),
        registry_path=settings.resolve_prompt_registry_path(),
    )
    master = build_travel_master_graph(
        llm=_FakeLLM(),  # type: ignore[arg-type]
        prompt_provider=prompt_provider,
        deep_research_client=_FakeResearch(),
        ingestion_service=_FakeIngest(),
        kb_status_service=_FakeKBStatus(),  # type: ignore[arg-type]
        retriever_provider=retriever_provider,  # type: ignore[arg-type]
    )
    return master.compile(checkpointer=MemorySaver())


def _initial_state(message: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=message)],
        "session_id": "s1",
        "user_id": "u1",
        "error": None,
        "human_feedback": None,
        "requirements": {},
        "requirements_complete": False,
        "missing_slots": [],
        "specialist_outputs": {},
        "itinerary": None,
        "destination_key": "",
        "city": None,
        "country": None,
        "topics": [],
        "approved": None,
        "raw_research": None,
        "research_sources": [],
        "prepared_segments": [],
        "doc_count": 0,
        "kb_miss": False,
        "kb_build_attempted": False,
    }


async def test_kb_miss_approve_replans_and_produces_itinerary():
    ingest_state = {"ingested": False}
    app = _build_compiled(ingest_state)
    config = {"configurable": {"thread_id": "trip-1"}}

    # Pass 1: runs until the knowledge-builder approval interrupt.
    await app.ainvoke(_initial_state("Plan me 3 days in Atlantis, budget $1500"), config)
    snapshot = app.get_state(config)
    assert snapshot.next, "graph should be paused awaiting approval"
    assert snapshot.values["kb_miss"] is True
    assert ingest_state["ingested"] is False  # nothing stored before approval

    # Approve -> research/dedup/ingest -> re-plan -> itinerary.
    await app.ainvoke(Command(resume={"action": "approve"}), config)
    final = app.get_state(config)

    assert not final.next, "graph should be finished"
    assert ingest_state["ingested"] is True  # KB populated on approval
    assert final.values["kb_build_attempted"] is True
    assert final.values["doc_count"] == 1
    assert final.values["itinerary"]
    assert "city_expert" in final.values["specialist_outputs"]
    # Stage 8: the parallel specialists fanned out and merged their outputs.
    assert {"hotels", "flights_logistics", "food"} <= set(final.values["specialist_outputs"])
    assert final.values["clusters"], "spatial clustering should run after the specialists"


async def test_stream_reports_phase_progress_from_inside_subgraphs():
    """Phase lines must reach the stream while the slow work is still ahead."""
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.mappers.state_mapper import (  # noqa: E501
        to_agent_events,
    )

    ingest_state = {"ingested": False}
    app = _build_compiled(ingest_state)
    config = {"configurable": {"thread_id": "trip-3"}}

    async def collect(graph_input: Any) -> list[tuple[str | None, str]]:
        seen: list[tuple[str | None, str]] = []
        async for namespace, chunk in app.astream(graph_input, config, subgraphs=True):
            for event in to_agent_events(chunk, namespace=namespace):
                if event.phase_status and (event.phase, event.phase_status) not in seen:
                    seen.append((event.phase, event.phase_status))
        return seen

    first_pass = await collect(_initial_state("Plan me 3 days in Atlantis, budget $1500"))
    statuses = [status for _phase, status in first_pass]

    # Requirements -> KB miss, all before the interrupt. (city_expert now runs
    # first as the gate; on a KB miss it short-circuits to the build request.)
    assert ("requirements", "Getting started on your trip plan.") in first_pass
    assert any("bringing in the specialists" in s for s in statuses)
    assert any("asking to run deep research" in s for s in statuses)

    second_pass = await collect(Command(resume={"action": "approve"}))
    build_statuses = [status for _phase, status in second_pass]

    # The long research/ingest steps announce themselves before they run.
    assert any("this can take a few minutes" in s for s in build_statuses)
    assert any("Sorting through the research findings" in s for s in build_statuses)
    assert any("Knowledge base ready" in s for s in build_statuses)
    assert any("Re-planning" in s for s in build_statuses)
    assert ("done", "Your itinerary is ready.") in second_pass


async def test_kb_miss_reject_uses_web_fallback_without_storing():
    ingest_state = {"ingested": False}
    app = _build_compiled(ingest_state)
    config = {"configurable": {"thread_id": "trip-2"}}

    await app.ainvoke(_initial_state("Plan me 3 days in Atlantis, budget $1500"), config)
    assert app.get_state(config).next

    # Reject -> builder ends without ingesting; planner falls back to web search.
    await app.ainvoke(Command(resume={"action": "reject"}), config)
    final = app.get_state(config)

    assert not final.next
    assert ingest_state["ingested"] is False  # nothing stored on rejection
    assert final.values["kb_build_attempted"] is True
    assert final.values["itinerary"]
    assert "city_expert" in final.values["specialist_outputs"]
