# tests/test_connector_stage.py
import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import types
from xml.etree import ElementTree

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
                {
                    "measurement": "life expectancy at birth",
                    "english": ["life expectancy", "sex"],
                    "dutch": ["levensverwachting"],
                }
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


def test_second_candidate_can_complete_the_same_measurement(tmp_path, monkeypatch):
    from tests.test_data_coverage_contract import SCOPE, analysis

    connector = types.SimpleNamespace(NAME="fixture")
    candidates = {
        key: (connector, base.DatasetCandidate("fixture", key, key, "annual"))
        for key in ("first", "second")
    }
    result = {"analyses": [], "covered": [], "assessments": [], "search": {"catalogues": {}}}

    def analyse(*args, **kwargs):
        candidate = args[4]
        entity = "Netherlands" if candidate.dataset == "first" else "Germany"
        return analysis(entity), {"decision": "analysed", "recovery": []}

    monkeypatch.setattr(stage, "analyse_dataset", analyse)
    stage._choose_and_analyse(
        "Compare",
        SCOPE,
        tmp_path,
        candidates,
        SCOPE["measurements"],
        result,
        complete=lambda *args: {
            "choices": [
                {"candidate": key, "measurement": "life expectancy", "reason": "complement"}
                for key in candidates
            ]
        },
        fetch=None,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda _: None,
        skipped=[],
    )
    assert len(result["analyses"]) == 2
    assert result["covered"] == ["life expectancy"]


