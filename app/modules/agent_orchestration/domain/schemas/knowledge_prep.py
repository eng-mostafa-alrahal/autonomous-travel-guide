"""Structured output schema for the knowledge-builder deduplication step."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeSegment(BaseModel):
    """A single deduplicated, topic-tagged piece of destination knowledge."""

    model_config = ConfigDict(extra="ignore")

    topic: str = Field(
        ...,
        description="Short topic label, e.g. 'history', 'food', 'culture', 'transport'.",
    )
    content: str = Field(
        ...,
        description="Self-contained, non-redundant prose about the topic.",
    )


class PreparedKnowledge(BaseModel):
    """The LLM outputs this after removing redundancy and organizing by topic."""

    model_config = ConfigDict(extra="ignore")

    segments: list[KnowledgeSegment] = Field(
        default_factory=list,
        description="Cleaned, deduplicated knowledge segments grouped by topic.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_llm_field_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "segments" not in d:
            for alt in ("chunks", "sections", "items", "knowledge"):
                raw = d.get(alt)
                if raw:
                    d["segments"] = raw
                    break
            else:
                d["segments"] = []
        return d
