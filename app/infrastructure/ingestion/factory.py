"""Select the ingestion adapter based on configuration."""

from __future__ import annotations

import logging

from app.core.config.settings import Settings
from app.modules.agent_orchestration.application.ports.ingestion_port import IIngestionService

logger = logging.getLogger(__name__)


def build_ingestion_service(settings: Settings) -> IIngestionService:
    """Return the HTTP adapter when an ingestion URL is set, else the local fallback."""
    if settings.INGESTION_SERVICE_URL:
        from app.infrastructure.ingestion.http_ingestion import HttpIngestionAdapter

        logger.info("Using external ingestion service at %s", settings.INGESTION_SERVICE_URL)
        return HttpIngestionAdapter(
            base_url=settings.INGESTION_SERVICE_URL,
            api_key=settings.INGESTION_SERVICE_API_KEY,
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_dimensions=settings.EMBEDDING_DIMENSIONS,
            embedder_provider=settings.INGESTION_EMBEDDER_PROVIDER,
            macro_splitter=settings.INGESTION_MACRO_SPLITTER,
            request_timeout_s=settings.INGESTION_SERVICE_TIMEOUT_S,
            poll_timeout_s=settings.INGESTION_POLL_TIMEOUT_S,
            poll_interval_s=settings.INGESTION_POLL_INTERVAL_S,
            max_concurrency=settings.INGESTION_MAX_CONCURRENCY,
        )

    from app.infrastructure.ingestion.local_pgvector_ingestion import (
        LocalPgVectorIngestionAdapter,
    )

    logger.info("Using local pgvector ingestion fallback")
    return LocalPgVectorIngestionAdapter()
