"""Keep DeepSearch reports verbatim and add long-form LLM chapters per theme.

The previous single-call "dedup" step compressed six research reports into a
handful of short paragraphs. That killed late-chunking: there was nothing long
enough to chunk. This node:

1. Splits raw research on ``##`` cluster headings.
2. Stores each report as-is (never summarized).
3. Asks the LLM, per cluster, only for ADDITIONAL guidebook chapters from its
   own knowledge so travelers can ask a wide range of questions.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.infrastructure.llm_gateways.structured_output import with_pydantic_output
from app.modules.agent_orchestration.application.ports.prompt_provider_port import IPromptProvider
from app.modules.agent_orchestration.domain import phases
from app.modules.agent_orchestration.domain.prompts.context import PromptContext
from app.modules.agent_orchestration.domain.prompts.intent import PromptIntent
from app.modules.agent_orchestration.domain.prompts.schema_compact import compact_schema_for_llm
from app.modules.agent_orchestration.domain.research_sections import (
    split_research_sections,
    topic_slug,
)
from app.modules.agent_orchestration.domain.schemas.knowledge_prep import PreparedKnowledge
from app.modules.agent_orchestration.domain.states.knowledge_builder_state import (
    KnowledgeBuilderState,
)
from app.modules.agent_orchestration.infrastructure.langgraph_engine.prompt_trace_config import (
    trace_config_for_structured_pair,
)

logger = logging.getLogger(__name__)

_ENRICH_CONCURRENCY = 3


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
        sections = split_research_sections(raw)
        system_rendered = prompt_provider.resolve_prompt(
            PromptIntent.STRUCTURED_OUTPUT_SYSTEM,
            PromptContext(),
        )
        semaphore = asyncio.Semaphore(_ENRICH_CONCURRENCY)

        async def enrich_one(label: str, body: str) -> list[dict[str, str]]:
            kept = [{"topic": f"{topic_slug(label)}_research", "content": body}]
            human_rendered = prompt_provider.resolve_prompt(
                PromptIntent.KNOWLEDGE_DEDUP,
                PromptContext(
                    goal_section=goal_section,
                    extra_section=label,
                    retrieved_evidence=body,
                    compact_schema=compact_schema_for_llm(PreparedKnowledge),
                ),
            )
            trace_cfg = trace_config_for_structured_pair(
                system_rendered.metadata,
                human_rendered.metadata,
            )
            async with semaphore:
                try:
                    prepared: PreparedKnowledge = await structured_llm.ainvoke(
                        [
                            SystemMessage(content=system_rendered.content),
                            HumanMessage(content=human_rendered.content),
                        ],
                        config=trace_cfg,
                    )  # type: ignore[assignment]
                except Exception:
                    logger.exception("knowledge_enrich failed for theme %r — keeping research only", label)
                    return kept
            extras = [
                {"topic": seg.topic.strip().lower(), "content": seg.content.strip()}
                for seg in prepared.segments
                if seg.content.strip()
            ]
            logger.info(
                "knowledge_enrich theme=%r research_chars=%d extra_chapters=%d",
                label,
                len(body),
                len(extras),
            )
            return kept + extras

        chunk_lists = await asyncio.gather(*(enrich_one(label, body) for label, body in sections))
        segments = [seg for group in chunk_lists for seg in group]
        logger.info(
            "knowledge_prep stored %d segments (%d research reports + extras)",
            len(segments),
            len(sections),
        )
        return {
            "prepared_segments": segments,
            **phases.phase_update(
                phases.KNOWLEDGE_BUILD,
                "Expanding the research with extra guidebook chapters, then storing it.",
            ),
        }

    return deduplicate
