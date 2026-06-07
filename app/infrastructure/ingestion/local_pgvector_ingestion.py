"""Local ingestion fallback — chunk + embed segments straight into pgvector."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.modules.agent_orchestration.application.ports.ingestion_port import (
    DestinationRef,
    IIngestionService,
    IngestionResult,
    IngestionSegment,
)

logger = logging.getLogger(__name__)


class LocalPgVectorIngestionAdapter(IIngestionService):
    """Used when no external ingestion service URL is configured."""

    def __init__(
        self,
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def ingest(
        self,
        segments: list[IngestionSegment],
        *,
        destination: DestinationRef,
    ) -> IngestionResult:
        # Imported lazily so this module doesn't hard-depend on pgvector at import time.
        from langchain_core.documents import Document

        from app.infrastructure.database.postgres.vector_store import build_pgvector_store
        from app.infrastructure.ingestion.chunking import chunk_text

        documents: list[Any] = []
        for segment in segments:
            for chunk in chunk_text(
                segment.content,
                chunk_size=self._chunk_size,
                overlap=self._chunk_overlap,
            ):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "destination_key": destination.destination_key,
                            "city": destination.city,
                            "country": destination.country,
                            "topic": segment.topic,
                            "source": segment.source or "deep_research",
                        },
                    )
                )

        if not documents:
            return IngestionResult(doc_count=0, ids=[])

        store = build_pgvector_store()
        ids = await asyncio.to_thread(store.add_documents, documents)
        logger.info(
            "local_pgvector_ingestion stored=%d destination=%s",
            len(ids),
            destination.destination_key,
        )
        return IngestionResult(doc_count=len(ids), ids=[str(i) for i in ids])
