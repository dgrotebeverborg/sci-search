"""Internal contract bugs must not become statements about dataset availability."""

import pytest

from sci_search.data_research import workflow
from tests.data_meaning_fixtures import with_positive_meaning_review
from tests.data_workflow_fixtures import mapping, strategy


def test_expected_source_error_remains_recoverable_and_cancellation_propagates():
    from sci_search.data_research.failures import record_failure
    from sci_search.data_research.run_control import BudgetExhausted

    record = {}
    assert record_failure(record, ValueError("Unsupported source unit"), stage="mapping") is False
    assert record["failure_category"] == "source_error"
    assert record["reason"] == "Unsupported source unit"
    assert "diagnostic" not in record
    with pytest.raises(BudgetExhausted):
        record_failure({}, BudgetExhausted("stop"), stage="mapping")


def test_new_source_failure_does_not_retain_stale_internal_diagnostics():
    from sci_search.data_research.failures import record_failure

    record = {}
    record_failure(record, TypeError("internal contract"), stage="mapping")
    record_failure(record, ValueError("Unavailable column"), stage="retry")
    assert record["failure_category"] == "source_error"
    assert record["error_class"] == "ValueError"
    assert "diagnostic" not in record


def test_derived_processing_bug_retains_technical_diagnostics(tmp_path, monkeypatch):
    from sci_search.data_research import derived_artifacts, derived_outputs

    def broken_jobs(*args):
        raise TypeError("invalid job contract")

    monkeypatch.setattr(derived_artifacts, "_retained", lambda *args: {})
    monkeypatch.setattr(derived_outputs, "prepare_jobs", broken_jobs)
    scope = strategy(
        calculations=[
            dict(
                id="index",
                label="Population index",
                operation="index",
                input="population",
                reference=None,
                base_year=2001,
                target_unit=None,
            )
        ]
    )
    result = {"strategy": scope, "analyses": []}
    derived_artifacts.finalize(result, tmp_path)
    assert result["derived_outputs"]["status"] == "blocked"
    assert result["derived_outputs"]["failure_category"] == "internal_error"
    assert "broken_jobs" in result["derived_outputs"]["diagnostic"]["traceback"]


def test_successful_publication_archives_previous_failure_diagnostics(tmp_path):
    from sci_search.data_research.publication import publish_analysis

    result = {"analyses": []}
    assessment = {
        "decision": "blocked",
        "reason": "Invalid column",
        "failure_stage": "mapping",
        "failure_category": "source_error",
        "error_class": "ValueError",
        "recovery_failure": {"failure_category": "internal_error", "error_class": "TypeError"},
    }
    analysis = {"source": {"sha256": "source"}, "series": []}
    publish_analysis(
        analysis,
        tmp_path,
        result=result,
        assessment=assessment,
        reason="Recovered source",
        overlap_policy="allow",
        execute=lambda a, *args, **kwargs: a,
        check_cancelled=lambda: None,
    )
    assert assessment["decision"] == "analysed"
    assert "failure_category" not in assessment
    assert "error_class" not in assessment
    assert "recovery_failure" not in assessment
    assert assessment["initial_assessment"]["failure_category"] == "source_error"
    assert assessment["initial_assessment"]["failure_stage"] == "mapping"
    assert assessment["initial_assessment"]["recovery_failure"]["error_class"] == "TypeError"


@pytest.mark.parametrize(
    "error", [TypeError("broken internal contract"), KeyError("internal_field")]
)
@pytest.mark.parametrize("target", ["execute_analysis", "analyse_csv"])
def test_unexpected_execution_error_has_distinct_diagnostics(tmp_path, monkeypatch, error, target):
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")
    page_url = "https://stats.example/data"
    page = b'<html>Annual population in people. <a href="/population.csv">CSV</a></html>'
    data = (
        b"Year,Country,Population\n2001,Netherlands,10\n2002,Netherlands,11\n2003,Netherlands,12\n"
    )
    replies = iter(
        [
            dict(
                adapter="csv",
                download_link_index=0,
                reason="Annual national population",
                definition_quote="Annual population in people.",
                license_note="Not established",
                covered_measurements=["population"],
            ),
            dict(
                suitable=True,
                reason="Matches",
                unit_evidence="people",
                measurement="population",
                mapping=mapping(),
            ),
        ]
    )

    def broken_execution(*args, **kwargs):
        raise error

    monkeypatch.setattr(workflow, target, broken_execution)

    def model(prompt, schema):
        if "operation" in schema["properties"]:
            return {"operation": "none"}
        if "code" in schema["properties"]:
            raise ValueError("Fallback could not extract")
        return next(replies)

    result = workflow.execute(
        "Population of Netherlands 2001–2003",
        strategy(),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(
                    url=page_url,
                    title="Population",
                    publisher="Statistics office",
                    rationale="Official",
                )
            ]
        },
        fetch=lambda u: (page, "text/html", u) if u == page_url else (data, "text/csv", u),
        complete=with_positive_meaning_review(model),
    )
    assessment = result["assessments"][0]
    assert assessment["failure_category"] == "internal_error"
    assert assessment["error_class"] == type(error).__name__
    assert "broken_execution" in assessment["diagnostic"]["traceback"]
    assert "availability" not in assessment
    assert assessment["failure_stage"] == (
        "execution" if target == "execute_analysis" else "mapping"
    )
    assert not result["analyses"]
