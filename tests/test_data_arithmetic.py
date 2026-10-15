import pytest

from sci_search.data_research.tabular import analyse_csv


def calculate(unit, first, last, kind=None):
    scope = {"start_year": 2020, "end_year": 2021, "measurements": ["value"]}
    if kind:
        scope["requirements"] = [{"measurement": "value", "measure_type": kind}]
    return analyse_csv(
        f"Year,Value\n2020,{first}\n2021,{last}\n".encode(),
        {
            "year_column": "Year",
            "value_column": "Value",
            "unit": unit,
            "output_unit": unit,
            "label": "value",
        },
        scope,
    )["series"][0]


@pytest.mark.parametrize("unit", ["°C", "degrees Celsius", "°F"])
def test_temperature_does_not_receive_a_percentage_growth(unit):
    result = calculate(unit, 10, 20)
    assert result["absolute_change"] == 10
    assert result["change_percent"] is None
    assert result["change_note"]


def test_percentages_distinguish_percentage_points_and_relative_change():
    result = calculate("%", 20, 30)
    assert result["absolute_change_unit"] == "percentage points"
    assert result["absolute_change"] == 10
    assert result["change_percent"] == 50


def test_unknown_scale_does_not_assume_a_meaningful_zero():
    assert calculate("arbitrary score", 10, 20)["change_percent"] is None


def test_negative_baseline_does_not_report_conventional_percentage_growth():
    assert calculate("EUR", -10, 10, "ratio")["change_percent"] is None


def test_requested_ratio_cannot_override_a_known_interval_unit():
    assert calculate("°C", 10, 20, "ratio")["change_percent"] is None
