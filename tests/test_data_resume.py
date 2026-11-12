import json

import pytest

from sci_search.data_research.connectors import eurostat
from sci_search.data_research.workflow import execute
from tests.test_connector_eurostat import offline
from tests.test_connector_recovery import GOOD, model
from tests.test_connector_stage import STRATEGY


def completed(directory):
    complete, _ = model([GOOD])
    return execute(
        "Life expectancy",
        STRATEGY,
        directory,
        connectors={"eurostat": eurostat},
        complete=complete,
        fetch=offline,
    )


def test_resume_preserves_checked_sources_without_new_provider_calls(tmp_path):
    original = completed(tmp_path / "original")

    def forbidden(*args, **kwargs):
        raise AssertionError("Covered question must not repeat acquisition or model calls")

    result = execute(
        "Life expectancy",
        STRATEGY,
        tmp_path / "resumed",
        resume_from=tmp_path / "original",
        fetch=forbidden,
        search=forbidden,
        complete=forbidden,
    )
    assert result["analyses"] == original["analyses"]
    assert result["coverage"]["gaps"] == []
    assert result["run_control"]["counts"]["model_calls"] == 0
    assert list((tmp_path / "resumed/connectors").glob("*/source*"))


def test_resume_rejects_tampered_retained_sources(tmp_path):
    completed(tmp_path / "original")
    source = next((tmp_path / "original/connectors").glob("*/source.tsv.gz"))
    source.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash|artifact"):
        execute(
            "Life expectancy", STRATEGY, tmp_path / "resumed", resume_from=tmp_path / "original"
        )


def test_resume_requires_the_same_question_contract(tmp_path):
    completed(tmp_path / "original")
    with pytest.raises(ValueError, match="question|scope"):
        execute(
            "Another question", STRATEGY, tmp_path / "resumed", resume_from=tmp_path / "original"
        )


def test_partial_resume_does_not_repeat_a_retained_connector_selection(tmp_path):
    complete, _ = model([{**GOOD, "filters": {**GOOD["filters"], "geo": ["NL"]}}])
    original = execute(
        "Life expectancy",
        STRATEGY,
        tmp_path / "original",
        complete=complete,
        fetch=offline,
        connectors={"eurostat": eurostat},
        budget_limits={"model_calls": 4},
    )
    assert original["analyses"]
    complete, seen = model([{**GOOD, "filters": {**GOOD["filters"], "geo": ["DE", "EL"]}}])
    result = execute(
        "Life expectancy",
        STRATEGY,
        tmp_path / "resumed",
        resume_from=tmp_path / "original",
        complete=complete,
        fetch=offline,
        search=lambda *a, **k: {"candidates": []},
        connectors={"eurostat": eurostat},
    )
    assert seen.count("connector_selection") == 1
    assert result["analyses"][0] == original["analyses"][0]
    assert len(result["analyses"]) == 2
    assert result["coverage"]["gaps"] == []


def test_resume_reconciles_completed_sources_after_a_stale_checkpoint(tmp_path):
    original = completed(tmp_path / "original")
    checkpoint = tmp_path / "original/checkpoint.json"
    state = json.loads(checkpoint.read_text())
    state["analyses"] = []
    state.pop("connector_checkpoint", None)
    checkpoint.write_text(json.dumps(state))
    from sci_search.data_research.resume import prepare

    restored = prepare(tmp_path / "original", tmp_path / "resumed", "Life expectancy", STRATEGY)
    assert restored["analyses"] == original["analyses"]
