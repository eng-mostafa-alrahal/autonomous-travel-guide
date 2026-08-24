"""Build travel data providers from settings (Stage 10).

Each builder returns the configured provider, or ``None`` when its flag is
``"none"`` — the signal for the specialist / clustering node to fall back to web
search or the distance heuristic. Adding a provider = add a ``Literal`` value to
the matching setting, implement the port, and branch here.
"""

from __future__ import annotations

from app.core.config.settings import Settings
from app.infrastructure.travel.osm_places import NominatimPlacesProvider
from app.infrastructure.travel.osrm_transit import OSRMTransitProvider
from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IFlightsProvider,
    IHotelsProvider,
    IPlacesProvider,
    ITransitProvider,
)


def build_places_provider(settings: Settings) -> IPlacesProvider | None:
    if settings.PLACES_PROVIDER == "osm":
        return NominatimPlacesProvider(
            base_url=settings.NOMINATIM_BASE_URL,
            user_agent=settings.NOMINATIM_USER_AGENT,
            timeout_s=settings.TRAVEL_PROVIDER_TIMEOUT_S,
        )
    return None


def build_transit_provider(settings: Settings) -> ITransitProvider | None:
    if settings.TRANSIT_PROVIDER == "osrm":
        return OSRMTransitProvider(
            base_url=settings.OSRM_BASE_URL,
            timeout_s=settings.TRAVEL_PROVIDER_TIMEOUT_S,
        )
    return None


def build_flights_provider(settings: Settings) -> IFlightsProvider | None:
    # No live flights adapter yet (needs a registered provider key).
    return None


def build_hotels_provider(settings: Settings) -> IHotelsProvider | None:
    # No live hotels adapter yet (needs a registered provider key).
    return None
