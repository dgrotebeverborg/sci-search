"""Context and ranking contracts for authorized scientific memory adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sci_search.discovery import PublicationCandidate
from sci_search.question_planning import ResearchPlan


@dataclass(frozen=True, slots=True)
class MemoryContext:
    user_id: str
    project_id: str


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    publication: PublicationCandidate
    base_score: float
    feedback_score: float = 0.0
    explanations: tuple[str, ...] = ()


class MemoryService(Protocol):
    def candidates(
        self, context: MemoryContext, plan: ResearchPlan, *, limit: int = 100
    ) -> tuple[MemoryCandidate, ...]: ...
    def ingest_revision(
        self, context: MemoryContext, run_id: str, revision: int
    ) -> dict[str, int]: ...
