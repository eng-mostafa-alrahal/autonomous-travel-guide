"""Jina DeepSearch adapter — autonomous deep research over the public web.

Jina DeepSearch exposes an OpenAI-compatible chat-completions endpoint. We send a
single user "brief" and read back the consolidated answer plus any visited URLs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.exceptions import ExternalServiceError
from app.modules.agent_orchestration.application.ports.deep_research_port import (
    DeepResearchResult,
    IDeepResearchClient,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://deepsearch.jina.ai/v1"
_SERVICE_NAME = "Jina DeepSearch"


class JinaDeepSearchClient(IDeepResearchClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "jina-deepsearch-v1",
        reasoning_effort: str = "medium",
        timeout_s: float = 300.0,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_s = timeout_s
        self._base_url = base_url.rstrip("/")

    async def research(self, brief: str) -> DeepResearchResult:
        if not self._api_key:
            raise ExternalServiceError(_SERVICE_NAME, "JINA_API_KEY is not configured.")

        payload: dict[str, Any] = {
            "model": self._model,
            "reasoning_effort": self._reasoning_effort,
            "stream": False,
            "messages": [{"role": "user", "content": brief}],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                _SERVICE_NAME, f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(_SERVICE_NAME, str(exc)) from exc

        content = _extract_content(data)
        if not content:
            raise ExternalServiceError(_SERVICE_NAME, "Empty research result.")
        sources = _extract_sources(data)
        logger.info("jina_deepsearch ok chars=%d sources=%d", len(content), len(sources))
        return DeepResearchResult(content=content, sources=sources)


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def _extract_sources(data: dict[str, Any]) -> list[str]:
    """Best-effort extraction of visited URLs across known Jina response shapes."""
    urls: list[str] = []

    top = data.get("visitedURLs") or data.get("visited_urls")
    if isinstance(top, list):
        urls.extend(str(u) for u in top if u)

    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        for ann in message.get("annotations") or []:
            if not isinstance(ann, dict):
                continue
            citation = ann.get("url_citation") or {}
            url = citation.get("url") if isinstance(citation, dict) else None
            if url:
                urls.append(str(url))

    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped
