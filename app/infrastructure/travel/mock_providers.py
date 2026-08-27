"""Offline mock travel providers powered by curated city fixtures.

Activated when ``TRAVEL_MOCK_APIS=true``. Returns ``None`` for unknown
destinations so specialists can fall back to web search. Never touches the
knowledge-builder path — city_expert still detects KB misses independently.
"""

from __future__ import annotations

import math
from typing import Any

from app.infrastructure.travel.mock_data import city_from_free_text, lookup_city
from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IFlightsProvider,
    IHotelsProvider,
    IPlacesProvider,
    ITransitProvider,
)
from app.modules.agent_orchestration.domain.schemas.travel_plan import (
    POI,
    FlightOption,
    HotelOption,
)

_EARTH_KM = 6371.0
# Mock "routed" travel is ~1.3x straight-line, at a blended urban speed.
_ROUTE_FACTOR = 1.3
_KMH = 25.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def _budget_band(budget: str) -> str:
    b = (budget or "").lower()
    if any(w in b for w in ("budget", "cheap", "hostel", "low")):
        return "budget"
    if any(w in b for w in ("luxury", "upscale", "high", "5-star", "splurge")):
        return "luxury"
    return "mid"


class MockPlacesProvider(IPlacesProvider):
    async def search_pois(self, query: str, *, limit: int = 8) -> list[POI] | None:
        city = lookup_city(query) or city_from_free_text(query)
        if city is None:
            return None
        q = query.lower()
        pois = city["pois"]
        if "restaurant" in q or "food" in q or "cuisine" in q:
            pois = [p for p in pois if p.get("category") == "restaurant"] or pois
        elif "museum" in q or "attraction" in q or "landmark" in q:
            pois = [p for p in pois if p.get("category") != "restaurant"] or pois
        items = [POI.model_validate(p) for p in pois[:limit]]
        return items or None

    async def geocode(self, place: str) -> POI | None:
        # Exact POI name match within a city ("Louvre Museum, Paris").
        city = city_from_free_text(place) or lookup_city(place)
        name_part = place.split(",")[0].strip().lower()
        if city is not None:
            for raw in city["pois"] + city["hotels"]:
                if str(raw.get("name", "")).strip().lower() == name_part:
                    return POI(
                        name=str(raw["name"]),
                        category=str(raw.get("category") or "attraction"),
                        lat=raw.get("lat"),
                        lng=raw.get("lng"),
                        notes=str(raw.get("notes") or ""),
                    )
            lat, lng = city["center"]
            return POI(
                name=city["display_name"],
                category="neighborhood",
                lat=lat,
                lng=lng,
                notes=f"City centre of {city['display_name']}",
            )
        return None


class MockTransitProvider(ITransitProvider):
    async def leg(
        self, from_lat: float, from_lng: float, to_lat: float, to_lng: float
    ) -> dict[str, Any] | None:
        dist = _haversine_km(from_lat, from_lng, to_lat, to_lng) * _ROUTE_FACTOR
        minutes = max(5, int(round((dist / _KMH * 60) / 5.0) * 5))
        return {"distance_km": round(dist, 2), "travel_minutes": minutes}


class MockFlightsProvider(IFlightsProvider):
    async def search(self, *, origin: str, destination: str) -> list[FlightOption] | None:
        city = lookup_city(destination) or city_from_free_text(destination)
        if city is None:
            return None
        return [FlightOption.model_validate(f) for f in city["flights"]]


class MockHotelsProvider(IHotelsProvider):
    async def search(self, *, destination: str, budget: str) -> list[HotelOption] | None:
        city = lookup_city(destination) or city_from_free_text(destination)
        if city is None:
            return None
        hotels = [HotelOption.model_validate(h) for h in city["hotels"]]
        band = _budget_band(budget)
        if band == "budget":
            hotels = sorted(hotels, key=lambda h: h.nightly_rate_usd or 0)
        elif band == "luxury":
            hotels = sorted(hotels, key=lambda h: h.nightly_rate_usd or 0, reverse=True)
        return hotels