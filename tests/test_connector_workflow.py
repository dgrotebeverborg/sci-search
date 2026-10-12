import pytest

from sci_search.data_research import workflow
from sci_search.data_research.connectors import eurostat
from sci_search.data_research.connectors import stage as connector_stage
from sci_search.research_runs import ResearchCancelled
from tests.test_connector_eurostat import offline
from tests.test_connector_recovery import BAD, GOOD, model
from tests.test_connector_stage import STRATEGY

DATABROWSER = "https://ec.europa.eu/eurostat/databrowser/view/demo_mlexpec/default/table"


def no_candidates(question, scope, **kwargs):
    return {"candidates": []}


def test_connector_analysis_skips_web_search_when_everything_is_covered(tmp_path):
    complete, _ = model([GOOD])

    def no_search(*a, **k):
        raise AssertionError("web search should not run")

    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=no_search,
        fetch=offline,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert result["analyses"] and result["analyses"][0]["source"]["connector"]["name"] == "eurostat"
    assert result["status"] == "partial"
    assert result["uncovered_measurements"] == []
    assert result["connector_search"]["terms"] == {STRATEGY["measurements"][0]: ["life expectancy"]}
    assert result["period"] == workflow.period_summary(STRATEGY, result["analyses"])


def test_uncovered_measurements_go_to_web_search_only(tmp_path):
    strategy = {**STRATEGY, "measurements": [*STRATEGY["measurements"], "healthy life years"]}
    complete, _ = model([GOOD])
    searched = {}

    def search(question, scope, **kwargs):
        searched["measurements"] = scope["measurements"]
        return {"candidates": []}

    result = workflow.execute(
        "Life expectancy",
        strategy,
        tmp_path,
        search=search,
        fetch=offline,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert searched["measurements"] == ["healthy life years"]
    # The result and its period summary still describe the whole request.
    assert result["strategy"]["measurements"] == strategy["measurements"]
    assert result["uncovered_measurements"] == ["healthy life years"]
    assert result["status"] == "partial"


def test_connectors_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")
    calls = {}

    def search(question, scope, **kwargs):
        calls["search"] = True
        return {"candidates": []}

    def fetch(url):
        raise AssertionError("no connector request expected: " + url)

    complete, seen = model([])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=search,
        fetch=fetch,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert calls["search"] and "connector_terms" not in seen
    assert not [key for key in result if key.startswith("connector")]
    assert not (tmp_path / "connectors").exists()
    assert result["status"] == "blocked"


def test_web_candidate_on_a_connector_host_is_rerouted(tmp_path):
    strategy = {**STRATEGY, "measurements": ["life expectancy at birth"]}
    # First round finds nothing (terms that match no dataflow), then web search returns a Eurostat page.
    complete, _ = model([GOOD], terms=(["zzzz"], ["zzzz"]), choices={"choices": []})

    def search(question, scope, **kwargs):
        return {
            "candidates": [
                {
                    "url": DATABROWSER,
                    "title": "Life expectancy",
                    "publisher": "Eurostat",
                    "rationale": "Official",
                }
            ]
        }

    result = workflow.execute(
        "Life expectancy",
        strategy,
        tmp_path,
        search=search,
        fetch=offline,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert result["analyses"][0]["source"]["connector"]["dataset"] == "demo_mlexpec"
    rerouted = [a for a in result["assessments"] if a.get("rerouted_from")]
    assert [a["rerouted_from"] for a in rerouted] == [DATABROWSER]
    assert result["status"] == "partial" and result["uncovered_measurements"] == []


def test_rerouting_never_repeats_a_dataset_the_stage_tried(tmp_path):
    # The stage tries demo_mlexpec and fails; the web candidate on the same dataset
    # is not analysed again through the connector but still gets the scraper path.
    complete, _ = model([BAD, BAD, BAD])
    fetched = []

    def search(question, scope, **kwargs):
        return {
            "candidates": [
                {
                    "url": DATABROWSER,
                    "title": "Life expectancy",
                    "publisher": "Eurostat",
                    "rationale": "",
                }
            ]
        }

    def fetch(url):
        fetched.append(url)
        if "databrowser" in url:
            return b"<html><body>Eurostat table</body></html>", "text/html", url
        try:
            return offline(url)
        except AssertionError as exc:
            raise OSError(str(exc)) from exc

    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=search,
        fetch=fetch,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    attempts = [a for a in result["assessments"] if a.get("dataset") == "demo_mlexpec"]
    assert len(attempts) == 1 and "rerouted_from" not in attempts[0]
    assert DATABROWSER in fetched  # the existing web path still checked the page
    assert any(a.get("url") == DATABROWSER and "failure_stage" in a for a in result["assessments"])


def test_script_only_pages_are_recorded_as_connector_gaps(tmp_path):
    strategy = {**STRATEGY, "measurements": ["river discharge"], "countries": []}
    complete, _ = model([], terms=(["zzzz"], ["zzzz"]), choices={"choices": []})

    def search(question, scope, **kwargs):
        return {
            "candidates": [
                {
                    "url": "https://waterinfo.rws.nl/#!/nav/index/",
                    "title": "Waterinfo",
                    "publisher": "Rijkswaterstaat",
                    "rationale": "Official",
                }
            ]
        }

    def fetch(url):
        if "waterinfo" in url:
            return b"<html><body>Loading...</body></html>", "text/html", url
        return offline(url)

    result = workflow.execute(
        "Rhine discharge",
        strategy,
        tmp_path,
        search=search,
        fetch=fetch,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert result["connector_gaps"] == [
        {
            "host": "waterinfo.rws.nl",
            "measurement": "river discharge",
            "evidence": result["connector_gaps"][0]["evidence"],
        }
    ]
    assert result["connector_gaps"][0]["evidence"] == "Page shows only a loading message"


def test_default_connector_fetch_is_bounded_to_5_mb(tmp_path, monkeypatch):
    limits = []

    def fetch_public(url, *, limit=50_000_000):
        limits.append(limit)
        raise OSError("offline")

    monkeypatch.setattr(workflow, "fetch_public", fetch_public)
    complete, _ = model([])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=no_candidates,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert limits and set(limits) == {5_000_000}
    assert result["assessments"][0]["failure_stage"] == "connector:search"


def test_a_failing_connector_stage_falls_back_to_web_search(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("connector bug")

    monkeypatch.setattr(connector_stage, "run", broken)
    searched = {}

    def search(question, scope, **kwargs):
        searched["measurements"] = scope["measurements"]
        return {"candidates": []}

    complete, _ = model([])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=search,
        fetch=offline,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert searched["measurements"] == STRATEGY["measurements"]
    assert result["assessments"][0]["failure_stage"] == "connector:stage"
    assert result["assessments"][0]["decision"] == "blocked"
    assert "connector bug" in result["assessments"][0]["reason"]
    assert result["status"] == "blocked"


def test_cancellation_inside_the_connector_stage_propagates(tmp_path):
    calls = []

    def check_cancelled():
        # execute's own first check passes, so the stage is the one that is cancelled.
        calls.append(1)
        if len(calls) > 1:
            raise ResearchCancelled("Research cancelled")

    complete, seen = model([GOOD])
    with pytest.raises(ResearchCancelled):
        workflow.execute(
            "Life expectancy",
            STRATEGY,
            tmp_path,
            search=no_candidates,
            fetch=offline,
            complete=complete,
            check_cancelled=check_cancelled,
            connectors={"eurostat": eurostat},
        )
    assert seen == ["connector_terms"]


def test_connector_analyses_replay_offline(tmp_path):
    import subprocess
    import sys

    complete, _ = model([GOOD])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=no_candidates,
        fetch=offline,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert result["analyses"]
    replay = subprocess.run(
        [sys.executable, "reproduce.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert replay.returncode == 0, replay.stderr
    assert "Verified connector-eurostat-demo-mlexpec-life-expectancy-at-birth" in replay.stdout
