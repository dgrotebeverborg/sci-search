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


def test_default_catalogue_fetch_is_bounded_to_20_mb(tmp_path, monkeypatch):
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
    # Only catalogue requests are made here; data requests are covered below.
    assert limits and set(limits) == {20_000_000}
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


def bounded_public_fetch(monkeypatch, oversized):
    """Replace fetch_public with the offline fixtures, enforcing the caller's limit."""
    calls = []

    def fetch_public(url, *, limit=50_000_000):
        calls.append((url, limit))
        body, kind, final = offline(url)
        if oversized(url):
            body += b"<!--" + b"x" * 6_000_000 + b"-->"
        if len(body) > limit:
            raise ValueError(f"Dataset exceeds the {limit // 1_000_000} MB acquisition limit")
        return body, kind, final

    monkeypatch.setattr(workflow, "fetch_public", fetch_public)
    return calls


def test_a_catalogue_over_5_mb_is_accepted_by_the_default_search_fetch(tmp_path, monkeypatch):
    calls = bounded_public_fetch(monkeypatch, lambda url: "/dataflow/ESTAT/all" in url)
    complete, _ = model([GOOD])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=no_candidates,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert result["analyses"]
    limits = {
        ("catalogue" if "/dataflow/ESTAT/all" in url else "data"): limit for url, limit in calls
    }
    assert limits == {"catalogue": 20_000_000, "data": 5_000_000}
    assert {limit for url, limit in calls if "/dataflow/ESTAT/all" not in url} == {5_000_000}


def test_a_data_response_over_5_mb_is_rejected_by_the_default_connector_fetch(
    tmp_path, monkeypatch
):
    bounded_public_fetch(monkeypatch, lambda url: "/data/demo_mlexpec/A.YR.F+M" in url)
    complete, _ = model([GOOD])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=no_candidates,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    assert not result["analyses"]
    attempt = next(a for a in result["assessments"] if a.get("dataset") == "demo_mlexpec")
    assert attempt["failure_stage"] == "connector:fetch"
    assert "5 MB acquisition limit" in attempt["reason"]


def test_a_second_run_on_the_same_day_reuses_the_shared_catalogue(tmp_path):
    catalogue_requests = []

    def fetch(url):
        if "/dataflow/ESTAT/all" in url:
            catalogue_requests.append(url)
        return offline(url)

    runs = []
    for number in (1, 2):
        complete, _ = model([GOOD])
        runs.append(
            workflow.execute(
                "Life expectancy",
                STRATEGY,
                tmp_path / f"run-{number}",
                search=no_candidates,
                fetch=fetch,
                complete=complete,
                connectors={"eurostat": eurostat},
                cache_dir=tmp_path / "connector-catalogues",
            )
        )
    assert len(catalogue_requests) == 1
    assert all(run["analyses"] for run in runs)
    digests = [run["connector_search"]["catalogues"]["eurostat"] for run in runs]
    assert digests[0] == digests[1] and len(digests[0]) == 64
    assert runs[1]["analyses"][0]["source"]["connector"]["catalogue_sha256"] == digests[0]
    assert not (tmp_path / "run-1" / "connectors" / "catalogues").exists()


def test_pages_on_a_connector_host_are_not_connector_gaps(tmp_path):
    strategy = {**STRATEGY, "measurements": ["river discharge"], "countries": []}
    complete, _ = model([], terms=(["zzzz"], ["zzzz"]), choices={"choices": []})
    page = "https://ec.europa.eu/eurostat/web/main/home"

    def search(question, scope, **kwargs):
        return {
            "candidates": [
                {"url": page, "title": "Eurostat", "publisher": "Eurostat", "rationale": ""}
            ]
        }

    def fetch(url):
        if url == page:
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
    assert any(a.get("url") == page and a.get("failure_stage") for a in result["assessments"])
    assert "connector_gaps" not in result


def test_reassessment_uses_the_candidates_own_folder_after_connector_assessments(tmp_path):
    import json

    from tests.data_meaning_fixtures import with_positive_meaning_review

    web_url = "https://example.org/data.csv"
    planned = []

    def model(prompt, schema):
        if schema.get("title") == "connector_terms":
            return {"terms": []}
        if "adapter" in schema["properties"]:
            return dict(
                adapter="unsupported",
                download_link_index=-1,
                reason="No bleaching",
                definition_quote="",
                license_note="Unknown",
                covered_measurements=[],
            )
        if "action" in schema["properties"]:
            sources = json.loads(prompt.rsplit("\n", 1)[1])["sources"]
            if planned:
                return dict(
                    action="stop",
                    source_index=-1,
                    link_index=-1,
                    query="",
                    measurements=[],
                    reason="Done",
                )
            planned.append(next(s["index"] for s in sources if s["url"] == web_url))
            return dict(
                action="reassess",
                source_index=planned[0],
                link_index=-1,
                query="",
                measurements=["coral cover"],
                reason="Use the supported cover subset",
            )
        if "code" in schema["properties"]:
            return dict(
                code="""import csv,json
from pathlib import Path
rows=list(csv.DictReader(Path('/input/source.bin').read_text().splitlines()))
Path('/output/observations.json').write_text(json.dumps({'observations':[dict(entity=r['Reef'],year=int(r['Year']),value=float(r['Cover']),unit='percent',measurement='coral cover',source_reference='row '+str(i+2)) for i,r in enumerate(rows)]}))
""",
                explanation="Extract cover only",
            )
        return dict(accepted=True, reason="Documented subset", limitations=["Bleaching missing"])

    def fetch(url):
        if url == web_url:
            return b"Year,Reef,Cover\n2024,A,40\n2025,A,50\n", "text/csv", url
        raise OSError("catalogue offline")

    result = workflow.execute(
        "cover and bleaching",
        dict(
            route="data",
            rationale="Trends",
            geography="A",
            measurements=["bleaching", "coral cover"],
            start_year=2024,
            end_year=2026,
        ),
        tmp_path,
        search=lambda *a, **k: dict(
            candidates=[dict(url=web_url, title="Cover", publisher="Agency")]
        ),
        fetch=fetch,
        complete=with_positive_meaning_review(model),
        connectors={"eurostat": eurostat},
    )
    assert planned[0] > 0  # connector assessments come first
    assert result["research_process"]["steps"][0]["outcome"]["status"] == "retained"
    assert (tmp_path / "source-1-review-1/analysis.json").exists()
    assessment = json.loads((tmp_path / "source-1/assessment.json").read_text())
    assert assessment["url"] == web_url and assessment["decision"] == "analysed"
    folders = sorted(p.name for p in tmp_path.glob("source-*"))
    assert folders == ["source-1", "source-1-review-1"]


