"""A linked output must implement the requested mathematical meaning."""

import pytest

from sci_search.data_research.calculation_contract import validate_requests
from tests.test_data_calculations import plan


def request(kind, ids=None, reason=""):
    return {
        "description": "Requested numerical comparison",
        "kind": kind,
        "calculation_ids": ["result"] if ids is None else ids,
        "unresolved_reason": reason,
    }


def test_cross_series_gap_cannot_be_certified_by_year_on_year_subtraction():
    calculation = {**plan(), "operation": "difference", "base_year": None}
    with pytest.raises(ValueError, match="meaning"):
        validate_requests([request("cross_series_difference")], [calculation])


@pytest.mark.parametrize(
    ("kind", "operation", "year"),
    [
        ("year_on_year_difference", "difference", None),
        ("baseline_difference", "difference", 2000),
        ("year_on_year_percentage_points", "percentage_point_change", None),
        ("baseline_percentage_points", "percentage_point_change", 2000),
        ("index", "index", 2000),
    ],
)
def test_matching_mathematical_meaning_is_executable(kind, operation, year):
    calculation = {**plan(), "operation": operation, "base_year": year}
    assert validate_requests([request(kind)], [calculation]) == []


@pytest.mark.parametrize(
    ("kind", "operation", "year"),
    [
        ("year_on_year_difference", "difference", 2000),
        ("baseline_difference", "difference", None),
        ("year_on_year_percentage_points", "difference", None),
        ("ratio", "share", None),
        ("reference_mean_anomaly", "difference", 2000),
    ],
)
def test_different_calculation_cannot_satisfy_requested_meaning(kind, operation, year):
    calculation = {**plan(), "operation": operation, "base_year": year}
    with pytest.raises(ValueError, match="meaning"):
        validate_requests([request(kind)], [calculation])


def test_unimplemented_meaning_is_explicitly_preserved_as_unresolved():
    result = validate_requests(
        [request("cross_series_difference", [], "Cross-series subtraction is unsupported")], []
    )
    assert result == ["Requested numerical comparison: Cross-series subtraction is unsupported"]


def test_fresh_model_strategy_cannot_use_legacy_untyped_inventory():
    from sci_search.data_research.strategy import validate_strategy
    from tests.test_data_calculations import scope

    calculation = {**plan(), "operation": "difference", "base_year": None}
    item = request("cross_series_difference")
    item.pop("kind")
    value = {**scope([calculation]), "calculation_requests": [item]}
    with pytest.raises(ValueError, match="meaning"):
        validate_strategy(value, require_calculation_intent=True)
    # Stored plans remain readable; this is not a fresh interpretation.
    assert validate_strategy(value)["calculations"] == [calculation]
