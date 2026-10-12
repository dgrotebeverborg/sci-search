import pytest

from sci_search.data_research.discovery import observed_urls
from sci_search.data_research.strategy import validate_strategy
from sci_search.data_research.tabular import analyse_csv
from tests.data_meaning_fixtures import with_positive_meaning_review


def strategy(**updates):
    return validate_strategy(
        dict(
            route="data",
            rationale="Annual observations answer the question.",
            measurements=["population"],
            geography="Netherlands",
            start_year=2001,
            end_year=2003,
            **updates,
        )
    )


def test_strategy_cannot_execute_urls_or_code():
    value = strategy()
    assert value["adapter"] == "discovered_data_v1"
    with pytest.raises(ValueError):
        validate_strategy({**value, "route": "shell"})
    with pytest.raises(ValueError):
        validate_strategy({**value, "start_year": True})


def mapping():
    return {
        "year_column": "Year",
        "entity_column": "Country",
        "entities": ["Netherlands"],
        "value_column": "Population",
        "unit": "people",
        "output_unit": "people",
        "filters": {},
        "label": "Population",
        "missing_values": ["", ":"],
        "decimal_separator": ".",
    }


def test_csv_keeps_zero_and_missing_separate_and_filters_exactly():
    body = b"Year,Country,Population\n2001,Netherlands,0\n2002,Netherlands,:\n2003,Netherlands,12\n2003,Belgium,9\n"
    result = analyse_csv(body, mapping(), strategy())
    assert [r["value"] for r in result["series"][0]["annual"]] == [0, None, 12]
    assert result["series"][0]["missing_years"] == [2002]
    assert result["series"][0]["change_percent"] is None
    assert result["series"][0]["annual"][2]["source_row"] == 4


def test_csv_rejects_duplicate_observations_and_unapproved_conversion():
    with pytest.raises(ValueError, match="Duplicate"):
        analyse_csv(
            b"Year,Country,Population\n2001,Netherlands,1\n2001,Netherlands,2",
            mapping(),
            strategy(),
        )
    with pytest.raises(ValueError, match="unit"):
        analyse_csv(
            b"Year,Country,Population\n2001,Netherlands,1",
            {**mapping(), "output_unit": "km2"},
            strategy(),
        )


def test_discovery_does_not_trust_urls_in_generated_text():
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "https://invented.test/data.csv",
                        "annotations": [
                            {"type": "url_citation", "url": "https://official.test/data"}
                        ],
                    }
                ],
            },
            {"type": "web_search_call", "action": {"sources": [{"url": "https://catalogue.test"}]}},
        ]
    }
    assert observed_urls(response) == {"https://official.test/data", "https://catalogue.test"}


def test_workflow_downloads_observed_csv_and_replays(tmp_path):
    import io
    import subprocess
    import sys
    import zipfile

    from sci_search.data_research.reporting import export
    from sci_search.data_research.workflow import execute

    url = "https://stats.example/data"
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
    result = execute(
        "Population of Netherlands 2001–2003",
        strategy(),
        tmp_path,
        search=lambda *a, **k: dict(
            candidates=[
                dict(
                    url=url, title="Population", publisher="Statistics office", rationale="Official"
                )
            ]
        ),
        fetch=lambda u: (page, "text/html", u) if u == url else (data, "text/csv", u),
        complete=with_positive_meaning_review(lambda *a: next(replies)),
    )
    assert result["status"] == "partial"
    assert result["analyses"][0]["series"][0]["change_percent"] == 20
    _, _, package = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)


def test_workflow_keeps_failed_discovery_visible(tmp_path):
    from sci_search.data_research.workflow import execute, investigation

    def fail(*a, **k):
        raise ValueError("No web search configured")

    result = execute("Population", strategy(), tmp_path, search=fail)
    assert result["status"] == "blocked"
    assert not result["analyses"]
    assert "No web search configured" in result["limitations"][0]
    assert not investigation("Population", {}, result)["answer_adequacy"][
        "can_answer_overall_question"
    ]


def test_public_downloader_rejects_private_dns(monkeypatch):
    import socket

    from sci_search.data_research.retrieval import public_addresses

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        public_addresses("https://example.org/data.csv")
    with pytest.raises(ValueError):
        public_addresses("file:///etc/passwd")


