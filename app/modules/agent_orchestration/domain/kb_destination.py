"""KB destination entity — tracks which destinations have an indexed knowledge base.

Shared by the travel planner (to detect a KB miss) and the knowledge builder
(to mark a destination as building / ready / failed).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.shared.domain_models.base_model import DomainModel

KBStatus = Literal["none", "building", "ready", "failed"]


def build_destination_key(*, city: str | None, country: str | None) -> str:
    """Canonical lookup key for a destination (case/space-insensitive).

    Examples: ("Paris", "France") -> "paris|france"; (None, "Japan") -> "|japan".
    """
    norm_city = (city or "").strip().lower()
    norm_country = (country or "").strip().lower()
    return f"{norm_city}|{norm_country}"


class KBDestination(DomainModel):
    destination_key: str = Field(max_length=512)
    city: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=255)
    status: KBStatus = "none"
    doc_count: int = 0
    error_message: str | None = None
    indexed_at: datetime | None = None
