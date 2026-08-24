"""OpenStreetMap/Nominatim places provider (Stage 10).

Free geocoding + POI search. Returns ``None`` on any error or empty result so the
specialist falls back to web search. Respects Nominatim's usage policy by always
sending an identifiable ``User-Agent``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.modules.agent_orchestration.application.ports.travel_providers_port import (
    IPlacesProvider,
)
from app.modules.agent_orchestration.domain.schemas.travel_plan import POI

logger = logging.getLogger(__name__)

# Map Nominatim (class, type) onto our coarse POI categories.
_CATEGORY_MAP: dict[str, str] = {
    "tourism": "attraction",
    "historic": "landmark",
    "amenity": "restaurant",
    "leisure": "activity",
    "natural": "attraction",
    "shop": "activity",
    "place": "neighborhood",
}


def _category(raw: dict[str, Any]) -> str:
    cls = str(raw.get("class") or "")
    return _CATEGORY_MAP.get(cls, cls or "attraction")


def _to_poi(raw: dict[str, Any]) -> POI | None:
    name = raw.get("name") or (raw.get("display_name") or "").split(",")[0]
    lat, lng = raw.get("lat"), raw.get("lon")
    if not name or lat is None or lng is None:
        return None
    try:
        return POI(
            name=name.strip(),
            category=_category(raw),
            lat=float(lat),
            lng=float(lng),
            notes=str(raw.get("display_name") or "")[:200],
        )
    except (TypeError, ValueError):
        return None


class NominatimPlacesProvider(IPlacesProvider):
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout_s: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._timeout_s = timeout_s

    async def search_pois(self, query: str, *, limit: int = 8) -> list[POI] | None:
        params = {"q": query, "format": "jsonv2", "limit": str(limit)}
        data = await self._get("/search", params)
        if not data:
            return None
        pois = [p for p in (_to_poi(item) for item in data) if p is not None]
        return pois or None

    async def geocode(self, place: str) -> POI | None:
        params = {"q": place, "format": "jsonv2", "limit": "1"}
        data = await self._get("/search", params)
        if not data:
            return None
        return _to_poi(data[0])

    async def _get(self, path: str, params: dict[str, str]) -> list[dict[str, Any]] | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.get(
                    f"{self._base_url}{path}", params=params, headers=self._headers
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError:
            logger.warning("nominatim request failed (%s)", path, exc_info=True)
            return None
        except ValueError:
            logger.warning("nominatim returned non-JSON (%s)", path, exc_info=True)
            return None
        return data if isinstance(data, list) else None
