"""Requirement-gathering nodes for the travel planner (extract + HITL ask)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
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

_SLOT_PHRASES = {
    "destination": "a destination (city or country)",
    "origin": "where you are traveling from (your current / departure city)",
    "num_days": "how many days the trip is",
    "budget": "your budget",
}


def _humanize_missing(missing: list[str]) -> str:
    phrases = [_SLOT_PHRASES.get(slot, slot) for slot in missing]
    if not phrases:
        return "a few more details"
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


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

        missing = requirements.missing_required()
        complete = not missing
        updates: dict[str, Any] = {
            "requirements": requirements.model_dump(),
            "missing_slots": missing,
            "requirements_complete": complete,
        }
        if complete:
            updates.update(
                phases.phase_update(
                    phases.PLANNING, "Trip details captured — bringing in the specialists."
                )
            )
        else:
            updates.update(
                phases.phase_update(
                    phases.REQUIREMENTS,
                    f"I still need {_humanize_missing(missing)}.",
                )
            )
        logger.info("travel_requirements complete=%s missing=%s", complete, missing)
        return updates

    return collect_requirements


def ask_requirements(state: TravelPlannerState) -> dict[str, Any]:
    missing = state.get("missing_slots") or []
    answer = interrupt(
        {
            "kind": "requirements",
            "message": (
                f"To plan your trip I still need {_humanize_missing(missing)}. "
                "Could you share those details?"
            ),
            "missing": missing,
        }
    )
    if isinstance(answer, dict):
        text = answer.get("feedback") or answer.get("answer") or answer.get("action") or ""
    else:
        text = str(answer)
    return {
        "messages": [HumanMessage(content=str(text or ""))],
        **phases.phase_update(phases.REQUIREMENTS, "Thanks — re-checking your trip details."),
    }
