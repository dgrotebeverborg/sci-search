"""Hand-checked coverage cases: missing cells must keep an investigation open."""

import pytest

from sci_search.data_research.strategy import validate_strategy

SCOPE = dict(
    route="data",
    rationale="Compare",
    measurements=["life expectancy"],
    geography="Netherlands and Germany",
    countries=["NLD", "DEU"],
    start_year=2020,
    end_year=2021,
)


def analysis(entity, values=(80, 81), unit="years", source="one"):
    return {
        "kind": "tabular",
        "source": {"sha256": source},
        "series": [
            {
                "label": "life expectancy",
                "entity": entity,
                "unit": unit,
                "annual": [{"year": 2020 + i, "value": v} for i, v in enumerate(values)],
            }
        ],
    }


def coverage(scope, analyses):
    from sci_search.data_research.coverage import evaluate

    return evaluate(validate_strategy(scope), analyses)


def test_one_country_does_not_cover_a_multicountry_question():
    result = coverage(SCOPE, [analysis("Netherlands")])
    assert result["complete_measurements"] == []
    assert [(g["entity"], g["missing_years"]) for g in result["gaps"]] == [("DEU", [2020, 2021])]


def test_null_values_do_not_count_as_country_coverage():
    result = coverage(SCOPE, [analysis("Netherlands"), analysis("Germany", (None, None))])
    assert result["gaps"][0]["status"] == "missing"


def test_sexes_are_independent_requirements_and_do_not_match_substrings():
    scope = {
        **SCOPE,
        "countries": ["NLD"],
        "requirements": [
            {
                "measurement": "life expectancy",
                "breakdowns": [{"dimension": "sex", "values": ["female", "male"]}],
            }
        ],
    }
    result = coverage(scope, [analysis("Netherlands, females")])
    assert len(result["cells"]) == 2
    assert [g["dimensions"] for g in result["gaps"]] == [{"sex": "male"}]


def test_full_single_source_series_covers_explicit_scope():
    result = coverage(SCOPE, [analysis("geo=NL (Netherlands)"), analysis("Germany")])
    assert result["complete_measurements"] == ["life expectancy"]
    assert result["gaps"] == []


def test_sources_with_disjoint_years_are_not_silently_spliced():
    result = coverage(
        {**SCOPE, "countries": ["NLD"]},
        [
            analysis("Netherlands", (80, None), source="one"),
            analysis("Netherlands", (None, 81), unit="months", source="two"),
        ],
    )
    assert result["complete_measurements"] == []
    assert result["gaps"][0]["status"] == "partial"


def test_disagreeing_sources_require_reconciliation_even_with_full_years():
    result = coverage(
        {**SCOPE, "countries": ["NLD"]},
        [analysis("Netherlands"), analysis("Netherlands", (70, 71), source="two")],
    )
    assert result["complete_measurements"] == []
    assert result["gaps"][0]["conflicts"]


def test_planner_receives_bounded_gaps_without_losing_the_total_count():
    from sci_search.data_research.coverage import planning_summary

    scope = {
        **SCOPE,
        "countries": [],
        "requirements": [
            {
                "measurement": "life expectancy",
                "entities": [f"station {n}" for n in range(60)],
                "breakdowns": [{"dimension": "sex", "values": ["female", "male"]}],
            }
        ],
    }
    result = planning_summary(scope, [])
    assert result["missing_combinations"] == 120
    assert len(result["gaps"]) <= 60
    assert result["omitted_gaps"] == 60


def test_unbounded_period_is_not_claimed_exhaustive():
    result = coverage(
        {**SCOPE, "countries": ["NLD"], "start_year": None, "end_year": None},
        [analysis("Netherlands")],
    )
    assert result["complete_measurements"] == []
    assert result["gaps"][0]["reason"] == "Open period requires a coverage search"


def test_unknown_geography_is_a_gap_not_inferred_from_the_requested_scope():
    result = coverage(
        {**SCOPE, "countries": [], "geography": "Lobith"}, [analysis("another station")]
    )
    assert result["complete_measurements"] == []


