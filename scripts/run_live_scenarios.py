"""Live API scenario runner for the travel guide (requires running server + keys).

Usage:
    uv run python scripts/run_live_scenarios.py [--base-url http://127.0.0.1:8001]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from typing import Any

import httpx

DEFAULT_BASE = "http://127.0.0.1:8001"


class ScenarioResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = False
        self.detail = ""
        self.elapsed_s = 0.0


async def _post(client: httpx.AsyncClient, path: str, **kwargs: Any) -> httpx.Response:
    return await client.post(f"/api/v1{path}", **kwargs)


async def _get(client: httpx.AsyncClient, path: str, **kwargs: Any) -> httpx.Response:
    return await client.get(f"/api/v1{path}", **kwargs)


async def auth_headers(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"scenario-{suffix}@example.com"
    password = "hunter22"
    reg = await _post(
        client,
        "/auth/register",
        json={"name": "Scenario Tester", "email": email, "password": password},
    )
    if reg.status_code not in (200, 201):
        raise RuntimeError(f"register failed: {reg.status_code} {reg.text}")
    login = await _post(client, "/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


async def create_session(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await _post(client, "/sessions/", headers=headers, json={"title": "Scenario run"})
    resp.raise_for_status()
    return resp.json()["id"]


async def chat(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    session_id: str,
    message: str,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    resp = await _post(
        client,
        "/chat/",
        headers=headers,
        json={"session_id": session_id, "message": message},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def resume(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    thread_id: str,
    action: str,
    *,
    feedback: str | None = None,
    timeout: float = 900.0,
) -> dict[str, Any]:
    body: dict[str, Any] = {"action": action}
    if feedback is not None:
        body["feedback"] = feedback
    resp = await _post(
        client,
        f"/runs/{thread_id}/resume",
        headers=headers,
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def run_scenario(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    name: str,
    fn: Any,
) -> ScenarioResult:
    result = ScenarioResult(name)
    t0 = time.perf_counter()
    try:
        result.detail = await fn(client, headers)
        result.ok = True
    except Exception as exc:
        result.detail = f"{type(exc).__name__}: {exc}"
    result.elapsed_s = time.perf_counter() - t0
    return result


async def scenario_health(client: httpx.AsyncClient, _headers: dict[str, str]) -> str:
    resp = await _get(client, "/health")
    resp.raise_for_status()
    data = resp.json()
    assert data.get("status") in {"ok", "healthy"}, data
    return f"status={data.get('status')}"


async def scenario_missing_requirements(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    sid = await create_session(client, headers)
    data = await chat(client, headers, sid, "I want to go somewhere nice")
    assert data.get("interrupted") is True, data
    approval = data.get("approval_request") or {}
    missing = approval.get("missing") or approval.get("missing_slots") or []
    reply = (data.get("reply") or "").lower()
    assert missing or "origin" in reply or "destination" in reply or "budget" in reply, data
    return f"interrupted=True missing={missing or 'in reply'}"


async def scenario_kb_miss_reject(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    sid = await create_session(client, headers)
    msg = (
        "Plan 3 days in Reykjavik, Iceland. I'm flying from Boston. "
        "Budget mid-range, interested in food and nature."
    )
    data = await chat(client, headers, sid, msg, timeout=180.0)
    if data.get("interrupted") and not _is_kb_prompt(data):
        # Fill missing slots if the model still wants more detail.
        data = await resume(
            client,
            headers,
            sid,
            "approved",
            feedback="3 days, mid-range budget, from Boston, Reykjavik Iceland, food and nature",
            timeout=180.0,
        )
    assert data.get("interrupted") is True, data
    assert _is_kb_prompt(data), f"expected KB prompt, got: {data.get('reply','')[:200]}"
    final = await resume(client, headers, sid, "rejected", timeout=600.0)
    assert final.get("interrupted") is False, final
    assert final.get("reply"), "empty reply"
    return f"itinerary_chars={len(final['reply'])}"


async def scenario_kb_miss_approve(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    sid = await create_session(client, headers)
    msg = (
        "Plan 2 days in Tallinn, Estonia. Departing from Helsinki. "
        "Budget $1200, love history and cafes."
    )
    data = await chat(client, headers, sid, msg, timeout=180.0)
    if data.get("interrupted") and not _is_kb_prompt(data):
        data = await resume(
            client,
            headers,
            sid,
            "approved",
            feedback="2 days Tallinn Estonia from Helsinki, $1200, history and cafes",
            timeout=180.0,
        )
    assert data.get("interrupted") is True, data
    assert _is_kb_prompt(data), f"expected KB prompt, got: {data.get('reply','')[:200]}"
    final = await resume(client, headers, sid, "approved", timeout=900.0)
    assert final.get("interrupted") is False, final
    assert final.get("reply"), "empty reply"
    return f"itinerary_chars={len(final['reply'])}"


def _is_kb_prompt(data: dict[str, Any]) -> bool:
    text = (data.get("reply") or "").lower()
    approval = data.get("approval_request") or {}
    blob = str(approval).lower()
    needles = ("knowledge base", "deep research", "deep search", "approve")
    return any(n in text or n in blob for n in needles)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument(
        "--skip-approve",
        action="store_true",
        help="Skip the slow KB approve build (~4+ min).",
    )
    args = parser.parse_args()

    scenarios = [
        ("health", scenario_health),
        ("missing_requirements_interrupt", scenario_missing_requirements),
        ("kb_miss_reject_web_fallback", scenario_kb_miss_reject),
    ]
    if not args.skip_approve:
        scenarios.append(("kb_miss_approve_full_build", scenario_kb_miss_approve))

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        headers, email = await auth_headers(client)
        print(f"Auth OK ({email})")

        results: list[ScenarioResult] = []
        for name, fn in scenarios:
            print(f"\n--- {name} ---")
            result = await run_scenario(client, headers, name, fn)
            results.append(result)
            status = "PASS" if result.ok else "FAIL"
            print(f"{status} ({result.elapsed_s:.1f}s): {result.detail}")

    failed = [r for r in results if not r.ok]
    print("\n=== Summary ===")
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"  [{mark}] {r.name} ({r.elapsed_s:.1f}s)")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
