# tests/test_connector_recovery.py
import pytest

from sci_search.data_research.connectors import base, eurostat, stage
from tests.data_meaning_fixtures import with_positive_meaning_review
from tests.test_connector_eurostat import offline
from tests.test_connector_stage import STRATEGY

GOOD = {
    "filters": {
        "freq": ["A"],
        "unit": ["YR"],
        "sex": ["F", "M"],
        "age": ["Y_LT1"],
        "geo": ["NL", "DE", "EL"],
    },
    "series_dimensions": ["sex", "geo"],
    "reason": "Birth, both sexes",
}
BAD = {**GOOD, "filters": {**GOOD["filters"], "sex": ["X"]}}


def model(selections, *, terms=(["life expectancy"], ["life expectancy"]), choices=None):
    # Two term replies: the first search and the reformulation round for uncovered measurements.
    replies = {"selection": iter(selections), "terms": iter(terms)}
    seen = []
    prompts = []

    def complete(prompt, schema):
        seen.append(schema.get("title"))
        prompts.append(prompt)
        if schema.get("title") == "connector_terms":
            return {
                "terms": [
                    {"measurement": STRATEGY["measurements"][0], "terms": next(replies["terms"])}
                ]
            }
        if schema.get("title") == "connector_choice":
            return choices or {
                "choices": [
                    {
                        "candidate": "eurostat:demo_mlexpec",
                        "measurement": STRATEGY["measurements"][0],
                        "reason": "Annual",
                    }
                ]
            }
        if schema.get("title") == "connector_selection":
            return next(replies["selection"])
        raise AssertionError(schema.get("title"))

    wrapped = with_positive_meaning_review(complete)
    wrapped.prompts = prompts  # type: ignore[attr-defined]
    return wrapped, seen


def run(tmp_path, complete, fetch=offline):
    return stage.run(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        complete=complete,
        fetch=fetch,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )


def test_wrong_code_is_repaired_with_the_valid_codes(tmp_path):
    complete, _ = model([BAD, GOOD])
    result = run(tmp_path, complete)
    assert result["covered"] == STRATEGY["measurements"]
    recovery = result["assessments"][0]["recovery"]
    assert recovery[0]["class"] == "selection" and recovery[0]["outcome"] == "repaired"
    repair_prompt = [p for p in complete.prompts if '"previous_error"' in p]  # type: ignore[attr-defined]
    assert len(repair_prompt) == 1
    assert '"valid_codes"' in repair_prompt[0] and "://" not in repair_prompt[0]


def test_repairs_stop_after_two_attempts(tmp_path):
    complete, _ = model([BAD, BAD, BAD])
    result = run(tmp_path, complete)
    assert result["covered"] == []
    assert [r["class"] for r in result["assessments"][0]["recovery"]] == [
        "selection",
        "selection",
    ]
    assert result["assessments"][0]["error_class"] == "SelectionError"


def test_facts_never_carry_urls():
    facts = {"valid_codes": {"geo": ["NL", "https://evil/x"]}, "note": "see http://x"}
    assert stage._facts(facts) == {"valid_codes": {"geo": ["NL"]}}


def test_transient_errors_are_retried_once(tmp_path):
    calls = {"n": 0}

    def flaky(url):
        if "/data/demo_mlexpec/A.YR.F+M" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("Dataset server returned HTTP 503")
        return offline(url)

    complete, _ = model([GOOD])
    result = run(tmp_path, complete, flaky)
    assert result["covered"] == STRATEGY["measurements"]
    assert [r["class"] for r in result["assessments"][0]["recovery"]] == ["transient"]


def test_a_second_transient_error_is_not_retried(tmp_path):
    def down(url):
        if "/data/demo_mlexpec/A.YR.F+M" in url:
            raise ValueError("Dataset server returned HTTP 503")
        return offline(url)

    complete, _ = model([GOOD])
    result = run(tmp_path, complete, down)
    assert result["covered"] == []
    assert result["assessments"][0]["failure_stage"] == "connector:fetch"
    assert [r["class"] for r in result["assessments"][0]["recovery"]] == ["transient"]


@pytest.mark.parametrize(
    "exc",
    [
        base.DatasetRejected("HTTP 503 mentioned in a rejection"),
        base.SelectionError("HTTP 5 in a selection error"),
        base.ReaderError("HTTP 500 in a reader error"),
    ],
)
def test_rejections_are_never_retried_as_transient(exc):
    calls = []

    def step():
        calls.append(1)
        raise exc

    with pytest.raises(type(exc)):
        stage._with_retry(step, [])
    assert len(calls) == 1


