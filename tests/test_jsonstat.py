import json

import pytest

from sci_search.data_research.jsonstat import prepare_jsonstat
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv


def dataset(time_codes=("2020", "2021"), values=(1.5, None, 2.5, 3.0), units=None):
    return json.dumps(
        {
            "class": "dataset",
            "version": "2.0",
            "id": ["Region", "ContentsCode", "Tid"],
            "size": [2, 1, len(time_codes)],
            "role": {"time": ["Tid"], "metric": ["ContentsCode"]},
            "dimension": {
                "Region": {
                    "label": "region",
                    "category": {
                        "index": {"SE1": 0, "SE2": 1},
                        "label": {"SE1": "North", "SE2": "South"},
                    },
                },
                "ContentsCode": {
                    "label": "observations",
                    "category": {
                        "index": {"EL01": 0},
                        "label": {"EL01": "Electricity use"},
                        "unit": units or {"EL01": {"base": "GWh", "decimals": 1}},
                    },
                },
                "Tid": {
                    "label": "year",
                    "category": {"index": {c: i for i, c in enumerate(time_codes)}},
                },
            },
            "value": list(values),
            "status": {"3": "p"},
        }
    ).encode()


SELECTION = {"reader": "jsonstat2", "series_dimensions": ["Region"], "reason": "Regions"}


def test_reads_annual_values_units_status_and_missing():
    table, prep = prepare_table(dataset(), SELECTION)
    headers, rows = read_csv(table)
    assert headers == ["Year", "Series", "Region", "ContentsCode", "Value", "Unit", "Status"]
    assert [(r["Year"], r["Series"], r["Value"], r["Unit"], r["Status"]) for r in rows] == [
        ("2020", "Region=SE1 (North)", "1.5", "GWh", ""),
        ("2021", "Region=SE1 (North)", ":", "GWh", ""),
        ("2020", "Region=SE2 (South)", "2.5", "GWh", ""),
        ("2021", "Region=SE2 (South)", "3.0", "GWh", "p"),
    ]
    assert prep["format"] == "jsonstat2_v1"
    assert prep["row_provenance"]["2"]["source_reference"] == "index:0; period:2020"


def test_rejects_non_annual_time():
    with pytest.raises(ValueError, match="no aggregation was performed"):
        prepare_jsonstat(dataset(time_codes=("2020M01", "2020M02")), SELECTION)


def test_fixed_dimensions_must_have_one_code_and_unit_is_required():
    with pytest.raises(ValueError, match="one code"):
        prepare_jsonstat(dataset(), {**SELECTION, "series_dimensions": ["ContentsCode"]})
    with pytest.raises(ValueError, match="unit"):
        prepare_jsonstat(dataset(units={"EL01": {}}), SELECTION)
