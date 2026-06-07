"""Unit tests for knowledge-builder pure logic and graph assembly."""

from __future__ import annotations

from typing import Any

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
