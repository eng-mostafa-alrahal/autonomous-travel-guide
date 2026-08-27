"""Uvicorn loop factory for Windows + psycopg async compatibility.

Uvicorn 0.44 defaults to ``ProactorEventLoop`` on Windows when ``--reload`` is
off. LangGraph's Postgres checkpointer (psycopg async) requires a selector loop.

Pass ``--loop app.core.event_loop:selector_loop_factory`` to uvicorn, or use
``scripts/run_api.py``.
"""

from __future__ import annotations

import asyncio
import sys


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Create an event loop compatible with psycopg async on all platforms."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.new_event_loop()
