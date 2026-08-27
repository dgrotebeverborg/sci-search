"""Versioned, provenance-aware methodological risk-of-bias judgments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RiskJudgment(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class RiskOfBiasRecord:
    id: str
    revision_id: str
    project_id: str
    study_id: str
    tool: str
    domain: str
    judgment: RiskJudgment
    rationale: str | None
    source_evidence_ids: tuple[str, ...]
    reviewer_user_id: str
    created_at: datetime
    revision: int
    previous_revision_id: str | None

    def __post_init__(self) -> None:
        required = (
            self.id,
            self.revision_id,
            self.project_id,
            self.study_id,
            self.tool,
            self.domain,
            self.reviewer_user_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("risk-of-bias identity fields must not be empty")
        if self.revision < 1:
            raise ValueError("risk-of-bias revision must be positive")
        if self.revision == 1 and self.previous_revision_id is not None:
            raise ValueError("first risk-of-bias revision cannot have a predecessor")
        if self.revision > 1 and not self.previous_revision_id:
            raise ValueError("later risk-of-bias revisions require lineage")
        if self.judgment is not RiskJudgment.UNKNOWN:
            if not (self.rationale or "").strip():
                raise ValueError("a non-unknown judgment requires a rationale")
            if not self.source_evidence_ids:
                raise ValueError("a non-unknown judgment requires source evidence")
        if any(not evidence_id.strip() for evidence_id in self.source_evidence_ids):
            raise ValueError("source evidence IDs must not be empty")
