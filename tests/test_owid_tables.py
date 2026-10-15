import json

import pytest

from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv

CSV = "entity,code,year,life_expectancy_0\nGermany,DEU,2000,77.9\nGermany,DEU,2001,78.2\nNetherlands,NLD,2000,78.0\nWorld,OWID_WRL,2000,66.5\n"
METADATA = {
    "columns": {
        "Period life expectancy at birth": {
            "titleShort": "Life expectancy",
            "unit": "years",
            "shortName": "life_expectancy_0",
            "descriptionShort": "Period life expectancy at birth",
        }
    }
}


def envelope(csv_text=CSV, metadata=METADATA):
    return json.dumps({"csv": csv_text, "metadata": metadata}).encode()


SELECTION = {
    "reader": "owid_csv",
    "indicator": "life_expectancy_0",
    "entities": ["Germany", "Netherlands"],
    "reason": "Requested",
}


def test_reads_selected_entities_with_unit():
    table, prep = prepare_table(envelope(), SELECTION)
    headers, rows = read_csv(table)
    assert headers == ["Year", "Series", "Code", "Value", "Unit", "Status"]
    assert [(r["Year"], r["Series"], r["Value"], r["Unit"]) for r in rows] == [
        ("2000", "Germany", "77.9", "years"),
        ("2001", "Germany", "78.2", "years"),
        ("2000", "Netherlands", "78.0", "years"),
    ]
    assert prep["format"] == "owid_csv_v1"
    assert prep["row_provenance"]["2"]["source_reference"] == "csv-line:2"


def test_unknown_entity_or_indicator_or_missing_unit_is_rejected():
    with pytest.raises(ValueError, match="entities"):
        prepare_table(envelope(), {**SELECTION, "entities": ["Atlantis"]})
    with pytest.raises(ValueError, match="indicator"):
        prepare_table(envelope(), {**SELECTION, "indicator": "gdp"})
    no_unit = {
        "columns": {"Display": {"titleShort": "x", "unit": "", "shortName": "life_expectancy_0"}}
    }
    with pytest.raises(ValueError, match="unit"):
        prepare_table(envelope(metadata=no_unit), SELECTION)


def test_missing_stays_missing_and_non_annual_year_is_rejected():
    csv_text = CSV.replace("78.2", "")
    _, rows = read_csv(prepare_table(envelope(csv_text), SELECTION)[0])
    assert rows[1]["Value"] == ":"
    daily = CSV.replace("2001", "2001-02-03")
    with pytest.raises(ValueError, match="dataset is daily; no aggregation was performed"):
        prepare_table(envelope(daily), SELECTION)


def test_duplicate_year_and_oversized_selection_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        prepare_table(envelope(CSV + "Germany,DEU,2000,1.0\n"), SELECTION)
    with pytest.raises(ValueError, match="60"):
        prepare_table(envelope(), {**SELECTION, "entities": [f"E{i}" for i in range(61)]})


def test_reader_accepts_verbatim_metadata_text_and_bom_csv():
    text = json.dumps(METADATA, indent=2)
    body = json.dumps({"csv": "\ufeff" + CSV, "metadata": text}).encode()
    _, rows = read_csv(prepare_table(body, SELECTION)[0])
    assert {r["Series"] for r in rows} == {"Germany", "Netherlands"}
