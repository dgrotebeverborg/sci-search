from __future__ import annotations

import pytest

from sci_search.domain.contradictions import (
    ContradictionCause,
    Severity,
    assess_severity,
    contradiction_group_id,
)

LAB = "laboratory experiment"
FIELD = "field or observational study"
MODEL = "simulation or model"


def test_group_id_is_independent_of_order_and_whitespace() -> None:
    first = contradiction_group_id("Salinity  effect", [["e2", "e1"], ["e3"]])
    second = contradiction_group_id("salinity effect", [["e3"], ["e1", "e2"]])
    assert first == second
    assert first.startswith("contradiction:")
    assert len(first) == len("contradiction:") + 20


def test_group_id_changes_with_membership() -> None:
    assert contradiction_group_id("t", [["e1"], ["e2"]]) != contradiction_group_id(
        "t", [["e1"], ["e3"]]
    )


@pytest.mark.parametrize(
    ("cause", "touches", "expected"),
    [
        ("different_conditions", False, Severity.LOW),
        ("different_population", False, Severity.LOW),
        ("different_outcome_measure", False, Severity.LOW),
        ("different_method", False, Severity.MODERATE),
        ("unexplained", False, Severity.HIGH),
        ("different_conditions", True, Severity.MODERATE),
        ("different_method", True, Severity.HIGH),
        ("unexplained", True, Severity.HIGH),
    ],
)
def test_base_and_answer_impact(cause: str, touches: bool, expected: Severity) -> None:
    severity, basis = assess_severity(
        cause,
        [["p1"], ["p2"]],
        touches_answer=touches,
        evidence_nature_by_publication={"p1": LAB, "p2": LAB},
    )
    assert severity is expected
    assert basis
    assert any("answer" in item for item in basis) is touches


def test_imbalance_lowers_and_clamps_at_low() -> None:
    natures = {"p1": MODEL, "p2": LAB, "p3": FIELD}
    severity, basis = assess_severity(
        ContradictionCause.DIFFERENT_CONDITIONS,
        [["p1"], ["p2", "p3"]],
        touches_answer=False,
        evidence_nature_by_publication=natures,
    )
    assert severity is Severity.LOW
    assert any(item.startswith("Lowered") for item in basis)


def test_imbalance_lowers_unexplained_to_moderate() -> None:
    natures = {"p1": "review", "p2": LAB, "p3": LAB}
    severity, _ = assess_severity(
        "unexplained",
        [["p1"], ["p2", "p3"]],
        touches_answer=False,
        evidence_nature_by_publication=natures,
    )
    assert severity is Severity.MODERATE


def test_missing_study_card_counts_as_not_primary() -> None:
    severity, _ = assess_severity(
        "unexplained",
        [["unknown"], ["p2", "p3"]],
        touches_answer=False,
        evidence_nature_by_publication={"p2": LAB, "p3": FIELD},
    )
    assert severity is Severity.MODERATE


def test_no_imbalance_when_weak_side_has_no_strong_counterpart() -> None:
    severity, _ = assess_severity(
        "unexplained",
        [["p1"], ["p2"]],
        touches_answer=False,
        evidence_nature_by_publication={"p1": MODEL, "p2": LAB},
    )
    assert severity is Severity.HIGH


def test_unknown_cause_is_rejected() -> None:
    with pytest.raises(ValueError):
        assess_severity(
            "bad_cause", [["p1"], ["p2"]], touches_answer=False, evidence_nature_by_publication={}
        )