def test_no_candidates_triggers_one_reformulated_search(tmp_path):
    complete, seen = model([GOOD], terms=(["zzzz nothing"], ["still nothing"]))
    result = run(tmp_path, complete)
    assert seen.count("connector_terms") == 2
    assert result["assessments"][-1]["reason"] == (
        "No connector dataset found after reformulated search"
    )
    assert result["search"]["reformulated_terms"] == {
        STRATEGY["measurements"][0]: ["still nothing"]
    }


def test_reformulation_finds_the_dataset(tmp_path):
    complete, seen = model([GOOD], terms=(["zzzz nothing"], ["life expectancy"]))
    result = run(tmp_path, complete)
    assert seen.count("connector_terms") == 2
    assert result["covered"] == STRATEGY["measurements"]
    assert result["assessments"][-1]["recovery"][0] == {
        "class": "search",
        "action": "reformulate",
        "outcome": "life expectancy",
    }


def test_reformulation_runs_once_and_skips_datasets_already_tried(tmp_path):
    complete, seen = model([BAD, BAD, BAD, GOOD])
    result = run(tmp_path, complete)
    assert seen.count("connector_terms") == 2
    assert result["covered"] == []
    assert [a.get("dataset") for a in result["assessments"]].count("demo_mlexpec") == 1


@pytest.mark.parametrize(
    "message",
    [
        "dataset is monthly; no aggregation was performed",
        "OWID response exceeds the 5 MB analysis limit",
        "JSON-stat measure has no documented unit",
        "OWID selection exceeds 60 entities",
        "OWID CSV has a duplicate Netherlands 2020 row",
    ],
)
def test_reader_rejections_never_go_to_python_recovery(tmp_path, monkeypatch, message):
    def forbidden(*args, **kwargs):
        raise AssertionError("recover_python must not be called for a rejection")

    def reject(raw, selection):
        raise ValueError(message)

    monkeypatch.setattr(stage, "recover_python", forbidden)
    monkeypatch.setattr(stage, "prepare_table", reject)
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assessment = result["assessments"][0]
    assert assessment["error_class"] == "DatasetRejected"
    assert assessment["reason"] == message
    assert not [r for r in assessment["recovery"] if r["class"] == "reader"]


def test_a_mapping_selection_error_is_a_rejection(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("recover_python must not be called for a rejection")

    def mixed(table, preparation, selection, measurement):
        raise base.SelectionError("Select one unit; the slice contains YR, PC")

    monkeypatch.setattr(stage, "recover_python", forbidden)
    monkeypatch.setattr(eurostat, "mapping", mixed)
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assert result["assessments"][0]["error_class"] == "DatasetRejected"
    assert result["assessments"][0]["failure_stage"] == "connector:normalize"


def test_reader_failures_go_to_python_recovery(tmp_path, monkeypatch):
    called = {}

    def fake_recover(question, strategy, data, source, folder, **kwargs):
        called["bytes"] = len(data)
        raise ValueError("Python extraction stopped after 3 attempt(s)")

    monkeypatch.setattr(stage, "recover_python", fake_recover)
    monkeypatch.setattr(
        stage,
        "prepare_table",
        lambda raw, selection: (_ for _ in ()).throw(ValueError("unknown layout")),
    )
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assert called["bytes"] > 0
    assessment = result["assessments"][0]
    assert assessment["recovery"][-1]["class"] == "reader"
    assert assessment["failure_stage"] == "connector:python"
    assert "Python extraction stopped" in assessment["reason"]


def test_a_garbled_response_is_recovered_and_executed(tmp_path, monkeypatch):
    executed = {}

    def fake_recover(question, strategy, data, source, folder, **kwargs):
        assert data.startswith(b"\x1f\x8b") and source["connector"]["dataset"] == "demo_mlexpec"
        return {"series": [{"label": "m"}], "source": source, "semantic_review": {"accepted": True}}

    def fake_execute(analysis, folder, *, check_cancelled):
        executed["analysis"] = analysis
        return {**analysis, "execution": {"status": "verified"}}

    monkeypatch.setattr(stage, "recover_python", fake_recover)
    monkeypatch.setattr(stage, "execute_analysis", fake_execute)
    monkeypatch.setattr(
        stage,
        "prepare_table",
        lambda raw, selection: (_ for _ in ()).throw(ValueError("Not a statistical TSV table")),
    )
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assert executed["analysis"]["source"]["connector"]["name"] == "eurostat"
    assert result["covered"] == STRATEGY["measurements"]
    assessment = result["assessments"][0]
    assert assessment["decision"] == "analysed"
    assert assessment["recovery"][-1] == {
        "class": "reader",
        "action": "python_recovery",
        "outcome": "recovered",
    }
