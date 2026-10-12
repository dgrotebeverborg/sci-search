# tests/test_connector_recovery.py
import json
import zipfile

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
# The web path's source assessment for a page that only shows a loading message.
UNSUPPORTED = dict(
    adapter="unsupported",
    download_link_index=-1,
    reason="Page shows only a loading message",
    definition_quote="",
    license_note="Unknown",
    covered_measurements=[],
)


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
        if schema.get("title") is None:
            return UNSUPPORTED
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
        "Only annual frequency can be analysed",
        "Select one statistical unit",
        "Unsupported statistical observation or status: 12.3 x",
        "CBS flagged numeric observation requires explicit interpretation",
        "Normalized statistical table exceeds analysis limit; narrow filters",
        "Statistical slice is empty or too large; narrow dimension filters",
        "CBS period label does not match its annual code",
        "CBS observation references an unknown dimension code",
        "Every non-series dimension must be fixed to one observed code: age",
        "a message no reader has used before",
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
        lambda raw, selection: (_ for _ in ()).throw(
            ValueError("Response is not a JSON-stat dataset")
        ),
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


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("Not a statistical TSV table"),
        ValueError("Invalid GZIP dataset"),
        ValueError("OWID CSV lacks entity, year or the selected indicator column"),
        ValueError("Unsupported CBS observation schema"),
        json.JSONDecodeError("Expecting value", "x", 0),
        zipfile.BadZipFile("File is not a zip file"),
        KeyError("dimension"),
    ],
)
def test_parse_failures_are_reader_errors(exc):
    assert isinstance(stage._reader_failure(exc), base.ReaderError)


def test_a_bad_zip_reaches_python_recovery(tmp_path, monkeypatch):
    called = []

    def fake_recover(*args, **kwargs):
        called.append(1)
        raise ValueError("Python extraction stopped after 1 attempt(s)")

    def bad_zip(raw, selection):
        raise zipfile.BadZipFile("File is not a zip file")

    monkeypatch.setattr(stage, "recover_python", fake_recover)
    monkeypatch.setattr(stage, "prepare_table", bad_zip)
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assert called and result["assessments"][0]["failure_stage"] == "connector:python"


def test_python_recovery_must_represent_the_measurement(tmp_path, monkeypatch):
    seen = {}

    def fake_recover(question, strategy, data, source, folder, **kwargs):
        seen["measurements"] = strategy["measurements"]
        return {
            "series": [],
            "source": source,
            "semantic_review": {"accepted": True},
            "uncovered_measurements": list(strategy["measurements"]),
        }

    def forbidden(*args, **kwargs):
        raise AssertionError("an unrepresented measurement must not be executed")

    monkeypatch.setattr(stage, "recover_python", fake_recover)
    monkeypatch.setattr(stage, "execute_analysis", forbidden)
    monkeypatch.setattr(
        stage,
        "prepare_table",
        lambda raw, selection: (_ for _ in ()).throw(ValueError("Not a statistical TSV table")),
    )
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assert seen["measurements"] == [STRATEGY["measurements"][0]]
    assert result["covered"] == []
    assessment = result["assessments"][0]
    assert assessment["error_class"] == "DatasetRejected"
    assert assessment["reason"] == "Python extraction did not represent the measurement"


def test_reformulation_records_datasets_already_tried(tmp_path):
    # The fixture catalogue matches only demo_mlexpec, which the first round already tried.
    complete, _ = model([BAD, BAD, BAD])
    result = run(tmp_path, complete)
    assert result["assessments"][-1]["failure_stage"] == "connector:search"
    assert result["assessments"][-1]["reason"] == (
        "No connector dataset found after reformulated search: all reformulated datasets "
        "were already tried"
    )


def test_reformulation_records_an_invalid_choice(tmp_path):
    # The reformulation round finds new datasets, but the model picks one already tried.
    complete, _ = model([BAD, BAD, BAD], terms=(["life expectancy"], ["health"]))
    result = run(tmp_path, complete)
    assert result["search"]["reformulated_skipped_choices"][0]["reason"] == "unknown candidate"
    assert result["assessments"][-1]["failure_stage"] == "connector:search"
    assert result["assessments"][-1]["reason"] == (
        "No connector dataset found after reformulated search: reformulated choice was invalid"
    )


def test_catalogue_failures_are_recorded_once(tmp_path):
    def broken(url):
        if "/dataflow/ESTAT/all" in url:
            raise ValueError("Catalogue unavailable: HTTP 404")
        return offline(url)

    complete, seen = model([GOOD])
    result = run(tmp_path, complete, broken)
    assert seen.count("connector_terms") == 2
    catalogue = [a for a in result["assessments"] if a["title"] == "eurostat catalogue"]
    assert len(catalogue) == 1
    assert result["assessments"][-1]["reason"] == (
        "No connector dataset found after reformulated search"
    )
