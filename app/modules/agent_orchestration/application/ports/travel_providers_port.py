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

    async def search_destinations(
        self, query: str, *, limit: int = 5
    ) -> list[dict[str, str | None]] | None:
        """Resolve city/country candidates for trip destinations.

        Each item: ``{"city", "country", "label"}``. Default: single ``geocode`` hit.
        Override for multi-result disambiguation (misspellings / same-name cities).
        """
        hit = await self.geocode(query)
        if hit is None:
            return None
        # Best-effort split of "City, Country, …" from notes/display.
        notes = (hit.notes or hit.name or "").strip()
        parts = [p.strip() for p in notes.split(",") if p.strip()]
        city = hit.name
        country = parts[-1] if len(parts) > 1 else None
        label = ", ".join(p for p in (city, country) if p) or hit.name
        return [{"city": city, "country": country, "label": label}]


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
