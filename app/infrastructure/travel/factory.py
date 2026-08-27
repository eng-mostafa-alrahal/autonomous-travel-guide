"""Build travel data providers from settings (Stage 10).

``TRAVEL_MOCK_APIS=true`` forces the offline mock pack for *all four* providers
(curated fixtures for London / Paris / Rome / Berlin / New York / Damascus /
Los Angeles). Otherwise each builder returns the configured live provider, or
``None`` when its flag is ``"none"`` — the signal to fall back to web search or
the distance heuristic.

Adding a live provider = add a ``Literal`` value to the matching setting,
implement the port, and branch here. Mocks never replace the knowledge builder.
"""

from __future__ import annotations

from app.core.config.settings import Settings
from app.infrastructure.travel.mock_providers import (
    MockFlightsProvider,
    MockHotelsProvider,
    MockPlacesProvider,
    MockTransitProvider,
)
from app.infrastructure.travel.osm_places import NominatimPlacesProvider
from app.infrastructure.travel.osrm_transit import OSRMTransitProvider
from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IFlightsProvider,
    IHotelsProvider,
    IPlacesProvider,
    ITransitProvider,
)


def build_places_provider(settings: Settings) -> IPlacesProvider | None:
    if settings.TRAVEL_MOCK_APIS:
        return MockPlacesProvider()
    if settings.PLACES_PROVIDER == "osm":
        return NominatimPlacesProvider(
            base_url=settings.NOMINATIM_BASE_URL,
            user_agent=settings.NOMINATIM_USER_AGENT,
            timeout_s=settings.TRAVEL_PROVIDER_TIMEOUT_S,
        )
    return None


def build_transit_provider(settings: Settings) -> ITransitProvider | None:
    if settings.TRAVEL_MOCK_APIS:
        return MockTransitProvider()
    if settings.TRANSIT_PROVIDER == "osrm":
        return OSRMTransitProvider(
            base_url=settings.OSRM_BASE_URL,
            timeout_s=settings.TRAVEL_PROVIDER_TIMEOUT_S,
        )
    return None


def build_flights_provider(settings: Settings) -> IFlightsProvider | None:
    if settings.TRAVEL_MOCK_APIS:
        return MockFlightsProvider()
    # No live flights adapter yet (needs a registered provider key).
    return None


def build_hotels_provider(settings: Settings) -> IHotelsProvider | None:
    if settings.TRAVEL_MOCK_APIS:
        return MockHotelsProvider()
    # No live hotels adapter yet (needs a registered provider key).
    return None
