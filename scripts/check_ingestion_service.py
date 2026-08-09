"""Smoke-check the external RAG Document Processor with the project's settings.

Verifies connectivity, the API key, and that our embedding model/dimensions are
accepted and returned at the expected width. Does NOT write to pgvector.

    uv run python scripts/check_ingestion_service.py
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.config.settings import get_settings

SAMPLE = (
    "Reykjavik is the capital of Iceland and the world's northernmost capital "
    "of a sovereign state. It is known for geothermal pools and the Hallgrimskirkja church."
)


async def main() -> int:
    settings = get_settings()
    base_url = settings.INGESTION_SERVICE_URL.rstrip("/")
    if not base_url:
        print("INGESTION_SERVICE_URL is empty - local pgvector fallback is in use.")
        return 1

    print(f"Service : {base_url}")
    print(f"Embedder: {settings.INGESTION_EMBEDDER_PROVIDER} / {settings.EMBEDDING_MODEL} "
          f"@ {settings.EMBEDDING_DIMENSIONS}d")

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as anon:
        health = await anon.get("/api/v1/health")
        print(f"[health] {health.status_code} {health.text.strip()}")
        if health.status_code != 200:
            return 1

    if not settings.INGESTION_SERVICE_API_KEY:
        print("\nINGESTION_SERVICE_API_KEY is empty - set it to test ingest/jobs/results.")
        return 1

    headers = {
        "X-API-Key": settings.INGESTION_SERVICE_API_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=120.0) as client:
        submit = await client.post(
            "/api/v1/ingest/text",
            json={
                "texts": [SAMPLE],
                "embedding_pipeline": "chunk_then_embed",
                "macro_splitter": settings.INGESTION_MACRO_SPLITTER,
                "embedder_provider": settings.INGESTION_EMBEDDER_PROVIDER,
                "embedding_model": settings.EMBEDDING_MODEL,
                "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
            },
        )
        print(f"[submit] {submit.status_code} {submit.text[:300]}")
        if submit.status_code != 200:
            return 1
        job_id = submit.json()["job_id"]

        for _ in range(int(settings.INGESTION_POLL_TIMEOUT_S / 2)):
            status_resp = await client.get(f"/api/v1/jobs/{job_id}")
            body = status_resp.json()
            state = body.get("status")
            if state in {"completed", "failed"}:
                print(f"[job]    {state} chunks_emitted={body.get('chunks_emitted')}")
                if state == "failed":
                    print(f"         error: {body.get('error_message')}")
                    return 1
                break
            await asyncio.sleep(2)
        else:
            print("[job]    timed out")
            return 1

        results = await client.get(f"/api/v1/jobs/{job_id}/results")
        if results.status_code != 200:
            print(f"[results] {results.status_code} {results.text[:300]}")
            return 1
        chunks = results.json().get("chunks") or []
        widths = {len(c.get("embedding") or []) for c in chunks}
        print(f"[results] {len(chunks)} chunk(s), embedding width(s)={sorted(widths)}")

        if widths != {settings.EMBEDDING_DIMENSIONS}:
            print(
                f"MISMATCH: expected {settings.EMBEDDING_DIMENSIONS}d vectors. "
                "Stored vectors would not be searchable by the city expert."
            )
            return 1

    print("\nOK - ingestion service reachable and vector width matches pgvector queries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
