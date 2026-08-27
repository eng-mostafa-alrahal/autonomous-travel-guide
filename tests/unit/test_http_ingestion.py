"""Unit tests for the external RAG Document Processor adapter.

Uses an httpx MockTransport so the full submit -> poll -> results -> store flow
runs without network or pgvector.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.exceptions import ExternalServiceError
from app.infrastructure.ingestion.http_ingestion import HttpIngestionAdapter, _describe
from app.modules.agent_orchestration.application.ports.ingestion_port import (
    DestinationRef,
    IngestionSegment,
)

DIMS = 8
DESTINATION = DestinationRef(destination_key="paris|france", city="Paris", country="France")


def _adapter(**overrides: Any) -> HttpIngestionAdapter:
    kwargs: dict[str, Any] = {
        "base_url": "https://rag.example.com",
        "api_key": "rag_test",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": DIMS,
        "poll_interval_s": 0.0,
        "poll_timeout_s": 5.0,
    }
    kwargs.update(overrides)
    return HttpIngestionAdapter(**kwargs)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
    captured: list[httpx.Request] | None = None,
) -> None:
    real_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        def _wrapped(request: httpx.Request) -> httpx.Response:
            if captured is not None:
                captured.append(request)
            return handler(request)

        kwargs["transport"] = httpx.MockTransport(_wrapped)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _stub_store(monkeypatch: pytest.MonkeyPatch, sink: dict[str, Any]) -> None:
    class _Store:
        def add_embeddings(
            self, texts: list[str], embeddings: list[list[float]], metadatas: list[dict]
        ) -> list[str]:
            sink["texts"] = texts
            sink["embeddings"] = embeddings
            sink["metadatas"] = metadatas
            return [f"id-{i}" for i in range(len(texts))]

    import app.infrastructure.database.postgres.vector_store as vs

    monkeypatch.setattr(vs, "build_pgvector_store", lambda: _Store())


def _happy_handler(embedding: list[float]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/ingest/text"):
            return httpx.Response(200, json={"job_id": "job-1"})
        if path.endswith("/results"):
            return httpx.Response(
                200,
                json={
                    "chunks": [
                        {
                            "index": 0,
                            "text": "Paris chunk.",
                            "embedding": embedding,
                            "metadata": {"embedder": "openai"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"status": "completed", "chunks_emitted": 1})

    return handler


async def test_ingest_stores_returned_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: dict[str, Any] = {}
    captured: list[httpx.Request] = []
    _install_transport(monkeypatch, _happy_handler([0.5] * DIMS), captured)
    _stub_store(monkeypatch, sink)

    result = await _adapter().ingest(
        [IngestionSegment(topic="history", content="Paris has a long history.")],
        destination=DESTINATION,
    )

    assert result.doc_count == 1
    assert sink["texts"] == ["Paris chunk."]
    # Destination metadata is attached alongside whatever the service returned.
    meta = sink["metadatas"][0]
    assert meta["destination_key"] == "paris|france"
    assert meta["topic"] == "history"
    assert meta["embedder"] == "openai"


async def test_submit_pins_embedder_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: dict[str, Any] = {}
    captured: list[httpx.Request] = []
    _install_transport(monkeypatch, _happy_handler([0.5] * DIMS), captured)
    _stub_store(monkeypatch, sink)

    await _adapter().ingest(
        [IngestionSegment(topic="food", content="Great bistros.")], destination=DESTINATION
    )

    import json

    submit = next(r for r in captured if r.url.path.endswith("/ingest/text"))
    body = json.loads(submit.content)
    assert body["embedder_provider"] == "openai"
    assert body["embedding_pipeline"] == "chunk_then_embed"
    assert body["embedding_model"] == "text-embedding-3-small"
    assert body["embedding_dimensions"] == DIMS
    assert submit.headers["X-API-Key"] == "rag_test"


async def test_submit_pins_late_chunking_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: dict[str, Any] = {}
    captured: list[httpx.Request] = []
    _install_transport(monkeypatch, _happy_handler([0.5] * DIMS), captured)
    _stub_store(monkeypatch, sink)

    await _adapter(
        embedder_provider="jina",
        embedding_pipeline="late_chunking",
        embedding_model="jina-embeddings-v3",
        macro_splitter="semantic",
        late_chunk_min_tokens=800,
        late_chunk_max_tokens=2000,
    ).ingest(
        [IngestionSegment(topic="food", content="Great bistros.")], destination=DESTINATION
    )

    import json

    submit = next(r for r in captured if r.url.path.endswith("/ingest/text"))
    body = json.loads(submit.content)
    assert body["embedding_pipeline"] == "late_chunking"
    assert body["embedder_provider"] == "jina"
    assert body["macro_splitter"] == "semantic"
    assert body["late_chunk_min_tokens"] == 800
    assert body["late_chunk_max_tokens"] == 2000


async def test_mismatched_vector_width_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: dict[str, Any] = {}
    _install_transport(monkeypatch, _happy_handler([0.5] * (DIMS - 1)))
    _stub_store(monkeypatch, sink)

    with pytest.raises(ExternalServiceError):
        await _adapter().ingest(
            [IngestionSegment(topic="history", content="Paris.")], destination=DESTINATION
        )
    assert "texts" not in sink  # nothing written to pgvector


async def test_results_retry_on_409(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: dict[str, Any] = {}
    state = {"attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/ingest/text"):
            return httpx.Response(200, json={"job_id": "job-1"})
        if path.endswith("/results"):
            state["attempts"] += 1
            if state["attempts"] == 1:
                return httpx.Response(409, json={"code": "job_results_not_ready"})
            return httpx.Response(
                200,
                json={"chunks": [{"text": "ok", "embedding": [0.1] * DIMS, "metadata": {}}]},
            )
        return httpx.Response(200, json={"status": "completed"})

    _install_transport(monkeypatch, handler)
    _stub_store(monkeypatch, sink)

    result = await _adapter().ingest(
        [IngestionSegment(topic="t", content="c")], destination=DESTINATION
    )
    assert result.doc_count == 1
    assert state["attempts"] == 2


async def test_failed_job_raises_with_service_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ingest/text"):
            return httpx.Response(200, json={"job_id": "job-1"})
        return httpx.Response(200, json={"status": "failed", "error_message": "embedder down"})

    _install_transport(monkeypatch, handler)

    with pytest.raises(ExternalServiceError, match="embedder down"):
        await _adapter().ingest(
            [IngestionSegment(topic="t", content="c")], destination=DESTINATION
        )


async def test_missing_api_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ExternalServiceError, match="INGESTION_SERVICE_API_KEY"):
        await _adapter(api_key="").ingest(
            [IngestionSegment(topic="t", content="c")], destination=DESTINATION
        )


async def test_blank_segments_skip_service(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _adapter().ingest(
        [IngestionSegment(topic="t", content="   ")], destination=DESTINATION
    )
    assert result.doc_count == 0


def test_describe_unauthorized() -> None:
    assert "invalid or missing X-API-Key" in _describe(httpx.Response(401))


def test_describe_invalid_dimensions_includes_bounds() -> None:
    message = _describe(
        httpx.Response(
            422,
            json={
                "detail": "bad dims",
                "code": "invalid_embedding_dimensions",
                "embedding_model": "jina-embeddings-v3",
                "requested_dimensions": 31,
                "allowed_dimensions_min": 32,
                "allowed_dimensions_max": 1024,
            },
        )
    )
    assert "invalid_embedding_dimensions" in message
    assert "32-1024" in message
