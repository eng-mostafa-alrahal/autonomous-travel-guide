"""Unit tests for chat-history filtering and checkpoint → snapshot mapping."""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.agent_orchestration.application.dtos.agent_result import (
    AgentMessage,
    visible_chat_history,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.mappers.state_mapper import (
    to_state_snapshot,
)


def test_visible_chat_history_drops_summaries_tools_and_system_by_default() -> None:
    messages = [
        AgentMessage(type="human", content="Plan Kyoto"),
        AgentMessage(type="ai", content="Sure — a few questions first."),
        AgentMessage(type="system", content="You are a travel guide."),
        AgentMessage(type="tool", content='{"hotels": []}'),
        AgentMessage(
            type="ai",
            content="Conversation summary:\n- User asked about Kyoto.",
        ),
        AgentMessage(type="ai", content="Here is day 1."),
    ]

    visible = visible_chat_history(messages)

    assert [m.content for m in visible] == [
        "Plan Kyoto",
        "Sure — a few questions first.",
        "Here is day 1.",
    ]


def test_visible_chat_history_can_include_tools_and_system() -> None:
    messages = [
        AgentMessage(type="system", content="sys"),
        AgentMessage(type="human", content="hi"),
        AgentMessage(type="tool", content="tool-out"),
        AgentMessage(type="ai", content="hello"),
    ]

    visible = visible_chat_history(
        messages, include_tools=True, include_system=True
    )

    assert [m.type for m in visible] == ["system", "human", "tool", "ai"]


def test_to_state_snapshot_includes_checkpoint_messages() -> None:
    human = SimpleNamespace(type="human", content="Hello", id="m1", tool_calls=None)
    ai = SimpleNamespace(type="ai", content="Hi there", id="m2", tool_calls=None)
    snapshot = SimpleNamespace(
        next=(),
        interrupts=(),
        tasks=(),
        values={"messages": [human, ai]},
    )

    dto = to_state_snapshot(snapshot, thread_id="thread-1")

    assert dto.thread_id == "thread-1"
    assert dto.interrupted is False
    assert len(dto.messages) == 2
    assert dto.messages[0].type == "human"
    assert dto.messages[0].content == "Hello"
    assert dto.messages[1].type == "ai"
    assert dto.messages[1].content == "Hi there"


def test_to_state_snapshot_empty_when_no_checkpoint_values() -> None:
    snapshot = SimpleNamespace(next=(), interrupts=(), tasks=(), values=None)

    dto = to_state_snapshot(snapshot, thread_id="thread-empty")

    assert dto.messages == []
