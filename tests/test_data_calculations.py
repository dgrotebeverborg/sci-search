"""Hand-calculated expectations for requested numerical outputs."""

import copy

import pytest

from sci_search.data_research import strategy


def plan(operation="index", **changes):
    return dict(
        id="result",
        label="Requested result",
        operation=operation,
        input="price",
        reference=None,
        base_year=2000,
        target_unit=None,
        **changes,
    )


def scope(calculations):
    return dict(
        route="data",
        rationale="Requested arithmetic",
        geography="Netherlands",
        countries=["NLD"],
        measurements=["price", "CPI", "hydro", "total"],
        start_year=2000,
        end_year=2002,
        calculations=calculations,
    )


def series(values, unit="euro", measure_type="ratio"):
    return dict(
        label="price",
        entity="Netherlands",
        unit=unit,
        measure_type=measure_type,
        annual=[
            dict(year=2000 + i, value=v, source_reference=f"row:{i + 2}")
            for i, v in enumerate(values)
        ],
    )


def test_calculation_contract_survives_strategy_validation():
    requested = [plan()]
    assert strategy.validate_strategy(scope(requested)).get("calculations") == requested


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "eval"},
        {"input": "unrequested"},
        {"base_year": True},
        {"operation": "share", "reference": None, "base_year": None},
        {"operation": "convert", "base_year": None, "target_unit": None},
    ],
)
def test_invalid_calculation_cannot_silently_disappear(change):
    item = {**plan(), **change}
    with pytest.raises(ValueError):
        strategy.validate_strategy(scope([item]))


def test_legacy_scope_does_not_claim_calculations_were_requested():
    old = scope([])
    old.pop("calculations")
    assert "calculations" not in strategy.validate_strategy(old)


def calculate(item, source, reference=None):
    from sci_search.data_research.calculations import calculate

    before = copy.deepcopy((source, reference))
    result = calculate(item, source, reference, years=[2000, 2001, 2002])
    assert (source, reference) == before
    return result


def test_index_uses_requested_baseline_without_overwriting_observations():
    result = calculate(plan(), series([200, 220, 300]))
    assert [r["value"] for r in result["annual"]] == [100, 110, 150]
    assert result["status"] == "complete"
    assert result["unit"] == "2000 = 100"


def test_missing_baseline_does_not_rebase_to_first_available_year():
    result = calculate(plan(), series([None, 220, 300]))
    assert result["status"] == "blocked"
    assert all(r["value"] is None for r in result["annual"])
    assert "2000" in result["reason"]


def test_real_index_uses_both_series_at_base_and_current_year():
    result = calculate(
        {**plan(), "operation": "real_index", "reference": "CPI"},
        series([200, 220, 300]),
        series([80, 88, 100], "2015 = 100", "index"),
    )
    assert [r["value"] for r in result["annual"]] == pytest.approx([100, 100, 120])


def test_deflated_amounts_keep_the_monetary_scale():
    result = calculate(
        {**plan(), "operation": "deflate", "reference": "CPI"},
        series([200, 220, 300]),
        series([80, 88, 100], "2015 = 100", "index"),
    )
    assert [r["value"] for r in result["annual"]] == [200, 200, 240]
    assert "2000" in result["unit"] and "euro" in result["unit"]


def test_energy_conversion_is_a_known_factor_not_model_arithmetic():
    result = calculate(
        {**plan(), "operation": "convert", "base_year": None, "target_unit": "TWh"},
        series([1000, 2500, None], "GWH"),
    )
    assert [r["value"] for r in result["annual"]] == [1, 2.5, None]
    assert result["status"] == "partial"


def test_share_converts_compatible_units_and_keeps_zero_denominator_missing():
    result = calculate(
        {**plan(), "operation": "share", "base_year": None, "reference": "total"},
        series([1, 2, 0], "TWh"),
        series([2000, 4000, 0], "GWH"),
    )
    assert [r["value"] for r in result["annual"]] == [50, 50, None]
    assert result["status"] == "partial"
    assert "denominator" in result["annual"][2]["reason"]


@pytest.mark.parametrize("kind", ["index", "real_index"])
def test_break_in_series_blocks_cross_year_indices(kind):
    source = series([200, 220, 300])
    source["annual"][1]["source_status"] = "b"
    item = {**plan(), "operation": kind, "reference": "CPI" if kind == "real_index" else None}
    result = calculate(
        item, source, series([80, 88, 100], "2015 = 100", "index") if kind == "real_index" else None
    )
    assert result["status"] == "blocked"


