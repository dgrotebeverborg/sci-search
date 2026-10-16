"""Regressions for documented units, stable measurement labels and input-only review."""

import json

import pytest

from sci_search.data_research import semantics
from sci_search.data_research.calculations import factor
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv
from tests.data_meaning_fixtures import positive_review


@pytest.mark.parametrize(
    "source,target,expected",
    [
        ("0.1 degrees Celsius", "°C", 0.1),
        ("tonnes per hectare", "t/ha", 1),
        ("kg/ha", "tonnes per hectare", 0.001),
        ("thousand hectares", "ha", 1000),
        ("thousand tonnes", "tonnes", 1000),
        ("million passenger-kilometres", "passenger-kilometres", 1e6),
    ],
)
def test_explicit_compatible_units_convert(source, target, expected):
    assert factor(source, target) == expected


@pytest.mark.parametrize(
    "source,target", [("1 000 kg", "t/ha"), ("RT", "per million inhabitants"), ("K", "°C")]
)
def test_units_do_not_invent_denominators_or_offset_conversions(source, target):
    with pytest.raises(ValueError):
        factor(source, target)


def crop_selection(label):
    return {
        "reader": "statistical_tsv",
        "filters": [
            {"dimension": "freq", "values": ["A"]},
            {"dimension": "strucpro", "values": ["YIELD"]},
            {"dimension": "geo", "values": ["NL"]},
        ],
        "series_dimensions": ["geo"],
        "code_labels": {"strucpro": {"YIELD": label}},
        "reason": "Published yield",
    }


def test_unit_declared_in_measure_label_survives_normalization_and_replay():
    body = b"freq,strucpro,geo\\TIME_PERIOD\t2020\nA,YIELD,NL\t42.1\n"
    selection = crop_selection("Yield in EU standard humidity - tonnes per hectare")
    table, prep = prepare_table(body, selection)
    assert read_csv(table)[1][0]["Unit"] == "tonnes per hectare"
    assert prep["row_provenance"]["2"]["unit"] == "tonnes per hectare"
    assert prepare_table(body, prep["selection"])[0] == table


@pytest.mark.parametrize(
    "label", ["Yield", "Estimated tonnes per hectare", "Yield - mystery units"]
)
def test_undocumented_units_are_not_inferred_from_a_measure_code(label):
    body = b"freq,strucpro,geo\\TIME_PERIOD\t2020\nA,YIELD,NL\t42.1\n"
    table, _ = prepare_table(body, crop_selection(label))
    assert read_csv(table)[1][0]["Unit"] == ""


def test_raw_review_does_not_receive_unperformed_cross_checks_as_its_task():
    request = {
        "measurements": ["yield", "production", "area"],
        "countries": ["NLD"],
        "requirements": [
            {"measurement": "yield", "definition": "Published potato yield"},
            {"measurement": "area", "definition": "Harvested area"},
        ],
        "calculations": [],
        "unresolved_calculations": ["Compare production / area with yield"],
    }
    seen = []

    def model(prompt, schema):
        context = json.loads(prompt.split("\n", 1)[1])
        seen.append(context)
        assert context["scope"]["measurements"] == ["yield"]
        assert "calculations" not in context["scope"]
        assert "unresolved_calculations" not in context["scope"]
        assert "production / area" not in context.get("question", "")
        return positive_review(prompt)

    result = semantics.assess(
        question="Compare production / area with yield",
        scope=request,
        analysis={"series": [{"label": "yield", "annual": []}]},
        documents={"metadata": "Published potato yield in tonnes per hectare."},
        complete=model,
    )
    assert result["accepted"]
    assert seen[0]["scope"]["requirements"] == request["requirements"][:1]
    assert request["unresolved_calculations"]


