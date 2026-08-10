"""Unit tests for structured specialist outputs (Stage 6)."""

from __future__ import annotations

from typing import Any

from app.modules.agent_orchestration.domain.schemas.travel_plan import (
    POI,
    FlightOptionList,
    HotelOptionList,
    POIList,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.itinerary import (  # noqa: E501
    _format_notes,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.specialists import (  # noqa: E501
    make_specialist_node,
)


def test_poi_list_accepts_wrapper_alias():
    out = POIList.model_validate({"pois": [{"name": "Fushimi Inari", "category": "landmark"}]})
    assert len(out.items) == 1
    assert out.items[0].name == "Fushimi Inari"


def test_poi_list_tolerates_extra_llm_fields():
    out = POIList.model_validate(
        {"items": [{"name": "Gion", "category": "neighborhood", "rating": 5, "best_time": "dusk"}]}
    )
    assert out.items[0].category == "neighborhood"


def test_hotel_list_alias_and_defaults():
    out = HotelOptionList.model_validate({"hotels": [{"name": "Capsule Inn"}]})
    assert out.items[0].nightly_rate_usd is None


def test_flight_list_alias():
    out = FlightOptionList.model_validate({"flights": [{"summary": "Direct, 2h"}]})
    assert out.items[0].price_usd is None


def test_format_notes_renders_structured_bullets():
    outputs = {
        "city_expert": [POI(name="Kinkaku-ji", category="landmark", lat=35.039, lng=135.729,
                            estimated_duration_min=90, notes="Golden pavilion.").model_dump()],
        "hotels": [{"name": "Station Hotel", "area": "Shimogyo", "nightly_rate_usd": 140.0}],
        "flights_logistics": [{"summary": "KIX arrival, Haruka express", "price_usd": 30.0}],
        "food": [{"name": "Nishiki Market", "category": "restaurant", "notes": "Street food."}],
    }
    notes = _format_notes(outputs)

    assert "## Local insights (points of interest)" in notes
    assert "Kinkaku-ji" in notes and "(35.039, 135.729)" in notes
    assert "## Lodging" in notes and "Shimogyo" in notes and "$140" in notes
    assert "## Travel & getting around" in notes and "KIX arrival" in notes
    assert "## Food & dining" in notes and "Nishiki Market" in notes


def test_format_notes_empty_outputs():
    assert _format_notes({}) == "(no specialist input available)"


async def test_specialist_node_returns_structured_items():
    """The hotels node must store validated dicts, not prose."""
    from app.core.config.settings import get_settings
    from app.modules.agent_orchestration.infrastructure.registries.file_prompt_registry import (
        FilePromptRegistry,
    )

    class _FakeStructured:
        def __init__(self, schema: type) -> None:
            self._schema = schema

        async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
            return self._schema.model_validate(
                {"items": [{"name": "Harbor Ryokan", "area": "Port", "nightly_rate_usd": 95}]}
            )

    class _FakeLLM:
        def with_structured_output(self, schema: type) -> _FakeStructured:
            return _FakeStructured(schema)

    settings = get_settings()
    prompt_provider = FilePromptRegistry(
        assets_dir=settings.resolve_prompt_assets_dir(),
        registry_path=settings.resolve_prompt_registry_path(),
    )
    node = make_specialist_node(
        "hotels",
        llm=_FakeLLM(),  # type: ignore[arg-type]
        prompt_provider=prompt_provider,
        web_search_tool=None,
    )
    requirements = {"destination_city": "Osaka", "num_days": 2, "budget": "low"}
    result = await node({"requirements": requirements})

    items = result["specialist_outputs"]["hotels"]
    assert items == [{"name": "Harbor Ryokan", "area": "Port", "nightly_rate_usd": 95,
                      "lat": None, "lng": None, "notes": ""}]
    assert all(isinstance(i, dict) for i in items)
    # The node announces itself (this also covers the KB re-plan fan-out).
    assert result["phase"] == "planning"
    assert "places to stay" in result["phase_status"]


async def test_specialist_nodes_run_concurrently():
    """Stage 8: hotels/flights/food fan out via Send and run in parallel.

    With a blocking fake LLM, three sequential specialists would need ~0.3s; run
    concurrently they should all finish in just over one 0.1s call.
    """
    import asyncio
    import time

    from app.core.config.settings import get_settings
    from app.modules.agent_orchestration.infrastructure.registries.file_prompt_registry import (
        FilePromptRegistry,
    )

    class _SlowStructured:
        def __init__(self, schema: type) -> None:
            self._schema = schema

        async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
            await asyncio.sleep(0.1)
            return self._schema.model_validate({"items": []})

    class _SlowLLM:
        def with_structured_output(self, schema: type) -> _SlowStructured:
            return _SlowStructured(schema)

    settings = get_settings()
    prompt_provider = FilePromptRegistry(
        assets_dir=settings.resolve_prompt_assets_dir(),
        registry_path=settings.resolve_prompt_registry_path(),
    )
    requirements = {"destination_city": "Osaka", "num_days": 2, "budget": "low"}
    nodes = [
        make_specialist_node(role, llm=_SlowLLM(), prompt_provider=prompt_provider, web_search_tool=None)  # type: ignore[arg-type]  # noqa: E501
        for role in ("hotels", "flights_logistics", "food")
    ]

    start = time.perf_counter()
    results = await asyncio.gather(*(n({"requirements": requirements}) for n in nodes))
    elapsed = time.perf_counter() - start

    assert elapsed < 0.25  # well under the 0.3s a sequential run would take
    assert {next(iter(r["specialist_outputs"])) for r in results} == {
        "hotels", "flights_logistics", "food",
    }
