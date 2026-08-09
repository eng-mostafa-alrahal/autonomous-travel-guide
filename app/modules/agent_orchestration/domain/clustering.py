"""Deterministic day clustering of POIs (Stage 7).

Groups geo-located stops into ``num_days`` buckets anchored on a chosen hotel,
then orders each day's stops by a nearest-neighbour walk from the anchor and
computes the travel hops between them. Fully deterministic and offline — given
the same inputs it always produces the same plan. Pure functions, no LLM.

Algorithm (greedy, deterministic):
  1. Seed ``num_days`` clusters, each anchored at the hotel.
  2. Assign each POI (farthest-first so outliers spread across days) to the day
     whose current centroid is nearest.
  3. Order each day's stops by nearest-neighbour starting from the anchor and
     emit the hop distance/time for each consecutive pair.
"""

from __future__ import annotations

from app.modules.agent_orchestration.domain.geo import haversine_km, travel_time_minutes
from app.modules.agent_orchestration.domain.schemas.travel_plan import (
    POI,
    ClusterLeg,
    DayCluster,
    DayClusterPlan,
)


def _locatable(poi: POI) -> bool:
    return poi.lat is not None and poi.lng is not None


def _centroid(stops: list[POI], anchor_lat: float, anchor_lng: float) -> tuple[float, float]:
    points = [(s.lat, s.lng) for s in stops if _locatable(s)]
    if not points:
        return anchor_lat, anchor_lng
    lat = sum(p[0] for p in points if p[0] is not None) / len(points)
    lng = sum(p[1] for p in points if p[1] is not None) / len(points)
    return lat, lng


def cluster_pois(
    pois: list[POI],
    *,
    num_days: int,
    anchor: tuple[float, float] | None = None,
    anchor_name: str = "",
) -> DayClusterPlan:
    """Assign ``pois`` to ``num_days`` day clusters anchored at ``anchor``.

    POIs without coordinates are distributed round-robin (deterministic) so no
    stop is silently dropped when coordinates are missing.
    """
    days = max(1, num_days)
    located = [p for p in pois if _locatable(p)]
    unlocated = [p for p in pois if not _locatable(p)]

    if anchor is None and located:
        anchor = (
            sum(p.lat for p in located if p.lat is not None) / len(located),
            sum(p.lng for p in located if p.lng is not None) / len(located),
        )
    anchor = anchor or (0.0, 0.0)

    buckets: list[list[POI]] = [[] for _ in range(days)]
    # Assign farthest-first so outlying POIs land in different days.
    ordered = sorted(
        located,
        key=lambda p: haversine_km(anchor[0], anchor[1], p.lat or 0.0, p.lng or 0.0),  # type: ignore[arg-type]
        reverse=True,
    )
    for poi in ordered:
        target = min(
            range(days),
            key=lambda i: (
                haversine_km(
                    _centroid(buckets[i], anchor[0], anchor[1])[0],
                    _centroid(buckets[i], anchor[0], anchor[1])[1],
                    poi.lat or 0.0,
                    poi.lng or 0.0,
                ),
                len(buckets[i]),  # tie-break toward the emptier day (stable)
            ),
        )
        buckets[target].append(poi)

    # Round-robin the coordinate-less POIs so they still appear somewhere.
    for idx, poi in enumerate(unlocated):
        buckets[idx % days].append(poi)

    clusters: list[DayCluster] = []
    for i, bucket in enumerate(buckets):
        ordered_stops = _nearest_neighbor_order(bucket, anchor)
        legs = _legs_for(ordered_stops, anchor)
        clusters.append(
            DayCluster(day=i + 1, anchor_name=anchor_name, stops=ordered_stops, legs=legs)
        )
    return DayClusterPlan(days=clusters)


def _nearest_neighbor_order(stops: list[POI], anchor: tuple[float, float]) -> list[POI]:
    """Order stops by greedy nearest-neighbour starting from the anchor."""
    remaining = [s for s in stops if _locatable(s)]
    tail = [s for s in stops if not _locatable(s)]
    ordered: list[POI] = []
    current = anchor
    while remaining:
        nxt = min(
            remaining,
            key=lambda s: haversine_km(current[0], current[1], s.lat or 0.0, s.lng or 0.0),
        )
        ordered.append(nxt)
        current = (nxt.lat or 0.0, nxt.lng or 0.0)
        remaining.remove(nxt)
    return ordered + tail


def _legs_for(stops: list[POI], anchor: tuple[float, float]) -> list[ClusterLeg]:
    """Travel hops between consecutive stops (and from the anchor to the first)."""
    legs: list[ClusterLeg] = []
    prev_name = "Hotel"
    prev = anchor
    for stop in stops:
        if not _locatable(stop):
            continue
        dist = haversine_km(prev[0], prev[1], stop.lat or 0.0, stop.lng or 0.0)
        legs.append(
            ClusterLeg(
                from_name=prev_name,
                to_name=stop.name,
                distance_km=round(dist, 2),
                travel_minutes=travel_time_minutes(dist),
            )
        )
        prev = (stop.lat or 0.0, stop.lng or 0.0)
        prev_name = stop.name
    return legs