@pytest.mark.parametrize("values", [[200, float("inf"), 300], [200, True, 300]])
def test_invalid_numeric_input_is_not_published(values):
    result = calculate(plan(), series(values))
    assert result["annual"][1]["value"] is None
    assert result["status"] == "partial"


def test_duplicate_year_is_ambiguous_not_last_row_wins():
    source = series([200, 220, 300])
    source["annual"].append(dict(year=2001, value=999))
    assert calculate(plan(), source)["status"] == "blocked"


def test_dimensionally_incompatible_share_is_blocked():
    result = calculate(
        {**plan(), "operation": "share", "base_year": None, "reference": "total"},
        series([1, 2, 3], "TWh"),
        series([2, 4, 6], "people"),
    )
    assert result["status"] == "blocked"


@pytest.mark.parametrize("unit", ["terawatt-hours", "terawatt hours", "Terawatt-hour", "TWh"])
def test_spelled_energy_units_share_the_same_explicit_si_conversion(unit):
    from sci_search.data_research.calculations import calculate

    item = {**plan(), "operation": "convert", "base_year": None, "target_unit": "GWh"}
    output = calculate(item, series([1, 2, 3], unit), years=[2000, 2001, 2002])
    assert [r["value"] for r in output["annual"]] == [1000, 2000, 3000]


def test_real_index_accepts_a_documented_nominal_price_index():
    result = calculate(
        {**plan(), "operation": "real_index", "reference": "CPI"},
        series([100, 120, 132], "2015 = 100", "index"),
        series([100, 110, 120], "2015 = 100", "index"),
    )
    assert [r["value"] for r in result["annual"]] == pytest.approx([100, 109.090909, 110])


def test_deflate_still_rejects_nonmonetary_index():
    result = calculate(
        {**plan(), "operation": "deflate", "reference": "CPI"},
        series([100, 120, 132], "2015 = 100", "index"),
        series([100, 110, 120], "2015 = 100", "index"),
    )
    assert result["status"] == "blocked"


def test_conversion_uses_source_indicator_substance_without_changing_observations():
    source = series([1, 2, 3], "tonnes per person")
    source["identity"] = {
        "dimensions": {"indicator": "CO₂ emissions per capita (tonnes per person)"}
    }
    result = calculate(
        {**plan(), "operation": "convert", "target_unit": "kg of CO2 per person"}, source
    )
    assert [r["value"] for r in result["annual"]] == [1000, 2000, 3000]


@pytest.mark.parametrize(
    "indicator", ["", "Methane emissions per capita", "CO2-equivalent emissions per capita"]
)
def test_target_cannot_supply_missing_or_conflicting_substance(indicator):
    source = series([1, 2, 3], "tonnes per person")
    source["label"] = "CO2 emissions requested by user"
    source["identity"] = {"dimensions": {"indicator": indicator}}
    result = calculate(
        {**plan(), "operation": "convert", "target_unit": "tonnes of CO2 per person"}, source
    )
    assert result["status"] == "blocked"


@pytest.mark.parametrize("left_unit,right_unit", [("tonnes", "kg"), ("tonnes", "tonnes")])
def test_share_rejects_conflicting_source_substances_even_for_bare_units(left_unit, right_unit):
    source = series([1, 2, 3], left_unit)
    source["identity"] = {"dimensions": {"indicator": "Carbon dioxide emissions"}}
    reference = series([1000, 2000, 3000], right_unit)
    reference["identity"] = {"dimensions": {"indicator": "CH4 emissions"}}
    result = calculate({**plan(), "operation": "share", "reference": "total"}, source, reference)
    assert result["status"] == "blocked"
    assert all(row["value"] is None for row in result["annual"])


def test_identical_unknown_unit_single_source_conversion_is_preserved():
    source = series([1, 2, 3], "source-specific units")
    result = calculate(
        {**plan(), "operation": "convert", "target_unit": "source-specific units"}, source
    )
    assert [row["value"] for row in result["annual"]] == [1, 2, 3]


@pytest.mark.parametrize(
    "unit", ["tonnes CO2 per person", "t CO₂/person", "tonnes of carbon dioxide per capita"]
)
def test_explicit_carbon_dioxide_unit_aliases_preserve_substance(unit):
    from sci_search.data_research.calculations import factor

    assert factor("kg of CO2 per person", unit) == 0.001
