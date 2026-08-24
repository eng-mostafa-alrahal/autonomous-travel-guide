"""OSRM routing transit provider (Stage 10).

Real travel distance/time between two coordinates, replacing the haversine
heuristic in the spatial clustering node. Returns ``None`` on any error or
no-route so the caller falls back to the heuristic.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    ITransitProvider,
)

logger = logging.getLogger(__name__)

_METERS_PER_KM = 1000.0
_SECONDS_PER_MIN = 60.0


class OSRMTransitProvider(ITransitProvider):
    def __init__(self, *, base_url: str, timeout_s: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def leg(
        self, from_lat: float, from_lng: float, to_lat: float, to_lng: float
    ) -> dict[str, Any] | None:
        # OSRM expects coordinates as {lng},{lat}.
        coords = f"{from_lng},{from_lat};{to_lng},{to_lat}"
        url = f"{self._base_url}/route/v1/driving/{coords}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.get(url, params={"overview": "false"})
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("osrm route request failed", exc_info=True)
            return None

        routes = data.get("routes") if isinstance(data, dict) else None
        if not routes:
            return None
        route = routes[0]
        distance_m = route.get("distance")
        duration_s = route.get("duration")
        if distance_m is None or duration_s is None:
            return None
        distance_km = round(float(distance_m) / _METERS_PER_KM, 2)
        # Round to a friendly 5-minute step to match the heuristic's output.
        minutes = max(5, int(round((float(duration_s) / _SECONDS_PER_MIN) / 5.0) * 5))
        return {"distance_km": distance_km, "travel_minutes": minutes}
