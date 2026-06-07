"""Ingestion contract — turn cleaned knowledge segments into stored vectors.

Implementations either embed locally into pgvector or delegate to the external
RAG Document Processor and upsert the returned vectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class DestinationRef(BaseModel):
    destination_key: str
    city: str | None = None
    country: str | None = None


class IngestionSegment(BaseModel):
    topic: str = Field(default="general")
    content: str
    source: str | None = None


class IngestionResult(BaseModel):
    doc_count: int = 0
    ids: list[str] = Field(default_factory=list)


class IIngestionService(ABC):
    @abstractmethod
    async def ingest(
        self,
        segments: list[IngestionSegment],
        *,
        destination: DestinationRef,
    ) -> IngestionResult:
        """Persist the segments as retrievable vectors; return how many were stored."""
        ...
