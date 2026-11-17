"""Model-supplied wording variants widen recognition of plan terms only."""

from dataclasses import replace

from sci_search.coverage import decompose_question
from sci_search.question_planning import parse_term_synonyms, plan_question


def test_synonyms_are_kept_only_for_known_terms_and_bounded():
    parsed = parse_term_synonyms(
        [
            {"term": "Freshwater Zooplankton", "synonyms": ["Daphnia", "cladocerans", "daphnia"]},
            {"term": "unknown term", "synonyms": ["x y"]},
            {"term": "survival", "synonyms": ["survival", "", "mortality", 7]},
            "malformed",
        ],
        ("freshwater zooplankton", "survival"),
    )
    assert parsed == (
        ("freshwater zooplankton", ("Daphnia", "cladocerans", "daphnia")),
        ("survival", ("mortality",)),
    )
    assert parse_term_synonyms(None, ("a",)) == ()


def test_decomposition_adds_synonyms_to_every_dimension_using_the_term():
    question = (
        "What is the effect of reducing class size on student achievement in primary schools?"
    )
    plan = replace(
        plan_question(question),
        intent="relationship",
        subject_terms=("student achievement",),
        driver_terms=("class size",),
        population_terms=("primary school students",),
        term_synonyms=(
            ("primary school students", ("elementary school students", "pupils")),
            ("student achievement", ("test scores",)),
        ),
    )
    dimensions = {d["label"]: d for d in decompose_question(question, plan)["dimensions"]}
    assert "elementary school students" in dimensions["primary school students"]["terms"]
    subject = next(d for d in dimensions.values() if d["kind"] == "subject")
    assert "test scores" in subject["term_groups"][0]


def test_placeholder_driver_is_checked_as_any_explicit_explanation():
    question = "What factors explain the gender wage gap in European labour markets?"
    plan = replace(
        plan_question(question),
        intent="relationship",
        subject_terms=("gender wage gap",),
        driver_terms=("factors explaining the gender wage gap",),
    )
    topic = next(
        d for d in decompose_question(question, plan)["dimensions"] if d["kind"] == "topic"
    )
    assert "explained by" in topic["terms"]
    assert "factors explaining the gender wage gap" not in topic["terms"]


def test_setting_populations_and_exposure_drivers_accept_common_wording():
    from sci_search.coverage import _exposure_aliases, _population_aliases

    assert "primary school" in _population_aliases("primary school students")
    assert _population_aliases("older adults") == ("older adults",)
    assert {"exposure to microplastic", "microplastic"} <= set(
        _exposure_aliases("microplastic exposure")
    )
    assert _exposure_aliases("class size") == ()
