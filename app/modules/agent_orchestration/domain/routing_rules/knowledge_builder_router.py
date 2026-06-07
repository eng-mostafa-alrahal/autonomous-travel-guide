"""Pure routing rules for the knowledge-builder subgraph."""

from __future__ import annotations

from typing import Literal

from app.modules.agent_orchestration.domain.states.knowledge_builder_state import (
    KnowledgeBuilderState,
)


def route_after_confirm(state: KnowledgeBuilderState) -> Literal["deep_research", "end"]:
    if state.get("error"):
        return "end"
    return "deep_research" if state.get("approved") else "end"


def route_after_research(state: KnowledgeBuilderState) -> Literal["deduplicate", "end"]:
    return "end" if state.get("error") else "deduplicate"


def route_after_ingest(state: KnowledgeBuilderState) -> Literal["notify_complete", "end"]:
    return "end" if state.get("error") else "notify_complete"
