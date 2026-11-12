"""Unsupported numerical requests must survive interpretation and stay incomplete."""

import json

import pytest

from sci_search.data_research import derived_artifacts, derived_outputs, strategy
from tests.test_data_calculations import plan, scope
from tests.test_data_derived_outputs import analysis

GAP = "Check potato production divided by harvested area against published yield."


def test_unsupported_output_survives_strategy_validation():
    request = {**scope([]), "unresolved_calculations": [GAP]}
    assert strategy.validate_strategy(request)["unresolved_calculations"] == [GAP]


@pytest.mark.parametrize("value", ["ratio", [None], [""], ["x"] * 11, ["x" * 501]])
def test_invalid_unresolved_outputs_are_rejected(value):
    with pytest.raises(ValueError, match="unresolved calculations"):
        strategy.validate_strategy({**scope([]), "unresolved_calculations": value})


def test_complete_inputs_cannot_complete_an_unimplemented_request(tmp_path):
    request = scope([])
    request.update(measurements=["price"], unresolved_calculations=[GAP])
    result = {"strategy": request, "analyses": [analysis("price")]}
    derived_artifacts.finalize(result, tmp_path)
    assert result["output_completion"]["data_status"] == "complete"
    assert result["output_completion"]["calculation_status"] == "blocked"
    assert result["output_completion"]["numerical_answer_status"] == "partial"
    assert result["derived_outputs"]["unresolved_calculations"] == [GAP]
    assert GAP in result["derived_outputs"]["reason"]


def test_available_calculations_are_preserved_but_do_not_hide_unresolved_outputs():
    request = {**scope([plan()]), "unresolved_calculations": [GAP]}
    analyses = [analysis("price")]
    result = derived_outputs.compute(
        {
            "scope": request,
            "analyses": analyses,
            "jobs": derived_outputs.prepare_jobs(request, analyses),
        }
    )
    assert result["status"] == "partial"
    assert result["outputs"][0]["status"] == "complete"
    assert result["outputs"][0]["annual"][0]["value"] == 100
    assert result["unresolved_calculations"] == [GAP]


def test_explicit_empty_list_does_not_invent_a_calculation_gap():
    request = {**scope([]), "unresolved_calculations": []}
    result = derived_outputs.compute({"scope": request, "analyses": [], "jobs": []})
    assert result["status"] == "not_requested"
    assert json.loads(json.dumps(result)) == result