def test_documented_station_identity_and_requested_label_survive_execution(tmp_path, monkeypatch):
    import subprocess
    import sys

    from sci_search.data_research.workflow import execute
    from tests.data_meaning_fixtures import with_positive_meaning_review

    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")
    scope = {
        "route": "data",
        "rationale": "Station observations",
        "measurements": ["annual temperature"],
        "geography": "De Bilt",
        "start_year": 2020,
        "end_year": 2021,
        "requirements": [
            {
                "measurement": "annual temperature",
                "entities": ["De Bilt"],
                "measure_type": "interval",
            }
        ],
    }
    url = "https://climate.example/station.csv"
    body = b"# Station 260 = De Bilt; annual temperature in 0.1 degrees Celsius\nYear,Station,T\n2020,260,104\n2021,260,101\n"
    replies = iter(
        [
            {
                "adapter": "csv",
                "download_link_index": -1,
                "reason": "Station data",
                "definition_quote": "annual temperature",
                "license_note": "Not stated",
                "covered_measurements": ["annual temperature"],
            },
            {
                "suitable": True,
                "reason": "Published annual observations",
                "measurement": "annual temperature",
                "unit_evidence": "0.1 degrees Celsius",
                "entity_identities": [
                    {
                        "source_entity": "260",
                        "geography": "De Bilt",
                        "evidence": "Station 260 = De Bilt",
                    }
                ],
                "mapping": {
                    "year_column": "Year",
                    "value_column": "T",
                    "entity_column": "Station",
                    "entities": ["260"],
                    "unit": "0.1 degrees Celsius",
                    "output_unit": "°C",
                    "label": "De Bilt annual temperature",
                    "filters": [],
                    "missing_values": [],
                    "decimal_separator": ".",
                },
            },
        ]
    )
    result = execute(
        "Annual temperature at De Bilt",
        scope,
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                {
                    "url": url,
                    "title": "Station data",
                    "publisher": "Climate office",
                    "rationale": "Official",
                }
            ]
        },
        fetch=lambda u: (body, "text/csv", u),
        complete=with_positive_meaning_review(lambda *a: next(replies)),
    )
    assert result["coverage"]["complete_measurements"] == ["annual temperature"]
    s = result["analyses"][0]["series"][0]
    assert s["label"] == "annual temperature" and s["entity"] == "260"
    assert s["identity"]["geography"] == "De Bilt"
    assert [o["value"] for o in s["annual"]] == pytest.approx([10.4, 10.1])
    subprocess.run(
        [sys.executable, str(tmp_path / "reproduce.py")], check=True, capture_output=True
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"source_entity": "260", "geography": "Potsdam", "evidence": "Station 260 = De Bilt"},
        {"source_entity": "26", "geography": "De Bilt", "evidence": "Station 260 = De Bilt"},
        {
            "source_entity": "260",
            "geography": "De Bilt",
            "evidence": "Station 260 = De Bilt (invented)",
        },
    ],
)
def test_station_identity_cannot_be_invented_or_borrowed_from_another_code(entry):
    with pytest.raises(ValueError, match="citation"):
        semantics.bind_mapping(
            {"entities": ["260", "26"]}, "temperature", [entry], ["Station 260 = De Bilt"]
        )


def test_statistical_unit_dimension_takes_priority_over_measure_label():
    body = b"freq,strucpro,unit,geo\\TIME_PERIOD\t2020\nA,YIELD,KG_HA,NL\t42100\n"
    plan = crop_selection("Yield - tonnes per hectare")
    plan["filters"].append({"dimension": "unit", "values": ["KG_HA"]})
    table, _ = prepare_table(body, plan)
    assert read_csv(table)[1][0]["Unit"] == "KG_HA"


@pytest.mark.parametrize(
    "source,target", [("mW", "MW"), ("mWh", "MWh"), ("mg", "Mg"), ("T", "kg"), ("mWH", "MWh")]
)
def test_case_sensitive_unit_prefixes_are_never_identity_conversions(source, target):
    with pytest.raises(ValueError):
        factor(source, target)


def test_original_question_qualifiers_remain_available_to_the_input_reviewer():
    question = "Annual household electricity excluding autoproducers"

    def model(prompt, schema):
        context = json.loads(prompt.split("\n", 1)[1])
        assert context["research_question"] == question
        return positive_review(prompt)

    semantics.assess(
        question=question,
        scope={"measurements": ["electricity"]},
        analysis={"series": [{"label": "electricity", "annual": []}]},
        documents={"metadata": "Household electricity excluding autoproducers"},
        complete=model,
    )
