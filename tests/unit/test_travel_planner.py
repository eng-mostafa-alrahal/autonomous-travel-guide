"""Unit tests for travel-planner pure logic and graph assembly."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END
from langgraph.types import Send

from app.modules.agent_orchestration.domain.routing_rules.travel_planner_router import (
    PARALLEL_SPECIALISTS,
    SPECIALISTS,
    fan_out_specialists,
    route_after_requirements,
)
from app.modules.agent_orchestration.domain.schemas.trip_requirements import TripRequirements
from app.modules.agent_orchestration.domain.states.travel_planner_state import (
    merge_specialist_outputs,
)


def test_trip_requirements_missing_when_empty():
    req = TripRequirements()
    assert set(req.missing_required()) == {"destination", "origin", "num_days", "budget"}
    assert req.is_complete() is False


def test_trip_requirements_complete_with_city_only():
    req = TripRequirements(
        destination_city="Paris", origin_city="New York", num_days=3, budget="$1000"
    )
    assert req.missing_required() == []
    assert req.is_complete() is True


def test_trip_requirements_country_satisfies_destination():
    req = TripRequirements(
        destination_country="Japan", origin_city="Seoul", num_days=5, budget="mid-range"
    )
    assert "destination" not in req.missing_required()


def test_trip_requirements_missing_origin():
    req = TripRequirements(destination_city="Paris", num_days=3, budget="$1000")
    assert req.missing_required() == ["origin"]
    assert req.is_complete() is False


def test_trip_requirements_origin_alias_coerced():
    req = TripRequirements.model_validate(
        {
            "destination_city": "Rome",
            "from_city": "Lisbon",
            "num_days": 4,
            "budget": "€2000",
        }
    )
    assert req.origin_city == "Lisbon"
    assert req.is_complete() is True


def test_trip_requirements_interests_coerced_from_string():
    req = TripRequirements.model_validate({"interests": "food"})
    assert req.interests == ["food"]


def test_route_after_requirements_incomplete():
    state = {"requirements_complete": False}
    assert route_after_requirements(state) == "ask_requirements"  # type: ignore[arg-type]


def test_route_after_requirements_complete():
    state = {"requirements_complete": True}
    assert route_after_requirements(state) == "city_expert"  # type: ignore[arg-type]


def test_route_after_requirements_error():
    state = {"error": "x", "requirements_complete": True}
    assert route_after_requirements(state) == "end"  # type: ignore[arg-type]


def test_fan_out_sends_each_parallel_specialist():
    # After city_expert, the remaining specialists fan out to run concurrently.
    sends = fan_out_specialists({"kb_miss": False})  # type: ignore[arg-type]
    assert isinstance(sends, list)
    assert {s.node for s in sends} == {"hotels", "flights_logistics", "food"}
    assert all(isinstance(s, Send) for s in sends)
    # Each Send carries a snapshot of the state (so requirements are available).
    assert all(isinstance(s.arg, dict) for s in sends)


def test_fan_out_ends_on_kb_miss():
    # A fresh KB miss ends the planner early so the knowledge builder runs first.
    state = {"kb_miss": True, "kb_build_attempted": False}
    assert fan_out_specialists(state) == END  # type: ignore[arg-type]


def test_fan_out_continues_after_build_attempted():
    # After a build attempt (approved or rejected), don't re-trigger the builder.
    sends = fan_out_specialists({"kb_miss": True, "kb_build_attempted": True})  # type: ignore[arg-type]
    assert isinstance(sends, list)
    assert len(sends) == len(PARALLEL_SPECIALISTS)


def test_fan_out_ends_on_error():
    assert fan_out_specialists({"error": "x"}) == END  # type: ignore[arg-type]


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
    expected = {
        "collect_requirements",
        "ask_requirements",
        "spatial_cluster",
        "synthesize_itinerary",
    }
    expected |= set(SPECIALISTS)
    assert expected <= nodes
