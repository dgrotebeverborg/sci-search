import pytest

from sci_search.dashboard import build_dashboard
from sci_search.literature_review import build_literature_review, render_review_markdown


@pytest.mark.parametrize(
    ("gate", "ids", "expected"),
    [
        (True, ["e1"], "adequate"),
        (False, ["e1"], "partial"),
        (False, [], "insufficient"),
        (True, ["missing"], "insufficient"),
    ],
)
def test_quality_requires_gate_and_retained_qualifying_evidence(gate, ids, expected):
    payload = {
        "question": "Q",
        "evidence": [{"id": "e1", "publication_id": "p1"}],
        "answer_adequacy": {
            "status": "adequate",
            "can_answer_overall_question": gate,
            "qualifying_evidence_ids": ids,
        },
    }
    dashboard = build_dashboard(payload, run_id="r", revision=1)
    report = build_literature_review(payload)
    assert dashboard["result_quality"]["status"] == expected
    assert report["result_quality"] == dashboard["result_quality"]
    markdown = render_review_markdown(report)
    assert "Processing complete" in markdown
    assert report["result_quality"]["label"] in markdown
    assert "expert scientific validation" in markdown


def test_historical_result_is_not_assumed_adequate():
    dashboard = build_dashboard({"question": "Old"}, run_id="old", revision=1)
    assert dashboard["result_quality"]["status"] == "not_assessed"
    report = build_literature_review({"question": "Old"})
    del report["result_quality"]
    assert "Evidence adequacy was not recorded" in render_review_markdown(report)


def test_coverage_limited_ai_is_reported_as_used_even_without_overall_answer():
    payload = {
        "question": "Q",
        "answer_summary": "An overall answer is withheld.",
        "answer_adequacy": {"can_answer_overall_question": False},
        "ai_analysis": {
            "status": "coverage_limited",
            "provider": "openai",
            "model": "model",
            "answer": None,
            "claims": [],
        },
    }
    report = build_literature_review(payload)
    assert "Deterministic extractive" not in report["executive_summary"]["qualification"]
    assert report["methodology"]["model"]["status"] == "coverage_limited"
    assert "AI was used" in render_review_markdown(report)


@pytest.mark.parametrize(
    "field,value", [("review_state", "rejected"), ("validation_status", "failed")]
)
def test_rejected_evidence_cannot_make_quality_adequate(field, value):
    payload = {
        "evidence": [{"id": "e1", field: value}],
        "answer_adequacy": {"can_answer_overall_question": True, "qualifying_evidence_ids": ["e1"]},
    }
    assert (
        build_dashboard(payload, run_id="r", revision=1)["result_quality"]["status"]
        == "insufficient"
    )


def test_semantic_answer_withheld_overrides_source_adequacy_without_losing_findings():
    reason = "The cited sources do not support the proposed direction of the relationship."
    payload = {
        "question": "Q",
        "answer_summary": "Rejected overall conclusion.",
        "summary_evidence_ids": ["e1"],
        "synthesis": {"claims": [{"text": "Unreviewed extraction.", "evidence_ids": ["e1"]}]},
        "evidence": [{"id": "e1", "publication_id": "p1"}],
        "answer_adequacy": {
            "status": "adequate",
            "can_answer_overall_question": True,
            "qualifying_evidence_ids": ["e1"],
        },
        "ai_analysis": {
            "status": "coverage_limited",
            "answer": None,
            "answer_withheld": True,
            "answer_withheld_reason": reason,
            "claims": [{"text": "Supported bounded finding.", "evidence_ids": ["e1"]}],
        },
    }
    dashboard = build_dashboard(payload, run_id="r", revision=1)
    report = build_literature_review(payload)
    assert dashboard["result_quality"]["status"] == "partial"
    assert reason in dashboard["result_quality"]["explanation"]
    answer = next(block["data"] for block in dashboard["blocks"] if block["id"] == "answer")
    assert reason in answer["executive_summary"]["text"]
    assert answer["executive_summary"]["evidence_ids"] == []
    findings = next(block["data"] for block in dashboard["blocks"] if block["id"] == "findings")
    assert findings["claims"][0]["text"] == "Supported bounded finding."
    assert report["result_quality"] == dashboard["result_quality"]
    assert reason in report["executive_summary"]["text"]
    assert "Rejected overall conclusion" not in report["executive_summary"]["text"]
    assert report["executive_summary"]["evidence_ids"] == []
    assert "overall answer is withheld" in report["executive_summary"]["qualification"]
    assert report["findings"][0]["text"] == "Supported bounded finding."
    assert "Evidence covers the question" not in render_review_markdown(report)
    saved = build_dashboard({"literature_review_report": report}, run_id="r", revision=1)
    assert saved["result_quality"]["status"] == "partial"
    assert reason in saved["result_quality"]["explanation"]


@pytest.mark.parametrize("answer_withheld", [False, True])
def test_semantic_review_does_not_repopulate_rejected_findings(answer_withheld):
    rejected = {"text": "Rejected finding.", "evidence_ids": ["e1"]}
    payload = {
        "question": "Q",
        "evidence": [{"id": "e1", "publication_id": "p1"}],
        "answer_adequacy": {"can_answer_overall_question": True},
        "findings": [rejected],
        "synthesis": {"claims": [rejected]},
        "ai_analysis": {
            "status": "coverage_limited" if answer_withheld else "complete",
            "answer": None
            if answer_withheld
            else {"text": "Accepted answer.", "evidence_ids": ["e1"]},
            "answer_withheld": answer_withheld,
            "claims": [],
            "semantic_review": {"status": "complete"},
            "rejected_records": [{"category": "claims", "stage": "semantic_support"}],
        },
    }
    report = build_literature_review(payload)
    assert report["findings"] == []
    for source in (payload, {**payload, "literature_review_report": report}):
        dashboard = build_dashboard(source, run_id="r", revision=1)
        findings = next(block for block in dashboard["blocks"] if block["id"] == "findings")
        assert not findings["data"]["claims"]


def test_unavailable_semantic_review_keeps_source_evidence_without_promoting_findings():
    payload = {
        "question": "Q",
        "evidence": [{"id": "e1", "publication_id": "p1"}],
        "findings": [{"text": "Unreviewed finding.", "evidence_ids": ["e1"]}],
        "answer_adequacy": {"can_answer_overall_question": True},
        "ai_analysis": {
            "status": "unavailable",
            "answer_withheld": True,
            "semantic_review": {"status": "unavailable"},
            "claims": [],
        },
    }
    dashboard = build_dashboard(payload, run_id="r", revision=1)
    findings = next(block for block in dashboard["blocks"] if block["id"] == "findings")
    assert not findings["data"]["claims"]
    evidence = next(block for block in dashboard["blocks"] if block["id"] == "evidence")
    assert evidence["data"] == payload["evidence"]
