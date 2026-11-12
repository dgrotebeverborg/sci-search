import io
import zipfile
from pathlib import Path

import pytest

from sci_search.data_research.packages import attach_provenance, prepare_table
from sci_search.data_research.tabular import analyse_csv, read_csv
from tests.data_meaning_fixtures import with_positive_meaning_review


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


FIXTURE = Path(__file__).parent / "fixtures/data_research/cbs_85929NED.zip"


def test_actual_cbs_package_resolves_measures_periods_units_and_missingness():
    body, prep = prepare_table(FIXTURE.read_bytes())
    headers, rows = read_csv(body)
    discharge = next(
        r
        for r in rows
        if r["Measure"] == "Batterijen; bruto productie"
        and r["GrootteklasseInOpslagcapaciteit"] == "Totaal alle grootteklassen batterijen"
        and r["Year"] == "2024"
    )
    assert discharge["Value"] == "182263"
    assert discharge["Unit"] == "1000kWh"
    assert discharge["Period status"] == "Voorlopig"
    assert prep["format"] == "cbs_csv_zip_v1"
    assert prep["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert any(r["Value"] == "" and r["Value attribute"] == "Impossible" for r in rows)
    assert "opslagcapaciteit > 1 MWh" in prep["metadata"]


def _with_replacements(entry, replacements):
    output = io.BytesIO()
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(output, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == entry:
                text = data.decode("utf-8-sig")
                for old, new in replacements.items():
                    assert old in text
                    text = text.replace(old, new)
                data = text.encode()
            target.writestr(name, data)
    return output.getvalue()


def _with_measure_titles(replacements):
    return _with_replacements("MeasureCodes.csv", replacements)


def test_cbs_measures_sharing_a_title_are_distinguished_by_unit():
    # CBS repeats measure titles across groups, e.g. production in kWh and as % of use.
    body, _ = prepare_table(
        _with_measure_titles({"Batterijen; vermogen": "Batterijen; aantal systemen"})
    )
    _, rows = read_csv(body)
    units = {r["Unit"] for r in rows if r["Measure"] == "Batterijen; aantal systemen"}
    assert units == {"aantal", "MW"}


def test_cbs_measures_sharing_title_and_unit_remain_ambiguous():
    package = _with_measure_titles({"Batterijen; eigen verbruik": "Batterijen; bruto productie"})
    with pytest.raises(ValueError, match="ambiguous"):
        prepare_table(package)


def test_cbs_period_labels_with_surrounding_whitespace_are_annual():
    package = _with_replacements(
        "PeriodenCodes.csv", {"JJ00;0;Perioden;2;2023;": "JJ00;0;Perioden;2;2023 ;"}
    )
    body, _ = prepare_table(package)
    _, rows = read_csv(body)
    assert "2023" in {r["Year"] for r in rows}


def test_cbs_series_keeps_original_observation_reference_and_unit_contract():
    body, prep = prepare_table(FIXTURE.read_bytes())
    mapping = {
        "year_column": "Year",
        "entity_column": "GrootteklasseInOpslagcapaciteit",
        "entities": ["Totaal alle grootteklassen batterijen"],
        "value_column": "Value",
        "unit": "1000kWh",
        "output_unit": "1000kWh",
        "label": "Gross electricity discharged",
        "filters": {"Measure": "Batterijen; bruto productie"},
        "missing_values": [""],
        "decimal_separator": ".",
    }
    result = analyse_csv(body, mapping, {"start_year": 2022, "end_year": 2024})
    attach_provenance(result, prep)
    series = result["series"][0]
    assert [r["value"] for r in series["annual"]] == [73170, 87794, 182263]
    assert series["annual"][-1]["source_reference"] == "Observations.csv:17"
    assert series["annual"][-1]["source_status"] == "Voorlopig"
    with pytest.raises(ValueError, match="unit"):
        attach_provenance(
            analyse_csv(body, {**mapping, "unit": "MWh", "output_unit": "MWh"}, {}), prep
        )


def test_zip_selection_is_safe_and_does_not_guess_between_tables():
    def archive(files):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for k, v in files.items():
                z.writestr(k, v)
        return out.getvalue()

    with pytest.raises(ValueError, match="path"):
        prepare_table(archive({"../data.csv": "Year,Value\n2020,1"}))
    with pytest.raises(ValueError, match="multiple"):
        prepare_table(archive({"a.csv": "Year,Value\n2020,1", "b.csv": "Year,Value\n2020,2"}))
    body, meta = prepare_table(archive({"data.csv": "Year,Value\n2020,1"}))
    assert body.startswith(b"Year")
    assert meta["entry"] == "data.csv"


@pytest.mark.parametrize("download_index", [0, -1, 1])
def test_cbs_workflow_and_offline_package(tmp_path, download_index):
    import subprocess
    import sys

    from sci_search.data_research.reporting import export
    from sci_search.data_research.workflow import execute

    scope = {
        "adapter": "discovered_data_v1",
        "route": "data",
        "rationale": "Trends in use",
        "geography": "Netherlands",
        "country_scope": "other",
        "measurements": ["electricity storage use"],
        "start_year": None,
        "end_year": None,
    }
    mapping = {
        "year_column": "Year",
        "entity_column": "GrootteklasseInOpslagcapaciteit",
        "entities": ["Totaal alle grootteklassen batterijen"],
        "value_column": "Value",
        "unit": "1000kWh",
        "output_unit": "1000kWh",
        "label": "Gross discharged electricity",
        "filters": [{"column": "Measure", "value": "Batterijen; bruto productie"}],
        "missing_values": [""],
        "decimal_separator": ".",
    }
    responses = iter(
        [
            {
                "adapter": "csv",
                "download_link_index": download_index,
                "reason": "Partial: large batteries only",
                "definition_quote": "Large battery discharge",
                "license_note": "Unknown",
                "covered_measurements": ["electricity storage use"],
            },
            {
                "suitable": True,
                "measurement": "electricity storage use",
                "reason": "Actual discharge; only >1 MWh batteries, provisional 2022–2024.",
                "unit_evidence": "1000kWh",
                "mapping": mapping,
            },
        ]
    )
    fetched = []

    def fetch(url):
        fetched.append(url)
        if url.endswith("table"):
            return (
                b'<html>Large battery discharge<a href="/data.zip">CSV</a><a href="https://opendata.cbs.nl/ODataApi/OData/85929NED">API</a></html>',
                "text/html",
                url,
            )
        return FIXTURE.read_bytes(), "application/octet-stream", url

    result = execute(
        "Trend in Dutch electricity storage",
        scope,
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                {
                    "url": "https://example.org/table",
                    "title": "CBS",
                    "publisher": "CBS",
                    "rationale": "Direct",
                }
            ]
        },
        fetch=fetch,
        complete=with_positive_meaning_review(lambda *a: next(responses)),
    )
    if download_index == 1:
        assert fetched[-1] == "https://datasets.cbs.nl/CSV/CBS/nl/85929NED"
    assert result["analyses"], result["assessments"]
    analysis = result["analyses"][0]
    assert analysis["source"]["artifact"] == "source.zip"
    assert analysis["series"][0]["annual"][-1]["value"] == 182263
    assert any(">1 MWh" in note for note in analysis["limitations"])
    _, _, body = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert "wildfire.py" not in z.namelist()
        assert "report.html" in z.namelist()
        assert "Observations.csv:17" in z.read("analysed-observations.csv").decode()
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)


