"""Structured output schema for knowledge-builder enrichment.

The LLM does not rewrite DeepSearch reports. It only adds long-form chapters
from its own knowledge so late-chunking has dense, paragraph-scale text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeSegment(BaseModel):
    """One additional guidebook chapter (not a summary of the research)."""

    model_config = ConfigDict(extra="ignore")

    topic: str = Field(
        ...,
        description=(
            "Short snake_case topic for this extra chapter, e.g. "
            "'neighborhoods_trastevere', 'scams_pickpockets', 'day_trip_tivoli'."
        ),
    )
    content: str = Field(
        ...,
        description=(
            "NEW long-form guidebook prose (several paragraphs, typically 600–1500 words / "
            "800–2000 tokens). Add what the research missed or treated thinly, using your "
            "own reliable knowledge. Do not summarize, paraphrase, or shorten the research."
        ),
    )


class PreparedKnowledge(BaseModel):
    """Additional chapters only — the original research is stored separately."""

    model_config = ConfigDict(extra="ignore")

    segments: list[KnowledgeSegment] = Field(
        default_factory=list,
        description=(
            "3–8 extra in-depth chapters for THIS theme only. Each chapter must be long "
            "enough for late-chunking (dense paragraphs, not bullet summaries)."
        ),
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