@pytest.mark.parametrize("route", ["data", "both"])
def test_manager_executes_discovered_route_and_preserves_both_exports(tmp_path, monkeypatch, route):
    import io
    import zipfile

    from sci_search.data_research import workflow
    from sci_search.question_interpretation import interpret_question
    from sci_search.research_runs import ResearchLimits, ResearchRunManager

    question = "How has the population of the Netherlands changed?"
    brief = interpret_question(question)
    brief["ambiguity"] = "clear"
    brief["data_research"] = {**strategy(), "route": route}

    def execute(*args, **kwargs):
        result = {
            "kind": "discovered",
            "status": "blocked",
            "strategy": brief["data_research"],
            "analyses": [],
            "limitations": ["Fixture source unavailable"],
            "assessments": [],
        }
        directory = args[2]
        directory.mkdir(parents=True, exist_ok=True)
        workflow.save(directory / "analysis.json", result)
        return result

    monkeypatch.setattr(workflow, "execute", execute)

    class Provider:
        name = "fixture"
        calls = 0

        def search(self, *a, **k):
            self.calls += 1
            return ()

    provider = Provider()
    manager = ResearchRunManager(tmp_path, providers=(provider,), openalex_api_key="unused")
    state = manager.run_sync(
        question, question_brief=brief, limits=ResearchLimits(max_full_texts=1)
    )
    assert state["status"] == "complete", state.get("error")
    assert state["result"]["data_analysis"]["status"] == "blocked"
    assert provider.calls  # Empty data research continues with literature.
    assert state["result"]["data_analysis"]["strategy"]["route"] == "both"
    package = manager.download_research_package(state["run_id"])
    with zipfile.ZipFile(io.BytesIO(package.body)) as z:
        assert "data-research/reproduce.py" in z.namelist()
        if route == "both":
            assert "literature-review.html" in z.namelist()
            assert b"Appendix E" in z.read("literature-review.html")
    if route == "both":
        assert b"Dataset research" in manager.download_literature_review(state["run_id"]).body


def test_model_interpretation_can_plan_non_wildfire_data():
    import json

    from sci_search.mistral_analysis import ModelAnalyzer
    from sci_search.question_interpretation import interpret_question

    response = {
        "interpreted_question": "Population trend",
        "objective": "Measure annual population",
        "evidence_scope": ["Official population observations"],
        "assumptions": [],
        "exclusions": [],
        "ambiguity": "clear",
        "clarification_question": None,
        "research_plan": {
            "intent": "temporal_trend",
            "subject_terms": ["population"],
            "driver_terms": [],
            "geography_terms": ["Netherlands"],
            "evidence_preferences": [],
            "exclusion_terms": [],
        },
        "research_strategy": {k: v for k, v in strategy().items() if k != "adapter"},
    }
    analyzer = ModelAnalyzer(
        "fixture",
        complete_json=lambda *a: {"choices": [{"message": {"content": json.dumps(response)}}]},
    )
    brief = interpret_question("Population of Netherlands 2001–2003", analyzer=analyzer)
    assert brief["data_research"]["adapter"] == "discovered_data_v1"
    assert brief["data_research"]["route"] == "data"


def test_search_uses_observed_parent_not_unobserved_download():
    import json

    from sci_search.data_research.discovery import discover
    from sci_search.mistral_analysis import ModelAnalyzer
    from sci_search.model_provider import PROFILES

    page = "https://stats.example/datasets"
    reply = {
        "output": [
            {"type": "web_search_call", "action": {"sources": [{"url": page}]}},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "candidates": [
                                    {
                                        "url": "https://stats.example/unobserved.csv",
                                        "landing_url": page,
                                        "title": "Data",
                                        "publisher": "Office",
                                        "rationale": "Relevant",
                                    }
                                ]
                            }
                        ),
                    }
                ],
            },
        ]
    }
    trace = discover(
        "Population",
        strategy(),
        analyzer=ModelAnalyzer("fixture", provider=PROFILES["openai"]),
        transport=lambda body: reply,
    )
    assert trace["candidates"][0]["url"] == page
    assert trace["candidates"][0]["reported_download_url"].endswith("unobserved.csv")


def test_html_misclassified_as_workbook_is_blocked_not_crash(tmp_path):
    from sci_search.data_research.workflow import execute

    url = "https://forest-fire.emergency.copernicus.eu/page"
    result = execute(
        "Wildfires",
        strategy(),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                {"url": url, "title": "Page", "publisher": "EFFIS", "rationale": "Possible"}
            ]
        },
        fetch=lambda u: (b"<html>Annual reported fires</html>", "text/html", u),
        complete=lambda *a: dict(
            adapter="effis",
            download_link_index=-1,
            reason="Possible",
            definition_quote="Annual reported fires",
            license_note="Unknown",
            covered_measurements=["population"],
        ),
    )
    assert result["status"] == "blocked"
    assert "not an XLSX" in result["assessments"][0]["reason"]


def test_csv_comment_metadata_and_multiline_rows_keep_physical_line_reference():
    body = b'# Population in people\n# Annual national counts\nYear,Country,Population\n\n2001,"Nether\nlands",10\n2002,Netherlands,11\n'
    value = {**mapping(), "entities": ["Nether\nlands", "Netherlands"]}
    result = analyse_csv(body, value, strategy())
    assert result["series"][0]["annual"][0]["source_row"] == 5
    assert result["series"][1]["annual"][1]["source_row"] == 7


def test_all_missing_values_cannot_count_as_calculated_observations():
    with pytest.raises(ValueError, match="No numeric observations"):
        analyse_csv(b"Year,Country,Population\n2001,Netherlands,:", mapping(), strategy())


