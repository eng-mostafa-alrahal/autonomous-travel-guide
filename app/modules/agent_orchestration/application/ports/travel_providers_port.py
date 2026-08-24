"""Travel data-provider contracts (Stage 10).

Each specialist (hotels / flights_logistics / food / city_expert) and the spatial
clustering node can source data from a real provider *or* fall back to web
search. A provider returns ``None`` when it has nothing to offer (feature-flag
off, no result, or any error) — the caller then falls back. Returning ``None``
rather than raising keeps the planning hot path resilient and CI offline.

The contracts reuse the existing structured-output schemas as the data shapes,
so swapping web-search → provider is transparent to downstream nodes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.modules.agent_orchestration.domain.schemas.travel_plan import (
    POI,
    FlightOption,
    HotelOption,
)


class IPlacesProvider(ABC):
    """Geocoding + points-of-interest lookup (e.g. OpenStreetMap/Nominatim)."""

    @abstractmethod
    async def search_pois(self, query: str, *, limit: int = 8) -> list[POI] | None:
        """POIs matching ``query`` (name + lat/lng), or None to fall back."""
        ...

    @abstractmethod
    async def geocode(self, place: str) -> POI | None:
        """Best single match for a place name with coordinates, or None."""
        ...


class ITransitProvider(ABC):
    """Travel time/distance between two points (e.g. OSRM routing)."""

    @abstractmethod
    async def leg(
        self, from_lat: float, from_lng: float, to_lat: float, to_lng: float
    ) -> dict[str, Any] | None:
        """``{"distance_km": float, "travel_minutes": int}`` or None to fall back."""
        ...


class IFlightsProvider(ABC):
    """Flight/route options between origin and destination."""

    @abstractmethod
    async def search(self, *, origin: str, destination: str) -> list[FlightOption] | None: ...


class IHotelsProvider(ABC):
    """Lodging options for a destination."""

    @abstractmethod
    async def search(self, *, destination: str, budget: str) -> list[HotelOption] | None: ...
