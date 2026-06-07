"""HTTP ingestion adapter for the external RAG Document Processor.

The service chunks + embeds and returns vectors, so this adapter does NOT
re-embed: it submits text, polls the job, fetches results, and upserts the
returned ``text + embedding + metadata`` into pgvector. To keep retrieval
correct, it submits the same embedding model/dimensions used at query time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.exceptions import ExternalServiceError
from app.modules.agent_orchestration.application.ports.ingestion_port import (
    DestinationRef,
    IIngestionService,
    IngestionResult,
    IngestionSegment,
)

logger = logging.getLogger(__name__)

_SERVICE_NAME = "RAG Document Processor"
_TERMINAL = {"completed", "failed"}


class HttpIngestionAdapter(IIngestionService):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        embedding_model: str,
        embedding_dimensions: int,
        request_timeout_s: float = 60.0,
        poll_timeout_s: float = 300.0,
        poll_interval_s: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._request_timeout_s = request_timeout_s
        self._poll_timeout_s = poll_timeout_s
        self._poll_interval_s = poll_interval_s

    async def ingest(
        self,
        segments: list[IngestionSegment],
        *,
        destination: DestinationRef,
    ) -> IngestionResult:
        texts: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        headers = {"X-API-Key": self._api_key, "Content-Type": "application/json"}
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=headers, timeout=self._request_timeout_s
        ) as client:
            for segment in segments:
                if not segment.content.strip():
                    continue
                chunks = await self._ingest_segment(client, segment.content)
                for chunk in chunks:
                    embedding = chunk.get("embedding")
                    text = chunk.get("text")
                    if not isinstance(embedding, list) or not isinstance(text, str):
                        continue
                    texts.append(text)
                    embeddings.append([float(x) for x in embedding])
                    metadatas.append(
                        {
                            **(chunk.get("metadata") or {}),
                            "destination_key": destination.destination_key,
                            "city": destination.city,
                            "country": destination.country,
                            "topic": segment.topic,
                            "source": segment.source or "deep_research",
                        }
                    )

        if not texts:
            return IngestionResult(doc_count=0, ids=[])

        ids = await self._store(texts, embeddings, metadatas)
        logger.info(
            "http_ingestion stored=%d destination=%s", len(ids), destination.destination_key
        )
        return IngestionResult(doc_count=len(ids), ids=[str(i) for i in ids])

    # ── internals ────────────────────────────────────────────────

    async def _ingest_segment(
        self, client: httpx.AsyncClient, content: str
    ) -> list[dict[str, Any]]:
        job_id = await self._submit(client, content)
        await self._wait_for_job(client, job_id)
        return await self._fetch_results(client, job_id)

    async def _submit(self, client: httpx.AsyncClient, content: str) -> str:
        payload = {
            "texts": [content],
            "embedding_pipeline": "chunk_then_embed",
            "macro_splitter": "recursive",
            "embedding_model": self._embedding_model,
            "embedding_dimensions": self._embedding_dimensions,
        }
        try:
            resp = await client.post("/api/v1/ingest/text", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                _SERVICE_NAME, f"submit HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(_SERVICE_NAME, f"submit failed: {exc}") from exc

        job_id = resp.json().get("job_id")
        if not job_id:
            raise ExternalServiceError(_SERVICE_NAME, "submit returned no job_id.")
        return str(job_id)

    async def _wait_for_job(self, client: httpx.AsyncClient, job_id: str) -> None:
        deadline = time.monotonic() + self._poll_timeout_s
        while True:
            try:
                resp = await client.get(f"/api/v1/jobs/{job_id}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ExternalServiceError(_SERVICE_NAME, f"poll failed: {exc}") from exc

            body = resp.json()
            status = body.get("status")
            if status == "failed":
                raise ExternalServiceError(
                    _SERVICE_NAME, body.get("error_message") or "ingestion job failed."
                )
            if status in _TERMINAL:
                return
            if time.monotonic() >= deadline:
                raise ExternalServiceError(
                    _SERVICE_NAME, f"job {job_id} did not finish within poll timeout."
                )
            await asyncio.sleep(self._poll_interval_s)

    async def _fetch_results(self, client: httpx.AsyncClient, job_id: str) -> list[dict[str, Any]]:
        deadline = time.monotonic() + self._poll_timeout_s
        while True:
            resp = await client.get(f"/api/v1/jobs/{job_id}/results")
            if resp.status_code == 409:
                if time.monotonic() >= deadline:
                    raise ExternalServiceError(_SERVICE_NAME, "results not ready before timeout.")
                await asyncio.sleep(self._poll_interval_s)
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ExternalServiceError(_SERVICE_NAME, f"results failed: {exc}") from exc
            chunks = resp.json().get("chunks") or []
            return list(chunks)

    async def _store(
        self,
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> list[str]:
        from app.infrastructure.database.postgres.vector_store import build_pgvector_store

        store = build_pgvector_store()
        ids = await asyncio.to_thread(
            store.add_embeddings, texts, embeddings, metadatas
        )
        return [str(i) for i in ids]
