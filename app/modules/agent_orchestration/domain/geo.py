"""Deterministic geography helpers for day clustering (no network, no LLM).

Coordinates come from LLM best-estimates, so everything here is approximate and
tuned for plausibility, not precision. Pure functions, no framework imports.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088

# Rough average speeds used to translate a straight-line distance into a travel
# time. Walking for short hops, transit for anything longer.
WALK_SPEED_KMH = 4.5
TRANSIT_SPEED_KMH = 22.0
WALK_MAX_KM = 1.5
# Fixed overhead for waiting / getting to a stop when taking transit.
TRANSIT_OVERHEAD_MIN = 12.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def travel_time_minutes(distance_km: float) -> int:
    """Heuristic travel time (minutes) for a straight-line distance."""
    if distance_km <= WALK_MAX_KM:
        minutes = (distance_km / WALK_SPEED_KMH) * 60.0
    else:
        minutes = TRANSIT_OVERHEAD_MIN + (distance_km / TRANSIT_SPEED_KMH) * 60.0
    # Round to a friendly 5-minute step so itineraries don't show false precision.
    return max(5, int(round(minutes / 5.0) * 5))
