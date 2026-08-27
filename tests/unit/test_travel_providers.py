"""Unit tests for Stage 10 travel providers (OSM adapters + factory flags)."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config.settings import Settings
from app.infrastructure.travel.factory import (
    build_flights_provider,
    build_hotels_provider,
    build_places_provider,
    build_transit_provider,
)
from app.infrastructure.travel.osm_places import NominatimPlacesProvider
from app.infrastructure.travel.osrm_transit import OSRMTransitProvider


def _settings(**overrides: Any) -> Settings:
    base = {
        "PLACES_PROVIDER": "none",
        "TRANSIT_PROVIDER": "none",
        "FLIGHTS_PROVIDER": "none",
        "HOTELS_PROVIDER": "none",
    }
    base.update(overrides)
    return Settings.model_validate(base)


# ── Factory flags ────────────────────────────────────────────────────────


def test_factory_returns_none_when_flags_off():
    s = _settings()
    assert build_places_provider(s) is None
    assert build_transit_provider(s) is None
    assert build_flights_provider(s) is None
    assert build_hotels_provider(s) is None


def test_factory_builds_osm_providers_when_enabled():
    s = _settings(PLACES_PROVIDER="osm", TRANSIT_PROVIDER="osrm")
    assert isinstance(build_places_provider(s), NominatimPlacesProvider)
    assert isinstance(build_transit_provider(s), OSRMTransitProvider)


# ── Nominatim places ─────────────────────────────────────────────────────


async def test_nominatim_search_pois_parses_results(monkeypatch):
    payload = [
        {
            "name": "Kinkaku-ji",
            "display_name": "Kinkaku-ji, Kita Ward, Kyoto, Japan",
            "class": "tourism",
            "type": "attraction",
            "lat": "35.0394",
            "lon": "135.7292",
        }
    ]
    provider = NominatimPlacesProvider(base_url="https://x", user_agent="t")

    async def fake_get(_path, _params):
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)
    pois = await provider.search_pois("temples in Kyoto")
    assert pois and pois[0].name == "Kinkaku-ji"
    assert pois[0].category == "attraction"
    assert (pois[0].lat, pois[0].lng) == (35.0394, 135.7292)


async def test_nominatim_returns_none_on_empty(monkeypatch):
    provider = NominatimPlacesProvider(base_url="https://x", user_agent="t")

    async def fake_get(_path, _params):
        return []

    monkeypatch.setattr(provider, "_get", fake_get)
    assert await provider.search_pois("nothing") is None


async def test_nominatim_geocode_skips_malformed(monkeypatch):
    provider = NominatimPlacesProvider(base_url="https://x", user_agent="t")

    async def fake_get(_path, _params):
        return [{"display_name": None, "lat": None}]

    monkeypatch.setattr(provider, "_get", fake_get)
    assert await provider.geocode("nowhere") is None


# ── OSRM transit ─────────────────────────────────────────────────────────


async def test_osrm_leg_parses_route(monkeypatch):
    payload = {"routes": [{"distance": 6500.0, "duration": 1020.0}]}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return payload

    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, *a: Any, **k: Any) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    provider = OSRMTransitProvider(base_url="https://x")
    leg = await provider.leg(34.98, 135.75, 35.03, 135.72)
    assert leg is not None
    assert leg["distance_km"] == 6.5
    assert leg["travel_minutes"] == 15  # 1020s = 17min, rounded to a 5-min step


async def test_osrm_leg_none_when_no_routes(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return {"routes": []}

    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, *a: Any, **k: Any) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    provider = OSRMTransitProvider(base_url="https://x")
    assert await provider.leg(0, 0, 1, 1) is None


# ── Mock APIs (TRAVEL_MOCK_APIS) ───────────────────────────────────────────


def test_factory_builds_all_mocks_when_master_flag_on():
    from app.infrastructure.travel.mock_providers import (
        MockFlightsProvider,
        MockHotelsProvider,
        MockPlacesProvider,
        MockTransitProvider,
    )

    s = _settings(TRAVEL_MOCK_APIS=True)
    assert isinstance(build_places_provider(s), MockPlacesProvider)
    assert isinstance(build_transit_provider(s), MockTransitProvider)
    assert isinstance(build_flights_provider(s), MockFlightsProvider)
    assert isinstance(build_hotels_provider(s), MockHotelsProvider)


def test_mock_flag_overrides_per_provider_none():
    """Master mock flag wins even when per-provider flags stay at none."""
    from app.infrastructure.travel.mock_providers import MockHotelsProvider

    s = _settings(TRAVEL_MOCK_APIS=True, HOTELS_PROVIDER="none", PLACES_PROVIDER="none")
    assert isinstance(build_hotels_provider(s), MockHotelsProvider)


async def test_mock_hotels_and_flights_for_curated_cities():
    from app.infrastructure.travel.mock_data import list_mock_city_keys
    from app.infrastructure.travel.mock_providers import MockFlightsProvider, MockHotelsProvider

    hotels = MockHotelsProvider()
    flights = MockFlightsProvider()
    for key in list_mock_city_keys():
        dest = {
            "london": "London",
            "paris": "Paris",
            "rome": "Roma",
            "berlin": "Berlin",
            "new_york": "New York",
            "damascus": "Damascus",
            "los_angeles": "Los Angeles",
        }[key]
        h = await hotels.search(destination=dest, budget="mid")
        f = await flights.search(origin="JFK", destination=dest)
        assert h and len(h) >= 2
        assert f and len(f) >= 2
        assert all(item.lat is not None for item in h)


async def test_mock_places_filters_food_and_geocodes():
    from app.infrastructure.travel.mock_providers import MockPlacesProvider

    places = MockPlacesProvider()
    food = await places.search_pois("best restaurants and street food in Paris")
    assert food and all(p.category == "restaurant" for p in food)

    geo = await places.geocode("Eiffel Tower, Paris")
    assert geo is not None
    assert geo.name == "Eiffel Tower"
    assert geo.lat is not None


async def test_mock_unknown_city_returns_none():
    from app.infrastructure.travel.mock_providers import MockHotelsProvider, MockPlacesProvider

    assert await MockHotelsProvider().search(destination="Atlantis", budget="any") is None
    assert await MockPlacesProvider().search_pois("attractions in Atlantis") is None


async def test_mock_transit_leg_returns_routed_estimate():
    from app.infrastructure.travel.mock_providers import MockTransitProvider

    leg = await MockTransitProvider().leg(48.8566, 2.3522, 48.8584, 2.2945)
    assert leg is not None
    assert leg["distance_km"] > 0
    assert leg["travel_minutes"] >= 5


async def test_specialist_uses_mock_hotels_without_llm():
    """Hotels provider hit becomes specialist output; LLM is never called."""
    from app.infrastructure.travel.mock_providers import MockHotelsProvider
    from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.specialists import (  # noqa: E501
        make_specialist_node,
    )

    class _BoomLLM:
        async def ainvoke(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("LLM should not run when mock hotels hit")

    class _FakePrompts:
        def resolve_prompt(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("prompts unused on provider hit")

    node = make_specialist_node(
        "hotels",
        llm=_BoomLLM(),  # type: ignore[arg-type]
        prompt_provider=_FakePrompts(),  # type: ignore[arg-type]
        web_search_tool=None,
        hotels_provider=MockHotelsProvider(),
    )
    result = await node(
        {
            "requirements": {
                "destination_city": "Damascus",
                "destination_country": "Syria",
                "budget": "mid",
            }
        }
    )  # type: ignore[arg-type]
    items = result["specialist_outputs"]["hotels"]
    assert items and items[0]["name"]
    assert result["phase"] == "planning"
