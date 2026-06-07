"""Deep-research client contract — autonomous multi-step web research."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class DeepResearchResult(BaseModel):
    content: str = Field(description="The full researched text answer.")
    sources: list[str] = Field(
        default_factory=list,
        description="URLs / citations the research visited.",
    )


class IDeepResearchClient(ABC):
    @abstractmethod
    async def research(self, brief: str) -> DeepResearchResult:
        """Run deep research for the given brief and return the consolidated result."""
        ...
