"""Unit tests for deterministic spatial day clustering (Stage 7)."""

from __future__ import annotations

from app.modules.agent_orchestration.domain.clustering import cluster_pois_sync as cluster_pois
from app.modules.agent_orchestration.domain.geo import haversine_km, travel_time_minutes
from app.modules.agent_orchestration.domain.schemas.travel_plan import POI
from app.modules.agent_orchestration.infrastructure.langgraph_engine.subgraphs.travel_planner.nodes.spatial import (  # noqa: E501
    make_spatial_cluster_node,
)


def _poi(name: str, lat: float | None, lng: float | None, category: str = "attraction") -> POI:
    return POI(name=name, category=category, lat=lat, lng=lng)


def test_haversine_known_distance():
    # Kyoto Station (34.9858, 135.7585) to Kinkaku-ji (35.0394, 135.7292) ≈ 6.5 km straight-line.
    d = haversine_km(34.9858, 135.7585, 35.0394, 135.7292)
    assert 5.5 < d < 7.5


def test_travel_time_walks_short_hops():
    assert travel_time_minutes(0.5) <= travel_time_minutes(1.4) <= 30
    assert travel_time_minutes(0.5) == 5  # rounded to a friendly 5-min step


def test_travel_time_transit_for_long_hops():
    assert travel_time_minutes(10.0) > travel_time_minutes(1.0)


def test_cluster_is_deterministic():
    pois = [
        _poi("A", 35.0, 135.7),
        _poi("B", 35.001, 135.701),
        _poi("C", 35.04, 135.73),
        _poi("D", 35.041, 135.731),
    ]
    kwargs = {"num_days": 2, "anchor": (34.9858, 135.7585), "anchor_name": "Station Hotel"}
    first = cluster_pois(pois, **kwargs)
    second = cluster_pois(list(reversed(pois)), **kwargs)  # input order must not matter
    assert [d.model_dump() for d in first.days] == [d.model_dump() for d in second.days]


def test_nearby_pois_share_a_day():
    near = [_poi("N1", 35.0, 135.7), _poi("N2", 35.0005, 135.7005)]
    far = [_poi("F1", 35.05, 135.76), _poi("F2", 35.0505, 135.7605)]
    plan = cluster_pois(near + far, num_days=2, anchor=(34.9858, 135.7585))
    day_of = {s.name: d.day for d in plan.days for s in d.stops}
    assert day_of["N1"] == day_of["N2"]
    assert day_of["F1"] == day_of["F2"]
    assert day_of["N1"] != day_of["F1"]


def test_unlocated_pois_are_not_dropped():
    pois = [_poi("Located", 35.0, 135.7), _poi("Mystery", None, None)]
    plan = cluster_pois(pois, num_days=3, anchor=(34.9858, 135.7585))
    names = {s.name for d in plan.days for s in d.stops}
    assert names == {"Located", "Mystery"}


def test_legs_cover_consecutive_stops():
    pois = [_poi("A", 35.0, 135.7), _poi("B", 35.001, 135.701)]
    plan = cluster_pois(pois, num_days=1, anchor=(34.9858, 135.7585), anchor_name="Hotel")
    day = plan.days[0]
    assert len(day.legs) == len(day.stops)  # includes the hotel -> first stop hop
    assert day.legs[0].from_name == "Hotel"
    assert all(leg.travel_minutes >= 5 for leg in day.legs)


async def test_spatial_node_dedupes_shared_pois():
    node = make_spatial_cluster_node()
    shared = _poi("Nishiki Market", 35.005, 135.764, "restaurant").model_dump()
    state = {
        "requirements": {"destination_city": "Kyoto", "num_days": 2, "budget": "mid"},
        "specialist_outputs": {
            "city_expert": [shared],
            "food": [shared],  # same place from both roles
        },
    }
    result = await node(state)  # type: ignore[arg-type]
    total = sum(len(d["stops"]) for d in result["clusters"])
    assert total == 1


async def test_spatial_node_groups_and_sets_phase():
    node = make_spatial_cluster_node()
    state = {
        "requirements": {"destination_city": "Kyoto", "num_days": 2, "budget": "mid"},
        "specialist_outputs": {
            "city_expert": [
                _poi("Kinkaku-ji", 35.039, 135.729, "landmark").model_dump(),
                _poi("Gion", 35.003, 135.775, "neighborhood").model_dump(),
            ],
            "food": [_poi("Nishiki Market", 35.005, 135.764, "restaurant").model_dump()],
            "hotels": [
                {"name": "Station Hotel", "area": "Shimogyo", "lat": 34.985, "lng": 135.758}
            ],
        },
    }
    result = await node(state)  # type: ignore[arg-type]

    clusters = result["clusters"]
    assert len(clusters) == 2
    assert any(d["anchor_name"] == "Station Hotel" for d in clusters)
    total_stops = sum(len(d["stops"]) for d in clusters)
    assert total_stops == 3
    assert result["phase"] == "planning"
    assert "Grouped 3 places into 2 day(s)" in result["phase_status"]


async def test_cluster_pois_uses_real_transit_leg_when_provided():
    """Stage 10: a transit provider overrides the haversine heuristic per leg."""
    from app.modules.agent_orchestration.domain.clustering import cluster_pois

    async def fake_leg(_f_lat, _f_lng, _t_lat, _t_lng):
        return {"distance_km": 9.99, "travel_minutes": 42}

    pois = [_poi("A", 35.0, 135.7), _poi("B", 35.001, 135.701)]
    plan = await cluster_pois(
        pois, num_days=1, anchor=(34.9858, 135.7585), leg_lookup=fake_leg
    )
    legs = plan.days[0].legs
    assert legs and all(leg.distance_km == 9.99 for leg in legs)
    assert all(leg.travel_minutes == 42 for leg in legs)


async def test_cluster_pois_falls_back_when_leg_lookup_returns_none():
    from app.modules.agent_orchestration.domain.clustering import cluster_pois

    async def no_route(_f_lat, _f_lng, _t_lat, _t_lng):
        return None

    pois = [_poi("A", 35.0, 135.7)]
    plan = await cluster_pois(
        pois, num_days=1, anchor=(34.9858, 135.7585), leg_lookup=no_route
    )
    # Heuristic distance (haversine) is used instead of a routed value.
    assert plan.days[0].legs[0].distance_km != 9.99