def replayed(directory):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "reproduce.py"], cwd=directory, capture_output=True, text=True
    )


def connector_run(tmp_path):
    complete, _ = model([GOOD])
    workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        search=no_candidates,
        fetch=offline,
        complete=complete,
        connectors={"eurostat": eurostat},
    )
    return tmp_path / "connectors" / "connector-eurostat-demo-mlexpec-life-expectancy-at-birth"


def test_replay_fails_when_a_connector_artifact_is_tampered_with(tmp_path):
    import json

    folder = connector_run(tmp_path)
    source = folder / json.loads((folder / "analysis.json").read_text())["source"]["artifact"]
    source.write_bytes(source.read_bytes() + b"\n")
    replay = replayed(tmp_path)
    assert replay.returncode != 0 and "Artifact hash mismatch" in replay.stderr


def test_replay_fails_when_a_connector_folder_is_missing(tmp_path):
    import shutil

    shutil.rmtree(connector_run(tmp_path))
    replay = replayed(tmp_path)
    assert replay.returncode != 0 and "a source is missing" in replay.stderr


def test_research_runs_pass_the_shared_catalogue_cache(tmp_path, monkeypatch):
    from sci_search.question_interpretation import interpret_question
    from sci_search.research_runs import ResearchLimits, ResearchRunManager

    question = "How has life expectancy in the Netherlands changed?"
    brief = interpret_question(question)
    brief["ambiguity"] = "clear"
    brief["data_research"] = {**STRATEGY, "route": "data"}
    seen = {}

    def execute(question, strategy, directory, **kwargs):
        seen["cache_dir"] = kwargs.get("cache_dir")
        result = {"kind": "discovered", "status": "blocked", "strategy": strategy}
        result.update(analyses=[], assessments=[], limitations=["Fixture"])
        directory.mkdir(parents=True, exist_ok=True)
        workflow.save(directory / "analysis.json", result)
        return result

    monkeypatch.setattr(workflow, "execute", execute)

    class Provider:
        name = "fixture"

        def search(self, *a, **k):
            return ()

    cache = tmp_path / "connector-catalogues"
    manager = ResearchRunManager(
        tmp_path / "runs",
        providers=(Provider(),),
        openalex_api_key="unused",
        connector_cache_dir=cache,
    )
    manager.run_sync(question, question_brief=brief, limits=ResearchLimits(max_full_texts=1))
    assert seen["cache_dir"] == cache


def test_production_stage_shares_a_catalogue_cache_outside_the_run(monkeypatch):
    import tempfile
    from pathlib import Path

    from sci_search.infrastructure import research_execution, sql_memory
    from sci_search.research_runs import ResearchRunManager
    from sci_search.worker import CancellationToken, StageInvocation

    seen = {}

    class Manager(ResearchRunManager):
        def run_sync(self, question, *, limits, **kwargs):
            seen.update(root=self.root, cache=self.connector_cache_dir)
            return {"status": "complete", "run_id": "internal", "result": {}}

    class Provider:
        name = "fixture"

        def search(self, *a, **k):
            return ()

    class Stage(research_execution.ProductionResearchStage):
        def _publish_corpus(self, *args):
            return {}

        def _publish_artifacts(self, *args):
            return []

        def publish_dashboard(self, *args, **kwargs):
            return None

    monkeypatch.setattr(sql_memory, "memory_for_project", lambda *a, **k: None)
    stage = Stage(
        None,
        None,
        manager_factory=lambda root: Manager(root, providers=(Provider(),), openalex_api_key="x"),
    )
    stage(
        StageInvocation(
            {"question": "Question", "run_id": "run", "project_id": "project"},
            CancellationToken(lambda: False),
        )
    )
    assert seen["cache"] == Path(tempfile.gettempdir()) / "sci-search-connector-catalogues"
    assert not seen["cache"].resolve().is_relative_to(seen["root"])
