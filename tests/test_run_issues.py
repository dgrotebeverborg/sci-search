import json

from sci_search import run_issues


def data_state():
    return {
        "run_id": "r1",
        "status": "complete",
        "question": "PRIVATE QUESTION",
        "result": {
            "data_analysis": {
                "assessments": [
                    {
                        "decision": "blocked",
                        "failure_stage": "connector:normalize",
                        "url": "https://source.test/data?secret=PRIVATE",
                        "reason": "Unsupported unit conversion",
                    },
                    {"decision": "analysed", "url": "https://source.test/good"},
                ],
                "output_completion": {"data_status": "partial", "calculation_status": "blocked"},
                "run_control": {"stop_reason": "Data investigation time budget exhausted"},
            }
        },
    }


def test_data_issues_are_separate_from_literature_and_do_not_copy_sensitive_content(tmp_path):
    run_issues.record(tmp_path, data_state(), now="2026-10-18T10:00:00+00:00")
    ledger = json.loads((tmp_path / "issues.json").read_text())
    assert {x["stream"] for x in ledger["issues"]} == {"data"}
    assert {x["category"] for x in ledger["issues"]} == {
        "unit_or_selection",
        "incomplete_data",
        "blocked_calculation",
        "budget_exhausted",
    }
    assert "PRIVATE" not in json.dumps(ledger)
    assert all(x["evidence_ref"] and x["code_fingerprints"] for x in ledger["issues"])


def test_repeated_updates_are_deduplicated_and_previous_observations_survive(tmp_path):
    state = data_state()
    run_issues.record(tmp_path, state, now="2026-10-18T10:00:00+00:00")
    run_issues.record(tmp_path, state, now="2026-10-18T11:00:00+00:00")
    run_issues.record(
        tmp_path, {"run_id": "r1", "status": "complete"}, now="2026-10-18T12:00:00+00:00"
    )
    ledger = json.loads((tmp_path / "issues.json").read_text())
    assert len(ledger["issues"]) == 4
    assert all(x["first_seen"] == "2026-10-18T10:00:00+00:00" for x in ledger["issues"])
    assert all(x["last_seen"] == "2026-10-18T11:00:00+00:00" for x in ledger["issues"])


def test_literature_withholding_is_not_a_technical_failure(tmp_path):
    state = {
        "run_id": "r",
        "status": "complete",
        "search_log": [
            {"provider": "openalex", "status": "failed", "query": "SECRET", "error": "private"}
        ],
        "acquisitions": [{"publication_id": "p", "status": "unreadable", "error": "private"}],
        "result": {
            "answer_adequacy": {"status": "partial", "can_answer_overall_question": False},
            "ai_analysis": {"status": "disabled"},
        },
    }
    run_issues.record(tmp_path, state)
    issues = json.loads((tmp_path / "issues.json").read_text())["issues"]
    assert {i["category"] for i in issues} == {
        "provider_failure",
        "unreadable_source",
        "answer_withheld",
    }
    assert {i["stream"] for i in issues} == {"literature"}


def test_failed_data_run_keeps_persisted_partial_diagnostics(tmp_path):
    (tmp_path / "data_analysis").mkdir()
    (tmp_path / "data_analysis/analysis.json").write_text(
        json.dumps(data_state()["result"]["data_analysis"])
    )
    run_issues.record(tmp_path, {"run_id": "r", "status": "failed", "error": "private traceback"})
    issues = json.loads((tmp_path / "issues.json").read_text())["issues"]
    assert "unit_or_selection" in {i["category"] for i in issues}
    assert "run_failed" in {i["category"] for i in issues}


def test_report_counts_runs_not_progress_updates_and_reports_corruption(tmp_path):
    for name in ["one", "two"]:
        folder = tmp_path / name
        folder.mkdir()
        run_issues.record(folder, data_state())
        run_issues.record(folder, data_state())
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "issues.json").write_text("{")
    report = run_issues.summarize(tmp_path)
    assert len(report["unreadable_ledgers"]) == 1
    assert all(g["run_count"] == 2 for g in report["groups"])
    assert len(report["groups"]) == 4


