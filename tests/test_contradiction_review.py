from __future__ import annotations

from typing import Any

from sci_search.literature_review import build_literature_review, render_review_markdown


def _group(group_id: str, cause: str, left: list[str], right: list[str]) -> dict[str, Any]:
    def position(ids: list[str]) -> dict[str, Any]:
        return {
            "stance": f"Stance {ids}",
            "evidence_ids": ids,
            "quotes": [{"evidence_id": item, "quote": f"quote {item}"} for item in ids],
            "publication_ids": [f"p{item[1:]}" for item in ids],
        }

    return {
        "id": group_id,
        "topic": f"Topic {group_id}",
        "cause": cause,
        "positions": [position(left), position(right)],
        "cause_explanation": None,
        "status": "model_proposed_source_verified",
        "validation_notes": [],
    }


def _investigation(groups: list[dict[str, Any]] | None, **ai: Any) -> dict[str, Any]:
    evidence = [
        {
            "id": f"e{n}",
            "publication_id": f"p{n}",
            "statement": f"s{n}",
            "passage": f"s{n}",
            "scope_dimension_ids": [f"d{n}"],
        }
        for n in range(1, 5)
    ]
    analysis: dict[str, Any] = {
        "status": "complete",
        "answer": {"text": "Answer", "evidence_ids": ["e1"], "quotes": []},
        "claims": [],
        **ai,
    }
    if groups is not None:
        analysis["contradiction_groups"] = groups
    return {
        "question": "Q",
        "evidence": evidence,
        "research_run": {"active_publication_ids": ["p1", "p2", "p3", "p4"]},
        "ai_analysis": analysis,
        "study_matrix": {
            "studies": [
                {
                    "publication_id": f"p{n}",
                    "inferred_evidence_nature": {"label": "laboratory experiment"},
                }
                for n in range(1, 5)
            ]
        },
        "answer_adequacy": {"can_answer_overall_question": True},
    }


def test_groups_get_severity_citations_and_order() -> None:
    report = build_literature_review(
        _investigation(
            [
                _group("contradiction:low", "different_conditions", ["e3"], ["e4"]),
                _group("contradiction:high", "unexplained", ["e1"], ["e2"]),
            ]
        )
    )
    groups = report["contradiction_groups"]
    assert [g["id"] for g in groups] == ["contradiction:high", "contradiction:low"]
    high = groups[0]
    assert high["severity"] == "high"
    assert high["touches_answer"] is True
    assert high["severity_rules_version"] == "contradiction_severity_v1"
    assert high["dimension_ids"] == ["d1", "d2"]
    assert high["positions"][0]["citations"] == [1]
    assert groups[1]["severity"] == "low"
    assert groups[1]["touches_answer"] is False


def test_high_group_touching_answer_contests_it() -> None:
    report = build_literature_review(
        _investigation([_group("contradiction:high", "unexplained", ["e1"], ["e2"])])
    )
    contest = report["answer_contest"]
    assert contest["contested"] is True
    assert contest["group_ids"] == ["contradiction:high"]
    assert contest["qualifications"] == [
        "Studies disagree on Topic contradiction:high; see the contradiction group."
    ]


def test_moderate_group_does_not_contest_answer() -> None:
    report = build_literature_review(
        _investigation([_group("contradiction:m", "different_conditions", ["e1"], ["e2"])])
    )
    assert report["contradiction_groups"][0]["severity"] == "moderate"
    assert report["answer_contest"]["contested"] is False


def test_v1_analysis_without_field_yields_none() -> None:
    report = build_literature_review(_investigation(None))
    assert report["contradiction_groups"] is None
    assert report["answer_contest"]["contested"] is False
    assert "Where studies disagree" not in render_review_markdown(report)


def test_group_citing_removed_evidence_is_dropped() -> None:
    investigation = _investigation([_group("contradiction:gone", "unexplained", ["e1"], ["e2"])])
    investigation["evidence"] = [e for e in investigation["evidence"] if e["id"] != "e2"]
    report = build_literature_review(investigation)
    assert report["contradiction_groups"] == []


def test_coverage_limited_run_uses_claims_for_answer_impact() -> None:
    investigation = _investigation(
        [
            _group("contradiction:a", "unexplained", ["e1"], ["e2"]),
            _group("contradiction:b", "different_conditions", ["e3"], ["e4"]),
        ],
        claims=[
            {"text": "Main", "evidence_ids": ["e3"], "quotes": [], "category": "claims"},
        ],
    )
    investigation["ai_analysis"].update(status="coverage_limited", answer=None)
    report = build_literature_review(investigation)
    by_id = {g["id"]: g for g in report["contradiction_groups"]}
    assert by_id["contradiction:a"]["touches_answer"] is False
    assert by_id["contradiction:b"]["touches_answer"] is True


def test_markdown_lists_groups_before_isolated_items() -> None:
    report = build_literature_review(
        _investigation([_group("contradiction:high", "unexplained", ["e1"], ["e2"])])
    )
    markdown = render_review_markdown(report)
    section = markdown[markdown.index("## Contradictions, methods, and comparability") :]
    assert "### Where studies disagree" in section
    assert "**Topic contradiction:high** — severity: high; cause: Unexplained." in section
    assert "  - Stance ['e1'] [1]" in section
