import pytest

from sci_search.data_research.wildfire import analyse, parse_number, propose


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


def test_numbers_preserve_missingness_and_convert_grouping():
    assert parse_number("12\u00a0345 ") == 12345
    assert parse_number("0") == 0
    assert parse_number("") is None
    with pytest.raises(ValueError):
        parse_number("-4")


def test_fixed_panel_excludes_incomplete_countries_without_zero_filling():
    records = [
        {"country": "ESP", "year": y, "fires": 10, "burned_area_ha": 250} for y in range(2001, 2007)
    ] + [{"country": "PRT", "year": 2001, "fires": 100, "burned_area_ha": 10000}]
    result = analyse(records, countries=["ESP", "PRT"], start=2001, end=2007)
    assert result["panel_countries"] == ["ESP"]
    assert result["annual"][0]["panel_burned_area_km2"] == 2.5
    assert result["annual"][1]["available_burned_area_km2"] == 2.5
    assert result["annual"][1]["requested_total_burned_area_km2"] is None
    assert result["missing_years"] == [2007]
    assert result["annual"][-1]["panel_fires"] is None


def test_duplicate_country_year_is_an_error():
    record = {"country": "ESP", "year": 2001, "fires": 10, "burned_area_ha": 100}
    with pytest.raises(ValueError):
        analyse([record, record], countries=["ESP"], start=2001, end=2002)


def test_only_supported_question_is_routed_and_years_are_not_guessed():
    assert propose(
        "What are the developments in amount of wildfires in Europe in this century in numbers and km2?"
    )
    assert propose("Why do wildfires occur in Europe?") is None
    assert propose("Wildfire counts in Canada since 2001") is None
    assert propose("European wildfire counts between 2010 and 2020")["start_year"] == 2010
    assert propose("European wildfire counts between 2010 and 2020")["end_year"] == 2020


def test_official_workbook_and_offline_package(tmp_path):
    import io
    import json
    import subprocess
    import sys
    import zipfile
    from pathlib import Path

    from sci_search.data_research.wildfire import export, parse_workbook, run

    body = (Path(__file__).parent / "fixtures/data_research/effis_report_2024.xlsx").read_bytes()
    records = parse_workbook(body)
    portugal = next(r for r in records if r["country"] == "PRT" and r["year"] == 1980)
    assert portugal["fires"] == 2349
    assert portugal["source_cells"]["fires"]["cell"] == "B2"
    scope = propose("European wildfire counts and km2 this century")
    scope["end_year"] = 2025
    result = run(
        scope,
        tmp_path / "source",
        fetch=lambda: body,
    )
    assert result["missing_years"] == [2025]
    assert len(result["panel_countries"]) == 22
    assert all(r["requested_total_fires"] is None for r in result["annual"])
    _, _, package = export(result, tmp_path / "source", bundle=True)
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)
    replay = json.loads((tmp_path / "replay/reproduced/analysis.json").read_text())
    assert replay["annual"] == result["annual"]
    assert replay["comparisons"] == result["comparisons"]
    assert replay["source"]["sha256"] == result["source"]["sha256"]


def test_data_route_completes_without_searching_literature(tmp_path, monkeypatch):
    from pathlib import Path

    from sci_search.data_research import wildfire
    from sci_search.question_interpretation import interpret_question
    from sci_search.research_runs import ResearchRunManager

    body = (Path(__file__).parent / "fixtures/data_research/effis_report_2024.xlsx").read_bytes()
    from sci_search.data_research import workflow
    from tests.data_meaning_fixtures import with_positive_meaning_review

    original_run = wildfire.run

    def guarded_run(scope, directory, **kwargs):
        if kwargs.get("execute_script", True):
            raise ValueError("Legacy publication bypassed measurement review")
        return original_run(scope, directory, **kwargs)

    monkeypatch.setattr(wildfire, "run", guarded_run)
    original_execute = workflow.execute

    def execute(question, strategy, directory, **kwargs):
        def model(prompt, schema):
            if "adapter" in schema["properties"]:
                return dict(
                    adapter="effis",
                    download_link_index=-1,
                    reason="Official workbook",
                    definition_quote="",
                    license_note="Unknown",
                    covered_measurements=strategy["measurements"],
                )
            return dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                measurements=[],
                reason="Done",
            )

        return original_execute(
            question,
            strategy,
            directory,
            **kwargs,
            search=lambda *a, **k: {
                "candidates": [dict(url=wildfire.SOURCE_URL, title="EFFIS", publisher="JRC")]
            },
            fetch=lambda url: (
                body,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                url,
            ),
            complete=with_positive_meaning_review(model),
        )

    monkeypatch.setattr(workflow, "execute", execute)

    class NoLiterature:
        name = "not-used"

        def search(self, *args, **kwargs):
            raise AssertionError("Data question reached literature discovery")

    question = "How have European wildfire counts and burned area in km2 changed this century?"
    manager = ResearchRunManager(tmp_path, providers=(NoLiterature(),), openalex_api_key="unused")
    state = manager.run_sync(question, question_brief=interpret_question(question))
    assert state["status"] == "complete", state.get("error")
    assert state["result"]["data_analysis"]["analyses"][0]["panel_countries"]
    assert state["result"]["data_analysis"]["analyses"][0]["semantic_review"]["accepted"]
    assert manager.download_research_package(state["run_id"]).content_type == "application/zip"
    assert "html" in manager.download_literature_review(state["run_id"]).content_type


def test_single_year_and_previous_century_are_not_silently_expanded():
    assert propose("How many wildfires in Europe in 2020, in numbers and km2?")["end_year"] == 2020
    assert propose("European wildfire counts last century") is None
