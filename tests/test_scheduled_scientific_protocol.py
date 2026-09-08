from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_search.scientific_protocol import load_protocol, sanitize_live_result

ROOT = Path(__file__).resolve().parents[1]


def test_locked_scheduled_protocol_matches_question_version_and_budgets() -> None:
    protocol = load_protocol(
        ROOT / "benchmarks" / "scheduled_scientific_protocol_v1.json",
        ROOT / "benchmarks" / "researcher_questions_v1.json",
    )
    assert protocol.version == 1
    assert protocol.scientific_status == "informational_pending_researcher_review"
    assert 1 <= protocol.per_query <= 10
    assert 1 <= protocol.max_full_texts <= 5
    assert 1 <= protocol.max_acquisition_attempts <= 10
    assert protocol.max_model_calls_per_case == 1
    assert len(protocol.case_ids) == 3


def test_live_result_sanitization_keeps_diagnostics_but_not_source_or_secrets() -> None:
    payload = {
        "schema_version": "sci_search_researcher_benchmark_result_v1",
        "question_sha256": "locked",
        "results": [
            {
                "case_id": "case-1",
                "run_status": "complete",
                "answer_adequacy": "adequate",
                "full_texts_analyzed": 2,
                "pipeline_warnings": [],
                "source_passage": "copyrighted full text",
                "api_key": "secret",
            }
        ],
    }
    sanitized = sanitize_live_result(payload)
    rendered = json.dumps(sanitized)
    assert sanitized["scientific_validation_status"] == "informational_pending_researcher_review"
    assert "full_texts_analyzed" in rendered
    assert "copyrighted full text" not in rendered
    assert "secret" not in rendered


def test_protocol_rejects_question_hash_drift(tmp_path: Path) -> None:
    protocol = json.loads(
        (ROOT / "benchmarks" / "scheduled_scientific_protocol_v1.json").read_text()
    )
    protocol["question_sha256"] = "0" * 64
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="question version"):
        load_protocol(path, ROOT / "benchmarks" / "researcher_questions_v1.json")


def test_scheduled_workflow_uses_manifest_budgets_and_never_updates_gold() -> None:
    workflow = (ROOT / ".github" / "workflows" / "provider-contracts.yml").read_text()
    assert "scheduled_scientific_protocol_v1.json" in workflow
    assert "sanitize_scheduled_result.py" in workflow
    assert "--max-acquisition-attempts 6" in workflow
    assert "retention-days: 30" in workflow
    assert "researcher_gold" not in workflow
