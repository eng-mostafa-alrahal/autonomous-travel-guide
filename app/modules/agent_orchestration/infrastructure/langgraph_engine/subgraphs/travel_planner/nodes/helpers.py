"""Shared helpers for travel-planner nodes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def format_requirements(requirements: dict[str, Any]) -> str:
    """Human-readable summary of the collected trip requirements."""
    if not requirements:
        return "(none provided yet)"
    labels = [
        ("destination_city", "City"),
        ("destination_country", "Country"),
        ("num_days", "Days"),
        ("budget", "Budget"),
        ("start_date", "Start date"),
        ("party_size", "Party size"),
    ]
    lines: list[str] = []
    for key, label in labels:
        value = requirements.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    interests = requirements.get("interests")
    if interests:
        joined = ", ".join(interests) if isinstance(interests, list) else str(interests)
        lines.append(f"- Interests: {joined}")
    return "\n".join(lines) if lines else "(none provided yet)"


def destination_label(requirements: dict[str, Any]) -> str:
    parts = [
        requirements.get("destination_city"),
        requirements.get("destination_country"),
    ]
    return ", ".join(p for p in parts if p) or "the destination"


async def run_web_search(tool: BaseTool | None, query: str) -> str:
    """Best-effort web search; returns empty string on any failure or when disabled."""
    if tool is None:
        return ""
    try:
        result = await asyncio.to_thread(tool.invoke, {"query": query})
        return str(result)
    except Exception:
        logger.exception("travel_planner web_search failed for query=%r", query)
        return ""
