import copy

import pytest

from sci_search.data_research.calculations import calculate
from sci_search.data_research.coverage import evaluate
from sci_search.data_research.derived_outputs import prepare_jobs
from sci_search.data_research.strategy import validate_strategy


def scope():
    return dict(
        route="data",
        rationale="Annual shares and changes",
        geography="Spain",
        countries=["ESP"],
        measurements=["share"],
        start_year=2000,
        end_year=2002,
        requirements=[
            dict(
                measurement="share",
                definition="State the chosen denominator",
                definition_policy="choose_documented",
                measure_type="percentage",
            )
        ],
    )


def plan(base=None):
    return dict(
        id="change",
        label="Change in percentage points",
        operation="percentage_point_change",
        input="share",
        reference=None,
        base_year=base,
        target_unit=None,
    )


def analysis(values, definition="Gross final consumption"):
    return dict(
        source=dict(sha256="a" * 64, title=definition, definition=definition),
        execution=dict(status="verified"),
        semantic_review=dict(
            accepted=True,
            measurements=[
                dict(
                    measurement="share",
                    checks=[
                        dict(
                            aspect="definition",
                            status="supported",
                            reason=definition,
                            evidence=[dict(document="metadata", quote=definition)],
                        )
                    ],
                )
            ],
        ),
        series=[
            dict(
                label="share",
                entity="Spain",
                unit="PC",
                measure_type="percentage",
                annual=[dict(year=2000 + i, value=v) for i, v in enumerate(values)],
            )
        ],
    )


def test_annual_percentage_points_are_subtractions_with_two_traceable_inputs():
    out = calculate(plan(), analysis([10, 12, 9])["series"][0], years=[2001, 2002])
    assert [r["value"] for r in out["annual"]] == [2, -3]
    assert out["unit"] == "percentage points" and out["status"] == "complete"
    assert [i["year"] for i in out["annual"][0]["inputs"]] == [2001, 2000]


def test_baseline_difference_allows_zero_and_negative_values():
    p = {**plan(2000), "operation": "difference"}
    s = analysis([0, -2, 3])["series"][0]
    s.update(unit="°C", measure_type="interval")
    out = calculate(p, s, years=[2000, 2001, 2002])
    assert [r["value"] for r in out["annual"]] == [0, -2, 3]
    assert out["unit"] == "°C"


def test_missing_previous_year_is_not_replaced_by_previous_available_observation():
    out = calculate(plan(), analysis([10, None, 12])["series"][0], years=[2001, 2002])
    assert out["status"] == "blocked"
    assert all(r["value"] is None for r in out["annual"])


@pytest.mark.parametrize(
    "change",
    [
        dict(unit="fraction"),
        dict(measure_type="ratio"),
        dict(comparability_note="Break in definition"),
    ],
)
def test_percentage_points_require_documented_percentage_scale_and_comparability(change):
    s = {**analysis([10, 12, 9])["series"][0], **change}
    assert calculate(plan(), s, years=[2001, 2002])["status"] == "blocked"


def test_annual_change_output_starts_at_second_requested_year():
    s = validate_strategy({**scope(), "calculations": [plan()]})
    jobs = prepare_jobs(s, [analysis([10, 12, 9])])
    assert jobs[0]["years"] == [2001, 2002]


def test_requested_calculation_cannot_be_silently_left_unassigned():
    with pytest.raises(ValueError, match="request"):
        validate_strategy(
            {
                **scope(),
                "calculations": [],
                "calculation_requests": [
                    dict(
                        description="Annual percentage-point changes",
                        calculation_ids=[],
                        unresolved_reason="",
                    )
                ],
            }
        )


def test_unsupported_request_blocks_completion_explicitly():
    s = validate_strategy(
        {
            **scope(),
            "calculations": [],
            "calculation_requests": [
                dict(
                    description="Temperature anomaly",
                    calculation_ids=[],
                    unresolved_reason="Reference-mean subtraction unsupported",
                )
            ],
        }
    )
    assert "Temperature anomaly" in s["unresolved_calculations"][0]


def test_documented_complete_source_is_selected_for_whole_comparison():
    sources = [analysis([1, 2, None], "Final consumption"), analysis([10, 12, 9])]
    before = copy.deepcopy(sources)
    result = evaluate(scope(), sources)
    assert result["complete_measurements"] == ["share"]
    assert result["source_choices"]["share"]["source_index"] == 1
    assert result["source_choices"]["share"]["alternative_source_indexes"] == [0]
    assert result["cells"][0]["sources"][0]["source_index"] == 1
    assert sources == before


def test_specified_definition_keeps_conflicting_sources_unresolved():
    s = scope()
    s["requirements"][0]["definition_policy"] = "specified"
    assert not evaluate(s, [analysis([1, 2, 3]), analysis([10, 12, 9])])["complete_measurements"]


def test_unreviewed_or_incomplete_sources_are_not_selected():
    sources = [analysis([1, 2, None]), analysis([10, None, 9])]
    assert not evaluate(scope(), sources).get("source_choices")
    assert not evaluate(scope(), sources)["complete_measurements"]
    sources[0] = analysis([1, 2, 3])
    sources[0]["semantic_review"]["accepted"] = False
    assert not evaluate(scope(), sources).get("source_choices")


def test_definition_choice_never_assembles_a_country_panel_from_different_sources():
    s = scope()
    s["countries"] = ["ESP", "PRT"]
    first, second = analysis([1, 2, 3]), analysis([10, 12, 9])
    second["series"][0]["entity"] = "Portugal"
    coverage = evaluate(s, [first, second])
    assert not coverage["complete_measurements"]
    assert not coverage.get("source_choices")


@pytest.mark.parametrize(
    "ids,reason", [(["missing"], ""), (["change"], "Unsupported"), (["change", "change"], "")]
)
def test_calculation_inventory_rejects_unknown_duplicated_or_ambiguous_assignments(ids, reason):
    with pytest.raises(ValueError):
        validate_strategy(
            {
                **scope(),
                "calculations": [plan()],
                "calculation_requests": [
                    dict(
                        description="Annual changes", calculation_ids=ids, unresolved_reason=reason
                    )
                ],
            }
        )


def test_selected_source_drives_requested_changes_without_using_alternative_values():
    from sci_search.data_research.derived_outputs import compute

    s = validate_strategy(
        {
            **scope(),
            "calculations": [plan()],
            "calculation_requests": [
                dict(
                    description="Annual percentage-point changes",
                    calculation_ids=["change"],
                    unresolved_reason="",
                )
            ],
        }
    )
    sources = [analysis([1, 2, None], "Final consumption"), analysis([10, 12, 9])]
    jobs = prepare_jobs(s, sources)
    out = compute(dict(scope=s, analyses=sources, jobs=jobs))
    assert out["status"] == "complete"
    assert [r["value"] for r in out["outputs"][0]["annual"]] == [2, -3]
    assert out["outputs"][0]["sources"][0]["analysis_index"] == 1