def test_one_csv_can_answer_multiple_measurements(tmp_path):
    from sci_search.data_research.workflow import execute

    page = b'<html>Population in people and area in km2<a href="/data.csv">data</a></html>'
    data = b"Year,Country,Population,Area\n2001,Netherlands,10,20\n2002,Netherlands,11,20\n2003,Netherlands,12,20"
    answers = iter(
        [
            dict(
                adapter="csv",
                download_link_index=0,
                reason="Measures",
                definition_quote="Population in people and area in km2",
                license_note="Unknown",
                covered_measurements=["population", "area"],
            ),
            dict(
                suitable=True,
                reason="Population",
                measurement="population",
                unit_evidence="people",
                mapping=mapping(),
            ),
            dict(
                suitable=True,
                reason="Area",
                measurement="area",
                unit_evidence="km2",
                mapping={
                    **mapping(),
                    "value_column": "Area",
                    "unit": "km2",
                    "output_unit": "km2",
                    "label": "Area",
                },
            ),
        ]
    )
    result = execute(
        "Population and area",
        {**strategy(), "measurements": ["population", "area"]},
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(
                    url="https://example.org",
                    title="Dataset",
                    publisher="Office",
                    rationale="Suitable",
                )
            ]
        },
        fetch=lambda u: (
            (page, "text/html", u) if u == "https://example.org" else (data, "text/csv", u)
        ),
        complete=with_positive_meaning_review(lambda *a: next(answers)),
    )
    assert len(result["analyses"][0]["components"]) == 2
    assert result["uncovered_measurements"] == []


def test_broader_europe_does_not_become_eu_from_negated_description(tmp_path):
    from pathlib import Path

    from sci_search.data_research.workflow import execute

    scope = {
        **strategy(),
        "geography": "Europe, not only the European Union; coverage gaps shown",
        "country_scope": "europe",
        "measurements": ["fire counts", "burned area"],
    }
    assert (
        validate_strategy({k: v for k, v in scope.items() if k != "country_scope"})["country_scope"]
        == "europe"
    )
    body = (Path(__file__).parent / "fixtures/data_research/effis_report_2024.xlsx").read_bytes()
    page = b'<html>Country totals: fires and burned area<a href="/report.xlsx">Data</a></html>'
    result = execute(
        "European wildfires",
        scope,
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(
                    url="https://forest-fire.emergency.copernicus.eu/page",
                    title="Dataset",
                    publisher="EFFIS",
                    rationale="Official",
                )
            ]
        },
        fetch=lambda u: (
            (page, "text/html", u)
            if u.endswith("/page")
            else (
                body,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "https://data.effis.emergency.copernicus.eu/report.xlsx",
            )
        ),
        complete=with_positive_meaning_review(lambda *a: dict(
            adapter="effis",
            download_link_index=0,
            reason="Country totals",
            definition_quote="Country totals: fires and burned area",
            license_note="Official terms",
            covered_measurements=scope["measurements"],
        )),
    )
    assert len(result["analyses"][0]["requested_countries"]) == 46


def test_csv_units_can_be_documented_in_download_comments(tmp_path):
    from sci_search.data_research.workflow import execute

    page = b'<html>Annual population<a href="/population.csv">CSV</a></html>'
    data = b"# Unit: people\nYear,Country,Population\n2001,Netherlands,10\n2002,Netherlands,11\n2003,Netherlands,12"
    responses = iter(
        [
            dict(
                adapter="csv",
                download_link_index=0,
                reason="Annual data",
                definition_quote="Annual population",
                license_note="Unknown",
                covered_measurements=["population"],
            ),
            dict(
                suitable=True,
                reason="Documented units",
                unit_evidence="Unit: people",
                measurement="population",
                mapping=mapping(),
            ),
        ]
    )
    result = execute(
        "Population",
        strategy(),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(
                    url="https://example.org",
                    title="Population",
                    publisher="Office",
                    rationale="Annual",
                )
            ]
        },
        fetch=lambda u: (
            (page, "text/html", u) if u == "https://example.org" else (data, "text/csv", u)
        ),
        complete=with_positive_meaning_review(lambda *a: next(responses)),
    )
    assert result["analyses"][0]["series"][0]["absolute_change"] == 2


def test_bad_csv_source_does_not_abort_other_candidates(tmp_path):
    import csv

    from sci_search.data_research.workflow import execute

    def broken(url):
        raise csv.Error("Malformed CSV")

    result = execute(
        "Population",
        strategy(),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(
                    url="https://example.org",
                    title="Broken data",
                    publisher="Office",
                    rationale="Annual",
                )
            ]
        },
        fetch=broken,
    )
    assert result["status"] == "blocked"
    assert result["assessments"][0]["reason"] == "Malformed CSV"


def test_offline_replay_skips_blocked_source_provisional_analysis(tmp_path):
    import io
    import json
    import subprocess
    import sys
    import zipfile

    from sci_search.data_research.reporting import export

    source = tmp_path / "source-1"
    source.mkdir()
    (source / "analysis.json").write_text(json.dumps({"annual": []}))
    (source / "assessment.json").write_text(
        json.dumps({"decision": "blocked", "reason": "No panel"})
    )
    _, _, body = export({"kind": "discovered", "analyses": []}, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)
