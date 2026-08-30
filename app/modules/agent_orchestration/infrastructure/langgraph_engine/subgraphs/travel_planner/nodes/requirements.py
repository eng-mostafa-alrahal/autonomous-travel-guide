"""Requirement-gathering nodes for the travel planner (extract + HITL ask)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.infrastructure.llm_gateways.structured_output import with_pydantic_output
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.prompts.schema_compact import compact_schema_for_llm
from app.modules.agent_orchestration.domain.schemas.trip_requirements import TripRequirements
from app.modules.agent_orchestration.domain.states.travel_planner_state import TravelPlannerState
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_config_for_structured_pair,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.shared_nodes.message_snippets import (  # noqa: E501
    recent_human_turns_as_text,
)

logger = logging.getLogger(__name__)

# Ask one thing at a time — keeps the chat feeling like a conversation, not a form.
_ASK_FOR: dict[str, str] = {
    "destination": (
        "I'd love to help plan this — where are you thinking of going? "
        "A city or a country both work!"
    ),
    "origin": "Nice! And where will you be leaving from?",
    "num_days": "Got it. How many days do you have for the trip?",
    "budget": (
        "Almost there — what's your rough budget for the whole trip? "
        "A number or something like \"mid-range\" is totally fine."
    ),
    "interests": (
        "One more thing before I dig in — anything you're especially into? "
        "Food, museums, nightlife, nature, slow mornings… or I can mix it up if you're open."
    ),
}

_STATUS_FOR: dict[str, str] = {
    "destination": "Waiting to hear where you'd like to go.",
    "origin": "Waiting to hear where you're leaving from.",
    "num_days": "Waiting to hear how many days you have.",
    "budget": "Waiting to hear your rough budget.",
    "interests": "Curious what you'd like to focus on.",
}


def _primary_slot(missing: list[str]) -> str | None:
    return missing[0] if missing else None


def _ask_message(missing: list[str]) -> str:
    slot = _primary_slot(missing)
    if slot and slot in _ASK_FOR:
        return _ASK_FOR[slot]
    return "Tell me a bit more about the trip and I'll shape the plan around you."


def _slots_to_ask(requirements: TripRequirements, *, preferences_asked: bool) -> list[str]:
    """Hard slots first; then one soft nudge for interests (skipped after we already asked)."""
    hard = requirements.missing_required()
    if hard:
        return hard
    if not requirements.interests and not preferences_asked:
        return ["interests"]
    return []


def make_collect_requirements_node(llm: BaseChatModel, *, prompt_provider: IPromptProvider):
    structured_llm = with_pydantic_output(llm, TripRequirements)

    async def collect_requirements(state: TravelPlannerState) -> dict[str, Any]:
        convo = recent_human_turns_as_text(state.get("messages", []))
        goal_section = f"Conversation so far:\n{convo}\n\n" if convo else ""

        system_rendered = prompt_provider.resolve_prompt(
            PromptIntent.STRUCTURED_OUTPUT_SYSTEM, PromptContext()
        )
        human_rendered = prompt_provider.resolve_prompt(
            PromptIntent.TRAVEL_REQUIREMENTS,
            PromptContext(
                goal_section=goal_section,
                compact_schema=compact_schema_for_llm(TripRequirements),
            ),
        )
        trace_cfg = trace_config_for_structured_pair(
            system_rendered.metadata, human_rendered.metadata
        )
        requirements: TripRequirements = await structured_llm.ainvoke(
            [
                SystemMessage(content=system_rendered.content),
                HumanMessage(content=human_rendered.content),
            ],
            config=trace_cfg,
        )  # type: ignore[assignment]

        missing = _slots_to_ask(
            requirements, preferences_asked=bool(state.get("preferences_asked"))
        )
        complete = not missing
        updates: dict[str, Any] = {
            "requirements": requirements.model_dump(),
            "missing_slots": missing,
            "requirements_complete": complete,
        }
        if complete:
            updates.update(
                phases.phase_update(
                    phases.PLANNING, "Got it — looking into the best options for you."
                )
            )
        else:
            slot = _primary_slot(missing)
            status = _STATUS_FOR.get(slot or "", "Still figuring out a few trip details.")
            updates.update(phases.phase_update(phases.REQUIREMENTS, status))
            # Surface the question in chat so clients aren't stuck on a blank "Action needed".
            updates["messages"] = [AIMessage(content=_ask_message(missing))]
        logger.info("travel_requirements complete=%s missing=%s", complete, missing)
        return updates

    return collect_requirements


def ask_requirements(state: TravelPlannerState) -> dict[str, Any]:
    missing = state.get("missing_slots") or []
    slot = _primary_slot(missing)
    answer = interrupt(
        {
            "kind": "requirements",
            "message": _ask_message(missing),
            # Clients still get the full list; we only voice the first ask.
            "missing": missing,
        }
    )
    if isinstance(answer, dict):
        text = answer.get("feedback") or answer.get("answer") or answer.get("action") or ""
    else:
        text = str(answer)
    updates: dict[str, Any] = {
        "messages": [HumanMessage(content=str(text or ""))],
        **phases.phase_update(phases.REQUIREMENTS, "Thanks — taking another look at your trip."),
    }
    # Soft preference: after we ask once, empty interests no longer blocks planning.
    if slot == "interests":
        updates["preferences_asked"] = True
    return updates
