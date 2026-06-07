"""Deduplication node — clean raw research into topic-tagged segments."""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.infrastructure.llm_gateways.structured_output import with_pydantic_output
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.prompts.schema_compact import compact_schema_for_llm
from app.modules.agent_orchestration.domain.schemas.knowledge_prep import PreparedKnowledge
from app.modules.agent_orchestration.domain.states.knowledge_builder_state import (
    KnowledgeBuilderState,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_config_for_structured_pair,
)

logger = logging.getLogger(__name__)


def make_deduplicate_node(llm: BaseChatModel, *, prompt_provider: IPromptProvider):
    structured_llm = with_pydantic_output(llm, PreparedKnowledge)

    async def deduplicate(state: KnowledgeBuilderState) -> dict:
        raw = state.get("raw_research") or ""
        if not raw.strip():
            return {"prepared_segments": []}

        city = state.get("city")
        country = state.get("country")
        where = ", ".join(p for p in (city, country) if p) or "the destination"
        goal_section = f"Destination: {where}.\n\n"

        system_rendered = prompt_provider.resolve_prompt(
            PromptIntent.STRUCTURED_OUTPUT_SYSTEM,
            PromptContext(),
        )
        human_rendered = prompt_provider.resolve_prompt(
            PromptIntent.KNOWLEDGE_DEDUP,
            PromptContext(
                goal_section=goal_section,
                retrieved_evidence=raw,
                compact_schema=compact_schema_for_llm(PreparedKnowledge),
            ),
        )
        trace_cfg = trace_config_for_structured_pair(
            system_rendered.metadata,
            human_rendered.metadata,
        )

        prepared: PreparedKnowledge = await structured_llm.ainvoke(
            [
                SystemMessage(content=system_rendered.content),
                HumanMessage(content=human_rendered.content),
            ],
            config=trace_cfg,
        )  # type: ignore[assignment]

        segments = [
            {"topic": seg.topic.strip().lower(), "content": seg.content.strip()}
            for seg in prepared.segments
            if seg.content.strip()
        ]
        logger.info("knowledge_dedup produced %d segments", len(segments))
        return {"prepared_segments": segments}

    return deduplicate
