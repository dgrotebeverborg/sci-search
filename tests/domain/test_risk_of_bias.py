from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sci_search.domain.risk_of_bias import RiskJudgment, RiskOfBiasRecord

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def _record(**overrides: object) -> RiskOfBiasRecord:
    values: dict[str, object] = {
        "id": "rob-1",
        "revision_id": "rob-revision-1",
        "project_id": "project",
        "study_id": "publication-1",
        "tool": "ROBINS-I",
        "domain": "confounding",
        "judgment": RiskJudgment.UNKNOWN,
        "rationale": None,
        "source_evidence_ids": (),
        "reviewer_user_id": "reviewer",
        "created_at": NOW,
        "revision": 1,
        "previous_revision_id": None,
    }
    values.update(overrides)
    return RiskOfBiasRecord(**values)  # type: ignore[arg-type]


def test_unknown_is_explicit_and_never_defaults_to_low_risk() -> None:
    record = _record()
    assert record.judgment is RiskJudgment.UNKNOWN
    assert record.judgment is not RiskJudgment.LOW


@pytest.mark.parametrize(
    ("rationale", "sources"),
    [(None, ("e1",)), ("", ("e1",)), ("Supported rationale", ())],
)
def test_non_unknown_judgment_requires_rationale_and_source(
    rationale: str | None, sources: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        _record(
            judgment=RiskJudgment.HIGH,
            rationale=rationale,
            source_evidence_ids=sources,
        )


def test_revision_requires_lineage_after_first_revision() -> None:
    with pytest.raises(ValueError):
        _record(revision=2, previous_revision_id=None)