def test_discovery_recovers_using_only_observed_source_indices():
    import json

    from sci_search.data_research.discovery import discover
    from sci_search.mistral_analysis import ModelAnalyzer
    from sci_search.model_provider import PROFILES

    observed = "https://data.example/dataset/actual-slug"
    draft = "https://data.example/dataset/guessed-id"
    reply = {
        "output": [
            {"type": "web_search_call", "action": {"sources": [{"url": observed}]}},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "candidates": [
                                    {
                                        "title": "Dataset",
                                        "url": draft,
                                        "landing_url": draft,
                                        "publisher": "Agency",
                                        "rationale": "Useful",
                                    }
                                ]
                            }
                        ),
                    }
                ],
            },
        ]
    }
    analyzer = ModelAnalyzer(
        "fixture",
        provider=PROFILES["openai"],
        complete_json=lambda *a: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "sources": [
                                    {
                                        "index": 0,
                                        "title": "Dataset",
                                        "publisher": "Agency",
                                        "rationale": "Relevant observed catalogue page",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        },
    )
    trace = discover("Storage", {}, analyzer=analyzer, transport=lambda body: reply)
    assert trace["candidates"][0]["url"] == observed
    assert trace["rejected"][0]["url"] == draft


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Bruto opbrengst per ha", "1 000 kg per hectare"),
        ("Gross yield per hectare", "1 000 kg per hectare"),
        ("Totale bruto opbrengst", "1 000 kg"),
    ],
)
def test_cbs_yield_unit_uses_selected_measure_title_and_retains_evidence(title, expected):
    import csv

    tables = {
        "Properties.csv": [
            {"Title": "Crop production", "Description": "Yield per hectare and total production"}
        ],
        "Dimensions.csv": [
            {"Identifier": "Perioden", "Kind": "TimeDimension", "CodesUrl": "PeriodenCodes.csv"}
        ],
        "PeriodenCodes.csv": [{"Identifier": "2020JJ00", "Title": "2020"}],
        "MeasureCodes.csv": [
            {
                "Identifier": "M1",
                "Title": title,
                "Unit": "1 000 kg",
                "Description": "Yield per hectare and total production",
            }
        ],
        "Observations.csv": [
            {
                "Measure": "M1",
                "Perioden": "2020JJ00",
                "Value": "42.1",
                "StringValue": "",
                "ValueAttribute": "",
            }
        ],
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, rows in tables.items():
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(name, output.getvalue())
    # Re-executing a saved pre-normalization plan must retain its original unit/filter.
    legacy, legacy_prep = prepare_table(stream.getvalue(), cbs_units_version=1)
    assert read_csv(legacy)[1][0]["Unit"] == "1 000 kg"
    assert "source_unit" not in legacy_prep["row_provenance"]["2"]
    body, prep = prepare_table(stream.getvalue())
    assert read_csv(body)[1][0]["Unit"] == expected
    origin = prep["row_provenance"]["2"]
    assert origin["unit"] == expected
    if expected != "1 000 kg":
        assert origin["source_unit"] == "1 000 kg"
        assert origin["unit_evidence"] == {"field": "MeasureCodes.Title", "value": title}
    assert read_csv(prepare_table(stream.getvalue())[0])[1][0]["Value"] == "42.1"
