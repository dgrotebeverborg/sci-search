# tests/test_connector_stage.py
import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import types

import pytest

from sci_search.data_research.connectors import base, stage
from tests.data_meaning_fixtures import with_positive_meaning_review


def offline(url):
    from tests.test_connector_eurostat import offline as eurostat_offline

    return eurostat_offline(url)


STRATEGY = {
    "adapter": "discovered_data_v1",
    "route": "data",
    "rationale": "Annual statistics",
    "measurements": ["life expectancy at birth"],
    "geography": "Netherlands, Germany and Greece",
    "country_scope": "other",
    "countries": ["NLD", "DEU", "GRC"],
    "start_year": 2000,
    "end_year": 2024,
}


def scripted(prompt, schema):
    title = schema.get("title", "")
    if title == "connector_terms":
        return {
            "terms": [
                {"measurement": "life expectancy at birth", "terms": ["life expectancy", "sex"]}
            ]
        }
    if title == "connector_choice":
        return {
            "choices": [
                {
                    "candidate": "eurostat:demo_mlexpec",
                    "measurement": "life expectancy at birth",
                    "reason": "Annual by sex and country",
                }
            ]
        }
    if title == "connector_selection":
        return {
            "filters": {
                "freq": ["A"],
                "unit": ["YR"],
                "sex": ["F", "M"],
                "age": ["Y_LT1"],
                "geo": ["NL", "DE", "EL"],
            },
            "series_dimensions": ["sex", "geo"],
            "reason": "Birth, both sexes, requested countries",
        }
    raise AssertionError("unexpected model call " + title)


def test_stage_produces_an_executed_analysis(tmp_path):
    from sci_search.data_research.connectors import eurostat

    result = stage.run(
        "How has life expectancy changed for men and women in NL, DE and GR?",
        STRATEGY,
        tmp_path,
        complete=with_positive_meaning_review(scripted),
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )
    assert result["covered"] == ["life expectancy at birth"]
    analysis = result["analyses"][0]
    assert analysis["execution"]["status"] == "verified"
    assert analysis["source"]["connector"]["dataset"] == "demo_mlexpec"
    assert (
        "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/"
        in analysis["source"]["connector"]["request"]["url"]
    )
    assert len(analysis["series"]) == 6
    assert result["assessments"][0]["decision"] == "analysed"


def test_selection_schema_enumerates_observed_codes():
    description = base.DatasetDescription(
        candidate=base.DatasetCandidate("x", "d", "t", "annual"),
        dimensions=(base.Dimension("geo", "Country", {"NL": "Netherlands"}),),
        years=(),
        licence_url="",
        definitions="",
        publisher="",
    )
    schema = stage.selection_schema(description)
    assert schema["properties"]["filters"]["properties"]["geo"]["items"]["enum"] == ["NL"]
    assert schema["properties"]["series_dimensions"]["items"]["enum"] == ["geo"]


def run_stage(tmp_path, complete, strategy=STRATEGY):
    from sci_search.data_research.connectors import eurostat

    return stage.run(
        "How has life expectancy changed?",
        strategy,
        tmp_path,
        complete=with_positive_meaning_review(complete),
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )


def test_the_same_dataset_for_two_measurements_keeps_both_analyses_sealed(tmp_path):
    strategy = {
        **STRATEGY,
        "measurements": ["life expectancy at birth", "life expectancy by sex"],
    }

    def complete(prompt, schema):
        if schema["title"] == "connector_terms":
            return {
                "terms": [
                    {"measurement": m, "terms": ["life expectancy"]}
                    for m in strategy["measurements"]
                ]
            }
        if schema["title"] == "connector_choice":
            return {
                "choices": [
                    {"candidate": "eurostat:demo_mlexpec", "measurement": m, "reason": "r"}
                    for m in strategy["measurements"]
                ]
            }
        return scripted(prompt, schema)

    result = run_stage(tmp_path, complete, strategy)
    assert result["covered"] == strategy["measurements"]
    folders = sorted(p for p in tmp_path.glob("connector-*"))
    assert len(folders) == 2
    for analysis in result["analyses"]:
        folder = next(
            f
            for f in folders
            if json.loads((f / "analysis.json").read_text())["mapping"]["label"]
            == analysis["mapping"]["label"]
        )
        for name, digest in analysis["execution"]["artifacts"].items():
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest


def test_attempt_folders_are_never_reused(tmp_path):
    first = stage._attempt_folder(tmp_path, "eurostat", "demo_mlexpec", "Life expectancy")
    second = stage._attempt_folder(tmp_path, "eurostat", "demo_mlexpec", "Life expectancy")
    assert first.name == "connector-eurostat-demo-mlexpec-life-expectancy"
    assert second.name == first.name + "-2"


@pytest.mark.parametrize(
    "reply",
    [
        {"choices": [{"candidate": ["eurostat:demo_mlexpec"], "measurement": "m", "reason": ""}]},
        {"picked": []},
        ValueError("model reply was not JSON"),
    ],
)
def test_a_malformed_dataset_choice_is_a_blocked_assessment(tmp_path, reply):
    def complete(prompt, schema):
        if schema["title"] == "connector_choice":
            if isinstance(reply, Exception):
                raise reply
            return reply
        return scripted(prompt, schema)

    result = run_stage(tmp_path, complete)
    assert result["analyses"] == []
    assert result["search"]["catalogues"]["eurostat"]
    choice = [a for a in result["assessments"] if a.get("failure_stage") == "connector:choice"]
    assert choice and all(a["decision"] == "blocked" for a in choice)
    # The reformulation round's choice is malformed too, and its outcome is recorded.
    assert result["assessments"][-1]["failure_stage"] == "connector:search"
    assert result["assessments"][-1]["reason"].endswith("reformulated choice was invalid")