def test_fixed_source_dimensions_can_identify_an_unlabelled_national_series():
    from sci_search.data_research.tabular import analyse_csv

    scope = {
        **SCOPE,
        "countries": ["NLD"],
        "requirements": [
            {
                "measurement": "life expectancy",
                "breakdowns": [{"dimension": "sex", "values": ["female"]}],
            }
        ],
    }
    result = analyse_csv(
        b"Year,Value\n2020,80\n2021,81\n",
        {
            "year_column": "Year",
            "value_column": "Value",
            "label": "life expectancy",
            "unit": "years",
            "output_unit": "years",
            "identity_geography": "Netherlands",
            "identity_dimensions": {"sex": "Females"},
        },
        scope,
    )
    assert coverage(scope, [result])["complete_measurements"] == ["life expectancy"]


def test_validated_strategy_retains_the_question_contract():
    requirement = {
        "measurement": "life expectancy",
        "definition": "At birth",
        "breakdowns": [{"dimension": "sex", "values": ["male", "female"]}],
        "measure_type": "ratio",
        "frequency": "annual",
    }
    result = validate_strategy({**SCOPE, "requirements": [requirement]})
    assert result["requirements"][0]["breakdowns"] == requirement["breakdowns"]
    assert validate_strategy(result) == result


@pytest.mark.parametrize(
    "requirements",
    [
        [{"measurement": "unrequested"}],
        [{"measurement": "life expectancy", "frequency": "made up"}],
        [{"measurement": "life expectancy", "breakdowns": [{"dimension": "sex", "values": []}]}],
    ],
)
def test_invalid_requirements_are_rejected(requirements):
    with pytest.raises(ValueError, match="requirement|frequency|breakdown"):
        validate_strategy({**SCOPE, "requirements": requirements})


def test_coverage_is_readable_in_exported_reports(tmp_path):
    from sci_search.data_research.reporting import export, markdown_appendix

    result = {
        "kind": "discovered",
        "analyses": [],
        "assessments": [],
        "limitations": [],
        "coverage": coverage(SCOPE, [analysis("Netherlands")]),
    }
    assert "1 of 2 requested combinations covered" in export(result, tmp_path)[2].decode()
    assert "DEU" in markdown_appendix(result)


def test_combined_countries_do_not_cover_individual_countries():
    assert not coverage(SCOPE, [analysis("Netherlands and Germany (combined)")])[
        "complete_measurements"
    ]


def test_different_labels_do_not_hide_conflicting_observations():
    result = coverage(
        {**SCOPE, "countries": ["NLD"]},
        [analysis("Netherlands"), analysis("geo=NL (Netherlands)", (70, 71), source="two")],
    )
    assert result["gaps"][0]["conflicts"]


def test_combined_sexes_do_not_cover_individual_sexes():
    scope = {
        **SCOPE,
        "countries": ["NLD"],
        "requirements": [
            {
                "measurement": "life expectancy",
                "breakdowns": [{"dimension": "sex", "values": ["male", "female"]}],
            }
        ],
    }
    assert len(coverage(scope, [analysis("Netherlands male/female combined")])["gaps"]) == 2


def test_single_requested_sex_rejects_combined_sexes():
    scope = {
        **SCOPE,
        "countries": ["NLD"],
        "requirements": [
            {
                "measurement": "life expectancy",
                "breakdowns": [{"dimension": "sex", "values": ["female"]}],
            }
        ],
    }
    assert coverage(scope, [analysis("Netherlands male/female combined")])["gaps"]


def test_fixed_sex_identity_and_display_label_share_conflict_identity():
    scope = {
        **SCOPE,
        "countries": ["NLD"],
        "requirements": [
            {
                "measurement": "life expectancy",
                "breakdowns": [{"dimension": "sex", "values": ["female"]}],
            }
        ],
    }
    fixed = analysis("Value")
    fixed["series"][0]["identity"] = {"geography": "Netherlands", "dimensions": {"sex": "Females"}}
    assert coverage(scope, [fixed, analysis("Netherlands females", (70, 71), source="two")])[
        "gaps"
    ][0]["conflicts"]


def test_ordinary_and_is_not_the_country_code_for_andorra():
    assert coverage({**SCOPE, "countries": ["NLD"]}, [analysis("Netherlands women and girls")])[
        "complete_measurements"
    ]
