from copy import deepcopy

from sci_search.dashboard import build_dashboard


def test_complete_dashboard_preserves_provenance_and_all_blocks():
    investigation = {
        "question": "Question A",
        "evidence": [
            {
                "id": "e1",
                "publication_id": "p1",
                "passage": "Exact source text.",
                "start_offset": 4,
                "end_offset": 22,
            }
        ],
        "synthesis": {"claims": [{"statement": "Exact source text.", "evidence_ids": ["e1"]}]},
        "literature_review_report": {
            "executive_summary": {"text": "Qualified answer", "evidence_ids": ["e1"]},
            "references": [{"publication_id": "p1", "title": "Study"}],
        },
        "study_matrix": {"studies": [{"publication_id": "p1", "title": "Study"}]},
        "research_run": {"candidates": [{"id": "p2", "title": "Excluded study"}]},
    }
    original = deepcopy(investigation)
    dashboard = build_dashboard(investigation, run_id="run-a", revision=1)
    assert dashboard["schema_version"] == "research_dashboard_v1"
    blocks = {b["id"]: b for b in dashboard["blocks"]}
    assert set(blocks) == {
        "scope",
        "answer",
        "literature_review",
        "findings",
        "comparisons",
        "landscape",
        "studies",
        "gaps",
        "methods",
        "evidence",
        "validation",
        "references",
        "downloads",
    }
    assert blocks["evidence"]["data"] == investigation["evidence"]
    assert {s["publication_id"] for s in blocks["studies"]["data"]["studies"]} == {"p1", "p2"}
    assert dashboard["question"] == investigation["question"]
    blocks["evidence"]["data"][0]["passage"] = "changed"
    assert investigation == original


def test_missing_content_is_explicit_and_withholding_survives():
    result = build_dashboard(
        {
            "question": "Unknown",
            "answer_adequacy": {"status": "insufficient_evidence", "answer_withheld": True},
        },
        run_id="r",
        revision=1,
    )
    blocks = {b["id"]: b for b in result["blocks"]}
    assert blocks["answer"]["data"]["answer_adequacy"]["answer_withheld"] is True
    assert blocks["literature_review"]["status"] == "unavailable"
    assert blocks["literature_review"]["explanation"]
    assert blocks["evidence"]["status"] == "empty"


def test_legacy_answer_summary_is_retained_without_review():
    result = build_dashboard(
        {
            "question": "Legacy",
            "answer_summary": "Insufficient evidence",
            "summary_evidence_ids": ["e1"],
        },
        run_id="legacy",
        revision=1,
    )
    answer = next(block for block in result["blocks"] if block["id"] == "answer")
    assert answer["data"]["executive_summary"] == {
        "text": "Insufficient evidence",
        "evidence_ids": ["e1"],
    }


def test_generic_evidence_validation_checks_are_retained():
    evidence = {
        "id": "e",
        "validation_status": "passed",
        "validation_checks": [{"name": "exact_quote", "passed": True}],
        "validator_version": "v2",
        "review_state": "unreviewed",
    }
    result = build_dashboard({"question": "Q", "evidence": [evidence]}, run_id="r", revision=1)
    record = next(b for b in result["blocks"] if b["id"] == "validation")["data"]["records"][0]
    assert record["validation_status"] == "passed"
    assert record["validation_checks"] == evidence["validation_checks"]
    assert record["validator_version"] == "v2"


def test_discovered_study_preserves_acquisition_without_matrix():
    snapshot = build_dashboard(
        {
            "question": "Q",
            "research_run": {
                "candidates": [
                    {"id": "p1", "title": "Acquired study"},
                    {"id": "p2", "title": "Metadata only"},
                ],
                "acquisitions": [{"publication_id": "p1", "status": "acquired"}],
            },
        },
        run_id="r",
        revision=1,
    )
    studies = next(block for block in snapshot["blocks"] if block["id"] == "studies")["data"][
        "studies"
    ]
    assert studies[0]["full_text_available"] is True
    assert studies[1]["full_text_available"] is False


def test_contradiction_groups_and_contest_reach_blocks():
    group = {"id": "contradiction:x", "topic": "T", "severity": "high", "positions": []}
    contest = {"contested": True, "group_ids": ["contradiction:x"], "qualifications": ["q"]}
    dashboard = build_dashboard(
        {
            "question": "Q",
            "literature_review_report": {
                "executive_summary": {"text": "A", "evidence_ids": []},
                "contradiction_groups": [group],
                "answer_contest": contest,
            },
        },
        run_id="r",
        revision=1,
    )
    blocks = {b["id"]: b for b in dashboard["blocks"]}
    assert blocks["comparisons"]["data"]["contradiction_groups"] == [group]
    assert blocks["comparisons"]["status"] == "ready"
    assert blocks["answer"]["data"]["answer_contest"] == contest


def test_v1_review_without_groups_keeps_comparisons_empty():
    dashboard = build_dashboard(
        {"question": "Q", "literature_review_report": {"executive_summary": {"text": "A"}}},
        run_id="r",
        revision=1,
    )
    blocks = {b["id"]: b for b in dashboard["blocks"]}
    assert blocks["comparisons"]["data"]["contradiction_groups"] is None
    assert blocks["comparisons"]["status"] == "empty"
    assert blocks["answer"]["data"]["answer_contest"] is None
