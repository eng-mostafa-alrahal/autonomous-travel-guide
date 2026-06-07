"""Unit tests for travel master graph wiring (planner <-> knowledge builder)."""

from __future__ import annotations

from typing import Any

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
from app.modules.agent_orchestration.domain.routing_rules.travel_planner_router import (
    route_after_city_expert,
)
from app.modules.agent_orchestration.domain.routing_rules.travel_root_router import (
    route_after_planner,
)


def test_route_after_planner_triggers_build_on_fresh_miss():
    state = {"kb_miss": True, "kb_build_attempted": False}
    assert route_after_planner(state) == "knowledge_builder"  # type: ignore[arg-type]


def test_route_after_planner_finalizes_when_already_attempted():
    state = {"kb_miss": True, "kb_build_attempted": True}
    assert route_after_planner(state) == "finalize"  # type: ignore[arg-type]


def test_route_after_planner_finalizes_without_miss():
    assert route_after_planner({"kb_miss": False}) == "finalize"  # type: ignore[arg-type]


def test_route_after_city_expert_ends_on_fresh_miss():
    state = {"kb_miss": True, "kb_build_attempted": False}
    assert route_after_city_expert(state) == "end"  # type: ignore[arg-type]


def test_route_after_city_expert_continues_after_attempt():
    state = {"kb_miss": True, "kb_build_attempted": True}
    assert route_after_city_expert(state) == "delegate"  # type: ignore[arg-type]


def test_route_after_city_expert_continues_without_miss():
    assert route_after_city_expert({}) == "delegate"  # type: ignore[arg-type]


def test_travel_master_graph_compiles():
    from app.core.config.settings import get_settings
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.travel_master_builder import (  # noqa: E501
        build_travel_master_graph,
    )
    from app.modules.agent_orchestration.infrastructure.registries.file_prompt_registry import (
        FilePromptRegistry,
    )

    class _Resp:
        content = "ok"

    class _FakeStructured:
        async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
            return _Resp()

    class _FakeLLM:
        async def ainvoke(self, *_a: Any, **_k: Any) -> _Resp:
            return _Resp()

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
    master = build_travel_master_graph(
        llm=_FakeLLM(),  # type: ignore[arg-type]
        prompt_provider=prompt_provider,
        deep_research_client=_FakeResearch(),
        ingestion_service=_FakeIngest(),
        kb_status_service=KBStatusService(uow_factory=lambda: None),  # type: ignore[arg-type]
    )
    compiled = master.compile()
    nodes = set(compiled.get_graph().nodes.keys())
    assert {"travel_root", "planner", "knowledge_builder", "after_build", "error_handler"} <= nodes
