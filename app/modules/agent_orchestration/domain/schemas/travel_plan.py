"""Structured outputs for the travel-planner specialists.

Each specialist emits a typed list instead of free text so downstream stages can
use the data: lat/lng feeds deterministic day clustering, and the cost fields
feed budget validation and itinerary persistence. Models are pure Pydantic (no
framework imports) and tolerate the extra fields LLMs tend to add.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _normalize_items(data: Any, aliases: tuple[str, ...]) -> Any:
    """Accept common LLM list-wrapper variants and coerce them into ``items``."""
    if not isinstance(data, dict):
        return data
    d = dict(data)
    if "items" in d:
        return d
    for alt in aliases:
        raw = d.get(alt)
        if isinstance(raw, list):
            d["items"] = raw
            break
    else:
        d["items"] = []
    return d


class POI(BaseModel):
    """A point of interest: attraction, neighborhood, restaurant, activity."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Name of the place or activity.")
    category: str = Field(
        default="attraction",
        description="attraction | neighborhood | restaurant | activity | landmark | museum | etc.",
    )
    lat: float | None = Field(
        default=None,
        description="Approximate latitude (best estimate from knowledge; None if unknown).",
    )
    lng: float | None = Field(
        default=None,
        description="Approximate longitude (best estimate from knowledge; None if unknown).",
    )
    estimated_duration_min: int | None = Field(
        default=None, description="Rough time to spend here, in minutes."
    )
    notes: str = Field(default="", description="One or two sentences of practical detail.")


class POIList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[POI] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        return _normalize_items(data, ("pois", "places", "attractions", "results", "spots"))


class HotelOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Hotel or neighborhood lodging option name.")
    area: str = Field(default="", description="Neighborhood / district.")
    nightly_rate_usd: float | None = Field(
        default=None, description="Approximate nightly rate in USD."
    )
    lat: float | None = Field(default=None, description="Approximate latitude.")
    lng: float | None = Field(default=None, description="Approximate longitude.")
    notes: str = Field(default="", description="Why it fits the trip (budget, vibe, location).")


class HotelOptionList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[HotelOption] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        return _normalize_items(data, ("hotels", "options", "accommodations", "results"))


class FlightOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(
        ..., description="Route / option summary, e.g. 'NRT → KIX, direct, 1h 15m'."
    )
    price_usd: float | None = Field(default=None, description="Approximate round-trip / leg price.")
    details: str = Field(default="", description="Carriers, transfers, timing, practical notes.")


class FlightOptionList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[FlightOption] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        return _normalize_items(data, ("options", "flights", "routes", "results"))


# ── Spatial day clustering (Stage 7, deterministic) ─────────────────────────


class ClusterLeg(BaseModel):
    """One hop between consecutive stops in a day, with an estimated travel time."""

    model_config = ConfigDict(extra="ignore")

    from_name: str
    to_name: str
    distance_km: float
    travel_minutes: int


class DayCluster(BaseModel):
    """A group of stops assigned to one day, ordered by a nearest-neighbour walk."""

    model_config = ConfigDict(extra="ignore")

    day: int = Field(..., description="1-based day number.")
    anchor_name: str = Field(default="", description="Name of the anchor (e.g. chosen hotel).")
    stops: list[POI] = Field(default_factory=list, description="Stops in visiting order.")
    legs: list[ClusterLeg] = Field(
        default_factory=list,
        description="Travel hops between consecutive stops (len == len(stops) - 1).",
    )


class DayClusterPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    days: list[DayCluster] = Field(default_factory=list)
