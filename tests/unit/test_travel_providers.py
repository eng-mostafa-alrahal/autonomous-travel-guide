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
