"""Unit tests for knowledge-builder pure logic and graph assembly."""

from __future__ import annotations

from typing import Any

import pytest

from app.infrastructure.ingestion.chunking import chunk_text
from app.modules.agent_orchestration.domain.kb_destination import build_destination_key
from app.modules.agent_orchestration.domain.routing_rules.knowledge_builder_router import (
    route_after_confirm,
    route_after_ingest,
    route_after_research,
)
from app.modules.agent_orchestration.domain.schemas.knowledge_prep import PreparedKnowledge


def test_route_after_confirm_approved():
    assert route_after_confirm({"approved": True}) == "deep_research"  # type: ignore[arg-type]


def test_route_after_confirm_rejected():
    assert route_after_confirm({"approved": False}) == "end"  # type: ignore[arg-type]


def test_route_after_confirm_error_short_circuits():
    assert route_after_confirm({"error": "x", "approved": True}) == "end"  # type: ignore[arg-type]


def test_route_after_research():
    assert route_after_research({"error": None}) == "deduplicate"  # type: ignore[arg-type]
    assert route_after_research({"error": "x"}) == "end"  # type: ignore[arg-type]


def test_route_after_ingest():
    assert route_after_ingest({"error": None}) == "notify_complete"  # type: ignore[arg-type]
    assert route_after_ingest({"error": "x"}) == "end"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ingest_retries_same_segments_then_succeeds():
    from app.modules.agent_orchestration.application.ports.ingestion_port import (
        DestinationRef,
        IIngestionService,
        IngestionResult,
        IngestionSegment,
    )
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.knowledge_builder.knowledge_builder_graph import (  # noqa: E501
        ingest_segments_with_retries,
    )

    calls: list[int] = []

    class _Flaky(IIngestionService):
        async def ingest(
            self, segments: list[IngestionSegment], *, destination: DestinationRef
        ) -> IngestionResult:
            calls.append(len(segments))
            if len(calls) < 3:
                raise RuntimeError(f"transient-{len(calls)}")
            return IngestionResult(doc_count=len(segments), ids=["a"])

    segments = [IngestionSegment(topic="history", content="lore", source="deep_research")]
    dest = DestinationRef(destination_key="atlantis|", city="Atlantis")
    result = await ingest_segments_with_retries(
        _Flaky(), segments, dest, max_attempts=3, retry_delay_s=0
    )
    assert result.doc_count == 1
    assert calls == [1, 1, 1]  # same payload each attempt; no re-research


@pytest.mark.asyncio
async def test_ingest_retries_exhausted_raises():
    from app.modules.agent_orchestration.application.ports.ingestion_port import (
        DestinationRef,
        IIngestionService,
        IngestionResult,
        IngestionSegment,
    )
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.knowledge_builder.knowledge_builder_graph import (  # noqa: E501
        ingest_segments_with_retries,
    )

    class _AlwaysFail(IIngestionService):
        async def ingest(
            self, segments: list[IngestionSegment], *, destination: DestinationRef
        ) -> IngestionResult:
            raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="down"):
        await ingest_segments_with_retries(
            _AlwaysFail(),
            [IngestionSegment(topic="t", content="c")],
            DestinationRef(destination_key="x|"),
            max_attempts=3,
            retry_delay_s=0,
        )


def test_build_destination_key_normalizes():
    assert build_destination_key(city="  Paris ", country="France") == "paris|france"
    assert build_destination_key(city=None, country="Japan") == "|japan"


def test_chunk_text_splits_long_content():
    chunks = chunk_text("para one.\n\npara two.\n\n" + ("z" * 3000), chunk_size=1200, overlap=150)
    assert len(chunks) >= 2
    assert all(len(c) <= 1200 for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("   ") == []


def test_prepared_knowledge_alias_normalization():
    pk = PreparedKnowledge.model_validate({"sections": [{"topic": "Food", "content": "c"}]})
    assert pk.segments[0].topic == "Food"
    assert pk.segments[0].content == "c"


def test_prepared_knowledge_defaults_empty():
    assert PreparedKnowledge.model_validate({}).segments == []


def test_split_research_sections_on_h2():
    from app.modules.agent_orchestration.domain.research_sections import (
        split_research_sections,
        topic_slug,
    )

    raw = "## History\n\nFounded in 753 BC.\n\n## Food\n\nTry cacio e pepe."
    sections = split_research_sections(raw)
    assert [label for label, _ in sections] == ["History", "Food"]
    assert "753" in sections[0][1]
    assert topic_slug("History, Culture & Identity") == "history_culture_identity"


def test_split_research_sections_without_headings_keeps_all():
    from app.modules.agent_orchestration.domain.research_sections import split_research_sections

    raw = "One long report with no headings."
    assert split_research_sections(raw) == [("full_destination_research", raw)]


def test_knowledge_builder_graph_compiles():
    from app.core.config.settings import get_settings
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
    from app.modules.agent_orchestration.application.use_cases.kb_status_service import (
        KBStatusService,
    )
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.knowledge_builder.knowledge_builder_graph import (  # noqa: E501
        build_knowledge_builder_graph,
    )
    from app.modules.agent_orchestration.infrastructure.registries.file_prompt_registry import (
        FilePromptRegistry,
    )

    class _FakeStructured:
        async def ainvoke(self, *_a: Any, **_k: Any) -> PreparedKnowledge:
            return PreparedKnowledge(segments=[])

    class _FakeLLM:
        def with_structured_output(self, _schema: Any) -> _FakeStructured:
            return _FakeStructured()

    class _FakeResearch(IDeepResearchClient):
        async def research(self, brief: str) -> DeepResearchResult:
            return DeepResearchResult(content="x", sources=[])

    class _FakeIngest(IIngestionService):
        async def ingest(
            self, segments: list[IngestionSegment], *, destination: DestinationRef
        ) -> IngestionResult:
            return IngestionResult(doc_count=len(segments), ids=[])

    settings = get_settings()
    prompt_provider = FilePromptRegistry(
        assets_dir=settings.resolve_prompt_assets_dir(),
        registry_path=settings.resolve_prompt_registry_path(),
    )
    graph = build_knowledge_builder_graph(
        _FakeLLM(),  # type: ignore[arg-type]
        prompt_provider=prompt_provider,
        deep_research_client=_FakeResearch(),
        ingestion_service=_FakeIngest(),
        kb_status_service=KBStatusService(uow_factory=lambda: None),  # type: ignore[arg-type]
    )
    compiled = graph.compile()
    nodes = set(compiled.get_graph().nodes.keys())
    assert {
        "confirm_build",
        "deep_research",
        "deduplicate",
        "ingest",
        "notify_complete",
    } <= nodes