def test_meaning_review_receives_the_selected_codes_as_plain_text(tmp_path):
    from sci_search.data_research.connectors import eurostat

    stage.run(
        "How has life expectancy changed?",
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
    review = next(tmp_path.rglob("semantic-review.json"))
    selection = json.loads(review.read_text())["evidence_documents"]["selection"]
    assert "Age class: Y_LT1 = Less than 1 year" in selection
    assert "Sex: F = Females" in selection
    assert "Geopolitical entity (reporting): EL = Greece" in selection


def test_table_evidence_summarises_every_selected_series_and_samples_both_ends():
    rows = [
        {"Year": str(y), "Series": s, "Value": str(v), "Measure": m}
        for m in ("kept", "other")
        for s in ("A", "B")
        for y, v in ((2000, 1), (2001, 2), (2024, 9))
    ]
    mapping = {
        "year_column": "Year",
        "value_column": "Value",
        "entity_column": "Series",
        "filters": [{"column": "Measure", "value": "kept"}],
    }
    summary, sample = stage.table_evidence(rows, mapping)
    assert "Selected rows: 6 of 12 table rows" in summary
    assert "Series A: 3 rows, years 2000-2024; first 2000 = 1; last 2024 = 9" in summary
    assert "Series B: 3 rows" in summary
    years = [r["Year"] for r in json.loads(sample)]
    assert "2024" in years and "2000" in years
    assert all(r["Measure"] == "kept" for r in json.loads(sample))


def test_table_evidence_keeps_to_the_requested_period():
    rows = [{"Year": str(y), "Series": "A", "Value": str(y - 1999)} for y in range(1990, 2026)]
    mapping = {"year_column": "Year", "value_column": "Value", "entity_column": "Series"}
    summary, sample = stage.table_evidence(rows, mapping, {"start_year": 2000, "end_year": 2024})
    assert "Selected rows: 36 of 36 table rows; 25 in the requested period 2000-2024" in summary
    assert "Series A: 25 rows, years 2000-2024; first 2000 = 1; last 2024 = 25" in summary
    assert {r["Year"] for r in json.loads(sample)} <= {str(y) for y in range(2000, 2025)}


def test_table_evidence_exposes_middle_year_status_flags_for_each_series():
    rows = [
        {"Year": str(y), "Series": s, "Value": "10", "Status": "b" if (s, y) == ("A", 2012) else ""}
        for s in ("A", "B")
        for y in range(2000, 2025)
    ]
    mapping = {"year_column": "Year", "value_column": "Value", "entity_column": "Series"}
    summary, _ = stage.table_evidence(rows, mapping)
    assert "Series A: Status b in 2012" in summary
    assert "Series B: Status b" not in summary
    summary, _ = stage.table_evidence(rows, mapping, {"start_year": 2013, "end_year": 2024})
    assert "Status b" not in summary


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
                    {"measurement": m, "english": ["life expectancy"], "dutch": ["leven"]}
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


def test_english_measurement_text_is_searched_and_dutch_terms_only_in_dutch_catalogues(tmp_path):
    # A live Mistral reply gave only Dutch terms, so Eurostat searched in Dutch.
    searched = {}

    def connector(name, languages):
        def search(terms, scope, *, fetch, cache_dir):
            searched.setdefault(name, list(terms))  # the first round
            return [], "digest"

        return types.SimpleNamespace(NAME=name, LANGUAGES=languages, search=search)

    def complete(prompt, schema):
        assert schema["title"] == "connector_terms"
        assert schema["properties"]["terms"]["items"]["required"] == [
            "measurement",
            "english",
            "dutch",
        ]
        return {
            "terms": [
                {
                    "measurement": "life expectancy at birth",
                    "english": ["levensverwachting"],
                    "dutch": ["levensverwachting bij geboorte"],
                }
            ]
        }

    stage.run(
        "q",
        STRATEGY,
        tmp_path,
        complete=complete,
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={
            "eurostat": connector("eurostat", ("en",)),
            "cbs": connector("cbs", ("nl", "en")),
        },
        cache_dir=tmp_path / "cache",
    )
    assert "life expectancy at birth" in searched["eurostat"]
    assert "levensverwachting bij geboorte" not in searched["eurostat"]
    assert "levensverwachting bij geboorte" in searched["cbs"]
    assert "life expectancy at birth" in searched["cbs"]


def test_every_connector_declares_its_search_languages():
    from sci_search.data_research.connectors import CONNECTORS

    assert {name: c.LANGUAGES for name, c in CONNECTORS.items()} == {
        "eurostat": ("en",),
        "cbs": ("nl", "en"),
        "pxweb": ("en",),
        "owid": ("en",),
    }


def test_the_selection_schema_pins_one_owid_indicator():
    # A live model used several OWID indicators as a series three times in a row.
    from sci_search.data_research.connectors import owid
    from tests.test_connector_owid import CANDIDATE, SCOPE
    from tests.test_connector_owid import offline as owid_offline

    schema = stage.selection_schema(owid.describe(CANDIDATE, SCOPE, fetch=owid_offline))
    filters = schema["properties"]["filters"]["properties"]
    assert filters["indicator"]["maxItems"] == 1
    assert "maxItems" not in filters["entity"]
    assert schema["properties"]["series_dimensions"]["items"]["enum"] == ["entity"]


def test_the_selection_schema_follows_the_cbs_series_rules():
    from sci_search.data_research.connectors import cbs
    from tests.test_connector_cbs import CANDIDATE, SCOPE
    from tests.test_connector_cbs import offline as cbs_offline

    schema = stage.selection_schema(cbs.describe(CANDIDATE, SCOPE, fetch=cbs_offline))
    assert schema["properties"]["filters"]["properties"]["Measure"]["maxItems"] == 1
    series = schema["properties"]["series_dimensions"]
    assert series["maxItems"] == 1 and "Measure" not in series["items"]["enum"]


def test_search_term_schemas_enumerate_the_requested_measurements(tmp_path):
    from sci_search.data_research.connectors import eurostat

    schemas = []

    def complete(prompt, schema):
        if schema["title"] == "connector_terms":
            schemas.append(schema)
            return {"terms": []}
        return scripted(prompt, schema)

    strategy = {**STRATEGY, "measurements": ["zzzz qqqq"]}
    stage.run(
        "q",
        strategy,
        tmp_path,
        complete=complete,
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )
    assert len(schemas) == 2  # the first search and the reformulation round
    for schema in schemas:
        item = schema["properties"]["terms"]["items"]["properties"]["measurement"]
        assert item == {"type": "string", "enum": ["zzzz qqqq"]}


def broken_connector(error):
    def describe(candidate, scope, *, fetch):
        raise error

    return types.SimpleNamespace(NAME="broken", PUBLISHER="X", describe=describe)


BROKEN = base.DatasetCandidate("broken", "b1", "Healthy life years", "annual")


@pytest.mark.parametrize(
    "error",
    [ElementTree.ParseError("not xml"), StopIteration(), AttributeError("x"), RuntimeError("bug")],
)
def test_an_unexpected_connector_error_is_a_blocked_assessment(tmp_path, error):
    analysis, assessment = single(broken_connector(error), BROKEN, STRATEGY, {}, tmp_path, offline)
    assert analysis is None
    assert assessment["decision"] == "blocked"
    assert assessment["failure_stage"] == "connector:describe"
    assert assessment["error_class"] == type(error).__name__


def test_cancellation_inside_analyse_dataset_propagates(tmp_path):
    from sci_search.research_runs import ResearchCancelled

    def cancelled():
        raise ResearchCancelled("Research cancelled")

    with pytest.raises(ResearchCancelled):
        stage.analyse_dataset(
            "q",
            STRATEGY,
            tmp_path,
            broken_connector(RuntimeError("bug")),
            BROKEN,
            "m",
            complete=lambda prompt, schema: {},
            fetch=offline,
            post=None,
            check_cancelled=cancelled,
            progress=lambda m: None,
        )


def test_a_cancellation_turned_into_another_error_still_propagates(tmp_path, monkeypatch):
    # A step that receives check_cancelled and wraps its exception must not hide the cancellation.
    from sci_search.data_research.connectors import eurostat
    from sci_search.research_runs import ResearchCancelled

    calls = []

    def cancelled_during_execution():
        calls.append(1)
        if len(calls) > 2:
            raise ResearchCancelled("Research cancelled")

    def execute_analysis(analysis, folder, *, check_cancelled):
        try:
            check_cancelled()
        except ResearchCancelled as exc:
            raise ValueError("execution stopped") from exc
        return analysis

    monkeypatch.setattr(stage, "execute_analysis", execute_analysis)
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual")
    with pytest.raises(ResearchCancelled):
        stage.analyse_dataset(
            "q",
            STRATEGY,
            tmp_path,
            eurostat,
            candidate,
            "life expectancy at birth",
            complete=with_positive_meaning_review(scripted),
            fetch=offline,
            post=None,
            check_cancelled=cancelled_during_execution,
            progress=lambda m: None,
        )


def test_a_reader_attribute_error_rejects_the_dataset(tmp_path, monkeypatch):
    from sci_search.data_research.connectors import eurostat

    def unreadable(raw, selection=None):
        raise AttributeError("'int' object has no attribute 'strip'")

    monkeypatch.setattr(stage, "prepare_table", unreadable)
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual")
    analysis, assessment = single(
        eurostat,
        candidate,
        STRATEGY,
        scripted({}, {"title": "connector_selection"}),
        tmp_path,
        offline,
    )
    assert analysis is None
    assert assessment["failure_stage"] == "connector:normalize"
    assert assessment["error_class"] == "DatasetRejected"


def test_an_unexpected_catalogue_error_is_a_blocked_search(tmp_path):
    def search(terms, scope, *, fetch, cache_dir):
        raise ElementTree.ParseError("not xml")

    broken = types.SimpleNamespace(NAME="broken", LANGUAGES=("en",), search=search)
    result = {"assessments": [], "search": {"catalogues": {}}}
    found = stage._search_all(
        {"broken": broken},
        {"en": ["x"]},
        STRATEGY,
        offline,
        tmp_path,
        result,
        check_cancelled=lambda: None,
    )
    assert found == {}
    assert result["assessments"][0]["failure_stage"] == "connector:search"
    assert "not xml" in result["assessments"][0]["reason"]


def test_a_dimension_with_too_many_codes_is_rejected_before_the_model_is_asked(tmp_path):
    codes = {f"R{i}": f"Region {i}" for i in range(1500)}

    def describe(candidate, scope, *, fetch):
        return base.DatasetDescription(
            candidate=candidate,
            dimensions=(base.Dimension("geo", "geo", codes),),
            years=(),
            licence_url="",
            definitions="",
            publisher="X",
        )

    asked = []
    connector = types.SimpleNamespace(NAME="many", PUBLISHER="X", describe=describe)
    analysis, assessment = stage.analyse_dataset(
        "q",
        STRATEGY,
        tmp_path,
        connector,
        BROKEN,
        "m",
        complete=lambda prompt, schema: asked.append(schema) or {},
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
    )
    assert analysis is None and asked == []
    assert assessment["reason"] == "dimension geo lists 1500 codes; narrow the geography"
    assert assessment["error_class"] == "DatasetRejected"
    assert assessment["failure_stage"] == "connector:describe"


def test_a_dimension_with_1000_codes_is_offered_to_the_model():
    description = base.DatasetDescription(
        candidate=BROKEN,
        dimensions=(base.Dimension("geo", "geo", {f"R{i}": "" for i in range(1000)}),),
        years=(),
        licence_url="",
        definitions="",
        publisher="X",
    )
    stage._check_code_counts(description)  # does not raise


def test_dataset_choices_are_constrained_to_current_candidates_and_measurements(tmp_path):
    def complete(prompt, schema):
        if schema["title"] == "connector_choice":
            props = schema["properties"]["choices"]["items"]["properties"]
            payload = json.loads(prompt[prompt.index("{") :])
            assert props["candidate"].get("enum") == [c["key"] for c in payload["candidates"]]
            assert props["measurement"].get("enum") == STRATEGY["measurements"]
        return scripted(prompt, schema)

    result = run_stage(tmp_path, complete)
    assert result["analyses"]


def test_selection_scope_contains_only_the_input_being_selected(tmp_path):
    from sci_search.data_research.connectors import eurostat

    scope = {
        **STRATEGY,
        "measurements": [*STRATEGY["measurements"], "population"],
        "calculations": [{"operation": "difference"}],
    }

    def complete(prompt, schema):
        if schema["title"] == "connector_selection":
            payload = json.loads(prompt[prompt.index("{") :])
            assert payload["scope"]["measurements"] == STRATEGY["measurements"]
            assert "calculations" not in payload["scope"]
        return scripted(prompt, schema)

    analysis, _ = stage.analyse_dataset(
        "Life expectancy and population",
        scope,
        tmp_path,
        eurostat,
        base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual"),
        STRATEGY["measurements"][0],
        complete=with_positive_meaning_review(complete),
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda _: None,
    )
    assert analysis
