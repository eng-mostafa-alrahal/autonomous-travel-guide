"""State schema for the knowledge-builder subgraph."""

from __future__ import annotations

from app.modules.agent_orchestration.domain.states.base_state import BaseAgentState


class KnowledgeBuilderState(BaseAgentState):
    destination_key: str
    city: str | None
    country: str | None
    topics: list[str]
    approved: bool | None
    raw_research: str | None
    research_sources: list[str]
    prepared_segments: list[dict[str, str]]
    doc_count: int
    # Progress reporting (streamed as `stream_detail=phases` SSE events).
    phase: str | None
    phase_status: str | None
