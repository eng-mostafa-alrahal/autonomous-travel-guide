"""Unit tests for travel-planner pure logic and graph assembly."""

from __future__ import annotations

from typing import Any

from app.modules.agent_orchestration.domain.routing_rules.travel_planner_router import (
    SPECIALISTS,
    route_after_requirements,
    route_specialist,
)
from app.modules.agent_orchestration.domain.schemas.trip_requirements import TripRequirements
from app.modules.agent_orchestration.domain.states.travel_planner_state import (
    merge_specialist_outputs,
)


def test_trip_requirements_missing_when_empty():
    req = TripRequirements()
    assert set(req.missing_required()) == {"destination", "num_days", "budget"}
    assert req.is_complete() is False


def test_trip_requirements_complete_with_city_only():
    req = TripRequirements(destination_city="Paris", num_days=3, budget="$1000")
    assert req.missing_required() == []
    assert req.is_complete() is True


def test_trip_requirements_country_satisfies_destination():
    req = TripRequirements(destination_country="Japan", num_days=5, budget="mid-range")
    assert "destination" not in req.missing_required()


def test_trip_requirements_interests_coerced_from_string():
    req = TripRequirements.model_validate({"interests": "food"})
    assert req.interests == ["food"]


def test_route_after_requirements_incomplete():
    state = {"requirements_complete": False}
    assert route_after_requirements(state) == "ask_requirements"  # type: ignore[arg-type]


def test_route_after_requirements_complete():
    state = {"requirements_complete": True}
    assert route_after_requirements(state) == "delegate"  # type: ignore[arg-type]


def test_route_after_requirements_error():
    state = {"error": "x", "requirements_complete": True}
    assert route_after_requirements(state) == "end"  # type: ignore[arg-type]


def test_route_specialist_returns_next():
    assert route_specialist({"next_specialist": "hotels"}) == "hotels"  # type: ignore[arg-type]


def test_route_specialist_synthesizes_when_done():
    assert route_specialist({"next_specialist": None}) == "synthesize"  # type: ignore[arg-type]


def test_merge_specialist_outputs():
    merged = merge_specialist_outputs({"hotels": "a"}, {"food": "b"})
    assert merged == {"hotels": "a", "food": "b"}


def test_travel_planner_graph_compiles():
    from app.core.config.settings import get_settings
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.travel_planner_graph import (  # noqa: E501
        build_travel_planner_graph,
    )
    from app.modules.agent_orchestration.infrastructure.registries.file_prompt_registry import (
        FilePromptRegistry,
    )

    class _Resp:
        content = "ok"

    class _FakeLLM:
        async def ainvoke(self, *_a: Any, **_k: Any) -> _Resp:
            return _Resp()

        def with_structured_output(self, _schema: Any) -> _FakeLLM:
            return self

    settings = get_settings()
    prompt_provider = FilePromptRegistry(
        assets_dir=settings.resolve_prompt_assets_dir(),
        registry_path=settings.resolve_prompt_registry_path(),
    )
    graph = build_travel_planner_graph(
        _FakeLLM(),  # type: ignore[arg-type]
        prompt_provider=prompt_provider,
    )
    compiled = graph.compile()
    nodes = set(compiled.get_graph().nodes.keys())
    expected = {"collect_requirements", "ask_requirements", "delegate", "synthesize_itinerary"}
    expected |= set(SPECIALISTS)
    assert expected <= nodes
