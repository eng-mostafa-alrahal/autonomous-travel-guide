"""Deterministic spatial day-clustering node (Stage 7).

Reads the structured POIs from ``city_expert`` and ``food`` plus the chosen hotel
anchor, groups them into ``num_days`` geographically-coherent days with travel
hops, and stores the result in ``state["clusters"]`` for the itinerary. No LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.clustering import cluster_pois
from app.modules.agent_orchestration.domain.schemas.travel_plan import POI
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState

logger = logging.getLogger(__name__)

_POI_ROLES = ("city_expert", "food")


def _parse_pois(items: list[dict[str, Any]]) -> list[POI]:
    out: list[POI] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            out.append(POI.model_validate(raw))
        except Exception:
            logger.debug("skipping invalid POI item: %r", raw)
    return out


def _anchor_from_hotels(outputs: dict[str, Any]) -> tuple[tuple[float, float] | None, str]:
    """Pick the anchor: the first hotel that has coordinates."""
    for raw in outputs.get("hotels") or []:
        if not isinstance(raw, dict):
            continue
        lat, lng = raw.get("lat"), raw.get("lng")
        if lat is not None and lng is not None:
            return (float(lat), float(lng)), str(raw.get("name") or "")
    return None, ""


def make_spatial_cluster_node():
    async def spatial_cluster(state: TravelPlannerState) -> dict[str, Any]:
        requirements = state.get("requirements", {})
        outputs = state.get("specialist_outputs", {})
        num_days = int(requirements.get("num_days") or 1)

        pois: list[POI] = []
        seen: set[str] = set()
        for role in _POI_ROLES:
            for poi in _parse_pois(outputs.get(role) or []):
                # city_expert and food can surface the same place; cluster it once.
                key = poi.name.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                pois.append(poi)

        anchor, anchor_name = _anchor_from_hotels(outputs)
        plan = cluster_pois(pois, num_days=num_days, anchor=anchor, anchor_name=anchor_name)
        clusters = [day.model_dump() for day in plan.days]

        located = sum(1 for p in pois if p.lat is not None and p.lng is not None)
        logger.info(
            "spatial_cluster: %d POIs (%d with coords) into %d days (anchor=%s)",
            len(pois),
            located,
            len(clusters),
            anchor_name or "centroid",
        )
        return {
            "clusters": clusters,
            **phases.phase_update(
                phases.PLANNING,
                f"Grouped {len(pois)} places into {len(clusters)} day(s) by location.",
            ),
        }

    return spatial_cluster
