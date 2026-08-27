"""HTTP ingestion adapter for the external RAG Document Processor.

The service chunks + embeds and returns vectors, so this adapter does NOT
re-embed: it submits text, polls the job, fetches results, and upserts the
returned ``text + embedding + metadata`` into pgvector.

Retrieval correctness depends on the stored vectors matching the ones the city
expert produces at query time (``build_pgvector_store`` uses OpenAIEmbeddings
with ``EMBEDDING_MODEL``/``EMBEDDING_DIMENSIONS``). We therefore pin the
provider/model/dimensions on every request instead of relying on server
defaults, and reject any chunk whose vector width disagrees.
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
        embedder_provider: str = "openai",
        macro_splitter: str = "recursive",
        embedding_pipeline: str = "chunk_then_embed",
        late_chunk_min_tokens: int = 800,
        late_chunk_max_tokens: int = 2000,
        request_timeout_s: float = 60.0,
        poll_timeout_s: float = 300.0,
        poll_interval_s: float = 2.0,
        max_concurrency: int = 4,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._embedder_provider = embedder_provider
        self._macro_splitter = macro_splitter
        self._embedding_pipeline = embedding_pipeline
        self._late_chunk_min_tokens = late_chunk_min_tokens
        self._late_chunk_max_tokens = late_chunk_max_tokens
        self._request_timeout_s = request_timeout_s
        self._poll_timeout_s = poll_timeout_s
        self._poll_interval_s = poll_interval_s
        self._max_concurrency = max(1, max_concurrency)

    async def ingest(
        self,
        segments: list[IngestionSegment],
        *,
        destination: DestinationRef,
    ) -> IngestionResult:
        pending = [s for s in segments if s.content.strip()]
        if not pending:
            return IngestionResult(doc_count=0, ids=[])

        if not self._api_key:
            raise ExternalServiceError(
                _SERVICE_NAME, "INGESTION_SERVICE_API_KEY is not configured."
            )

        headers = {"X-API-Key": self._api_key, "Content-Type": "application/json"}
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async with httpx.AsyncClient(
            base_url=self._base_url, headers=headers, timeout=self._request_timeout_s
        ) as client:

            async def run(segment: IngestionSegment) -> list[dict[str, Any]]:
                async with semaphore:
                    return await self._ingest_segment(client, segment.content)

            chunk_lists = await asyncio.gather(*(run(s) for s in pending))

        texts: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for segment, chunks in zip(pending, chunk_lists, strict=True):
            for chunk in chunks:
                embedding = chunk.get("embedding")
                text = chunk.get("text")
                if not isinstance(embedding, list) or not isinstance(text, str):
                    continue
                if len(embedding) != self._embedding_dimensions:
                    raise ExternalServiceError(
                        _SERVICE_NAME,
                        f"embedding width {len(embedding)} != expected "
                        f"{self._embedding_dimensions}; refusing to store vectors that "
                        "cannot be searched with the query-time embedder.",
                    )
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
            "http_ingestion stored=%d segments=%d destination=%s",
            len(ids),
            len(pending),
            destination.destination_key,
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
        payload: dict[str, Any] = {
            "texts": [content],
            "embedding_pipeline": self._embedding_pipeline,
            "macro_splitter": self._macro_splitter,
            "embedder_provider": self._embedder_provider,
            "embedding_model": self._embedding_model,
            "embedding_dimensions": self._embedding_dimensions,
        }
        if self._embedding_pipeline == "late_chunking":
            payload["late_chunk_min_tokens"] = self._late_chunk_min_tokens
            payload["late_chunk_max_tokens"] = self._late_chunk_max_tokens
        try:
            resp = await client.post("/api/v1/ingest/text", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                _SERVICE_NAME, f"submit failed — {_describe(exc.response)}"
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
            except httpx.HTTPStatusError as exc:
                raise ExternalServiceError(
                    _SERVICE_NAME, f"poll failed — {_describe(exc.response)}"
                ) from exc
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
            if resp.status_code >= 400:
                raise ExternalServiceError(
                    _SERVICE_NAME, f"results failed — {_describe(resp)}"
                )
            return list(resp.json().get("chunks") or [])

    async def _store(
        self,
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> list[str]:
        from app.infrastructure.database.postgres.vector_store import build_pgvector_store

        store = build_pgvector_store()
        ids = await asyncio.to_thread(store.add_embeddings, texts, embeddings, metadatas)
        return [str(i) for i in ids]


def _describe(response: httpx.Response) -> str:
    """Turn the service's ``{detail, code, ...}`` error body into one log-safe line."""
    status = response.status_code
    if status == 401:
        return "HTTP 401: invalid or missing X-API-Key."
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {status}: {response.text[:300]}"
    if not isinstance(body, dict):
        return f"HTTP {status}: {response.text[:300]}"

    code = body.get("code")
    detail = body.get("detail")
    parts = [f"HTTP {status}"]
    if code:
        parts.append(str(code))
    if detail:
        parts.append(str(detail)[:300])
    if code == "invalid_embedding_dimensions":
        parts.append(
            f"(model={body.get('embedding_model')} requested={body.get('requested_dimensions')} "
            f"allowed={body.get('allowed_dimensions_min')}-{body.get('allowed_dimensions_max')})"
        )
    return ": ".join(parts[:2]) + (" " + " ".join(parts[2:]) if len(parts) > 2 else "")
