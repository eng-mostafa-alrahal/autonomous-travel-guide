"""Structured output schema for travel-planner requirement gathering."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUIRED_SLOTS: tuple[str, ...] = ("destination", "num_days", "budget")


class TripRequirements(BaseModel):
    """Trip constraints extracted from the conversation."""

    model_config = ConfigDict(extra="ignore")

    destination_city: str | None = Field(default=None, description="Target city, if given.")
    destination_country: str | None = Field(default=None, description="Target country, if given.")
    num_days: int | None = Field(default=None, description="Trip length in days.")
    budget: str | None = Field(
        default=None, description="Budget as free text, e.g. '$1500' or 'mid-range'."
    )
    start_date: str | None = Field(default=None, description="Start date if specified.")
    party_size: int | None = Field(default=None, description="Number of travellers.")
    interests: list[str] = Field(
        default_factory=list, description="Themes of interest (food, history, nightlife...)."
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        interests = d.get("interests")
        if interests is None:
            d["interests"] = []
        elif isinstance(interests, str):
            d["interests"] = [interests]
        return d

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not (self.destination_city or self.destination_country):
            missing.append("destination")
        if not self.num_days:
            missing.append("num_days")
        if not self.budget:
            missing.append("budget")
        return missing

    def is_complete(self) -> bool:
        return not self.missing_required()