def test_unusable_choices_are_recorded_as_skipped(tmp_path):
    def complete(prompt, schema):
        if schema["title"] == "connector_choice":
            return {
                "choices": [
                    {
                        "candidate": "http://evil/x",
                        "measurement": "life expectancy at birth",
                        "reason": "",
                    },
                    {"candidate": "eurostat:demo_mlexpec", "measurement": "gdp", "reason": ""},
                ]
            }
        return scripted(prompt, schema)

    result = run_stage(tmp_path, complete)
    assert result["analyses"] == []
    assert result["search"]["skipped_choices"] == [
        {
            "candidate": "http://evil/x",
            "measurement": "life expectancy at birth",
            "reason": "unknown candidate",
        },
        {
            "candidate": "eurostat:demo_mlexpec",
            "measurement": "gdp",
            "reason": "measurement not requested",
        },
    ]


def single(connector, candidate, scope, selection, tmp_path, fetch):
    def complete(prompt, schema):
        assert schema["title"] == "connector_selection"
        return selection

    return stage.analyse_dataset(
        "q",
        scope,
        tmp_path,
        connector,
        candidate,
        "m",
        complete=with_positive_meaning_review(complete),
        fetch=fetch,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
    )


def scope_for(countries, end_year):
    return {**STRATEGY, "measurements": ["m"], "countries": countries, "end_year": end_year}


def run_download(folder, tmp_path):
    """Run the retained DOWNLOAD script with a retrieval stub that fails on any request."""
    replay = tmp_path / "replay"
    replay.mkdir()
    for name in ("download_source.py", "source-metadata.json"):
        shutil.copy(folder / name, replay / name)
    (replay / "retrieval.py").write_text(
        "def fetch_public(url):\n    raise AssertionError('network request ' + url)\n"
    )
    return subprocess.run(
        [sys.executable, str(replay / "download_source.py"), "--output", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cbs_through_analyse_dataset(tmp_path):
    from sci_search.data_research.connectors import cbs
    from tests.test_connector_cbs import CANDIDATE, selection_for
    from tests.test_connector_cbs import offline as cbs_offline

    scope = scope_for(["NLD"], 2024)
    description = cbs.describe(CANDIDATE, scope, fetch=cbs_offline)
    analysis, assessment = single(
        cbs, CANDIDATE, scope, selection_for(description), tmp_path, cbs_offline
    )
    assert assessment["decision"] == "analysed", assessment.get("reason")
    assert analysis is not None
    assert analysis["execution"]["status"] == "verified"
    assert analysis["source"]["download"] == {"reproducible": True}


def test_owid_is_analysed_but_marked_not_get_reproducible(tmp_path):
    from sci_search.data_research.connectors import owid
    from tests.test_connector_owid import CANDIDATE
    from tests.test_connector_owid import offline as owid_offline

    scope = scope_for(["NLD", "DEU"], 2023)
    description = owid.describe(CANDIDATE, scope, fetch=owid_offline)
    indicator = next(iter({d.id: d for d in description.dimensions}["indicator"].codes))
    selection = {
        "filters": {"indicator": [indicator], "entity": ["Germany", "Netherlands"]},
        "series_dimensions": ["entity"],
        "reason": "r",
    }
    analysis, assessment = single(owid, CANDIDATE, scope, selection, tmp_path, owid_offline)
    assert assessment["decision"] == "analysed", assessment.get("reason")
    assert analysis is not None
    assert analysis["execution"]["status"] == "verified"
    download = analysis["source"]["download"]
    assert download["reproducible"] is False and "connector.request" in download["reason"]
    replay = run_download(next(tmp_path.glob("connector-*")), tmp_path)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["reproducible"] is False
    assert not (tmp_path / "out").exists()


def test_a_post_request_is_marked_not_get_reproducible(tmp_path):
    from sci_search.data_research.connectors import eurostat

    def posted(description, selection, scope, *, fetch, post):
        fetched = eurostat.fetch(description, selection, scope, fetch=fetch, post=post)
        request = {"method": "POST", "url": fetched.request["url"], "body": {"query": []}}
        return dataclasses.replace(fetched, request=request)

    connector = types.SimpleNamespace(
        NAME=eurostat.NAME,
        PUBLISHER=eurostat.PUBLISHER,
        describe=eurostat.describe,
        fetch=posted,
        mapping=eurostat.mapping,
    )
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual")
    analysis, assessment = single(
        connector,
        candidate,
        STRATEGY,
        scripted({}, {"title": "connector_selection"}),
        tmp_path,
        offline,
    )
    assert assessment["decision"] == "analysed", assessment.get("reason")
    assert analysis is not None
    assert analysis["source"]["download"]["reproducible"] is False
    assert "POST" in analysis["source"]["download"]["reason"]
    replay = run_download(next(tmp_path.glob("connector-*")), tmp_path)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["reproducible"] is False


def test_the_meaning_review_prompt_leaves_out_row_provenance(tmp_path):
    # Row provenance lists every source row; a CBS package made the live prompt 1.4 MB.
    from sci_search.data_research.connectors import eurostat

    prompts = []
    reviewed = with_positive_meaning_review(scripted)

    def recording(prompt, schema):
        if set(schema["properties"]) == {"measurements"}:
            prompts.append(prompt)
        return reviewed(prompt, schema)

    result = stage.run(
        "How has life expectancy changed?",
        STRATEGY,
        tmp_path,
        complete=recording,
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )
    assert result["covered"] == ["life expectancy at birth"]
    assert prompts and all("row_provenance" not in p for p in prompts)
    assert result["analyses"][0]["preparation"]["row_provenance"]