def test_manager_persists_issues_and_telemetry_failure_does_not_fail_research(
    tmp_path, monkeypatch, caplog
):
    from sci_search.research_runs import ResearchRunManager

    manager = ResearchRunManager(tmp_path, openalex_api_key="offline")
    state = data_state()
    manager._persist("r1", state)
    assert (tmp_path / "r1/issues.json").exists()

    def unavailable(*args, **kwargs):
        raise OSError("private diagnostic")

    monkeypatch.setattr(run_issues, "record", unavailable)
    manager._persist("r1", {"run_id": "r1", "status": "complete"})
    assert json.loads((tmp_path / "r1/run.json").read_text())["status"] == "complete"
    assert "Issue recording unavailable" in caplog.text
    assert "private diagnostic" not in caplog.text


def test_cli_backfill_is_explicit_idempotent_and_not_attributed_to_current_code(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "run.json").write_text(json.dumps(data_state()))
    output = tmp_path / "report.json"
    assert run_issues.main(["--root", str(tmp_path), "--output", str(output)]) == 0
    assert not (folder / "issues.json").exists()
    assert run_issues.main(["--root", str(tmp_path), "--backfill", "--output", str(output)]) == 0
    content = (folder / "issues.json").read_text()
    assert all(
        i["code_fingerprints"] == ["unknown_historical"] for i in json.loads(content)["issues"]
    )
    assert run_issues.main(["--root", str(tmp_path), "--backfill", "--output", str(output)]) == 0
    assert (folder / "issues.json").read_text() == content


def test_malformed_ledger_is_reported_not_overwritten(tmp_path):
    (tmp_path / "issues.json").write_text("[]")
    assert run_issues.summarize(tmp_path)["unreadable_ledgers"] == ["issues.json"]


def test_since_filter_uses_original_time_for_backfilled_runs(tmp_path):
    from datetime import UTC, datetime

    state = data_state()
    state["finished_at"] = "2026-09-01T12:00:00+00:00"
    run_issues.record(tmp_path, state, historical=True)
    report = run_issues.summarize(tmp_path, since=datetime(2026, 10, 1, tzinfo=UTC))
    assert report["groups"] == []


def test_rejected_synthesis_and_uncertain_screening_are_visible(tmp_path):
    state = {
        "run_id": "r",
        "status": "complete",
        "full_text_screening": [{"publication_id": "p", "decision": "uncertain"}],
        "result": {
            "ai_analysis": {"status": "unavailable", "reason": "Model validation rejected output"}
        },
    }
    run_issues.record(tmp_path, state)
    categories = {
        x["category"] for x in json.loads((tmp_path / "issues.json").read_text())["issues"]
    }
    assert categories == {"screening_uncertain", "synthesis_unavailable"}


def test_bad_backfill_state_does_not_abort_other_runs(tmp_path):
    for name, state in [("bad", {"run_id": "r", "search_log": ["bad"]}), ("good", data_state())]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps(state))
    output = tmp_path / "report.json"
    assert run_issues.main(["--root", str(tmp_path), "--backfill", "--output", str(output)]) == 1
    assert (tmp_path / "good/issues.json").exists()
    assert json.loads(output.read_text())["backfill_errors"] == ["bad/run.json"]


def test_bad_ledger_does_not_contribute_partial_counts(tmp_path):
    run_issues.record(tmp_path, data_state())
    path = tmp_path / "issues.json"
    ledger = json.loads(path.read_text())
    del ledger["issues"][-1]["evidence_ref"]
    path.write_text(json.dumps(ledger))
    report = run_issues.summarize(tmp_path)
    assert report["groups"] == []
    assert report["unreadable_ledgers"] == ["issues.json"]


def test_backfill_leaves_active_runs_for_the_live_writer(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps({"run_id": "active", "status": "running"}))
    assert (
        run_issues.main(
            ["--root", str(tmp_path), "--backfill", "--output", str(tmp_path / "report.json")]
        )
        == 0
    )
    assert not (tmp_path / "issues.json").exists()
