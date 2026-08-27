"""Unit tests for phase progress: domain lines, event mapping, and SSE shaping."""

from __future__ import annotations

from app.api.v1.routers.chat_router import _phase_payload
from app.modules.agent_orchestration.application.dtos.agent_result import AgentEvent
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.infrastructure.langgraph_engine.mappers.state_mapper import (
    namespace_to_nodes,
    to_agent_events,
)


def test_phase_update_carries_phase_and_status():
    assert phases.phase_update(phases.PLANNING, "Looking around.") == {
        "phase": "planning",
        "phase_status": "Looking around.",
    }


def test_keep_true_sticky_flag():
    assert phases.keep_true(False, False) is False
    assert phases.keep_true(True, False) is True
    assert phases.keep_true(False, True) is True
    assert phases.keep_true(None, False) is False
    assert phases.keep_true(None, True) is True


def test_specialist_status_uses_role_template():
    assert phases.specialist_status("hotels", "Kyoto") == "Looking into places to stay in Kyoto."


def test_specialist_status_falls_back_for_unknown_role():
    status = phases.specialist_status("night_life", "Kyoto")
    assert "night life" in status
    assert "Kyoto" in status


def test_namespace_strips_checkpoint_suffix():
    assert namespace_to_nodes(("planner:9f3c-1234",)) == ["planner"]
    assert namespace_to_nodes(()) == []


def test_mapper_lifts_phase_out_of_updates():
    events = to_agent_events(
        {
            "delegate": {
                "next_specialist": "hotels",
                "phase": "planning",
                "phase_status": "Looking into places to stay in Kyoto.",
            }
        },
        namespace=("planner:abc",),
    )

    event = events[0]
    assert event.phase == "planning"
    assert event.phase_status == "Looking into places to stay in Kyoto."
    assert event.namespace == ["planner"]
    assert "phase" not in event.updates
    assert event.updates == {"next_specialist": "hotels"}


def test_mapper_leaves_phase_unset_when_node_reports_none():
    events = to_agent_events({"error_handler": {"error": None}})
    assert events[0].phase is None
    assert events[0].phase_status is None
    assert events[0].namespace == []


def test_phase_payload_none_without_status():
    assert _phase_payload(AgentEvent(node="delegate")) is None


def test_phase_payload_shape():
    event = AgentEvent(node="ingest", phase="knowledge_build", phase_status="Ready (3 entries).")
    assert _phase_payload(event) == {"phase": "knowledge_build", "status": "Ready (3 entries)."}
