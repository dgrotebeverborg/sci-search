"""Literal bounded periods must survive omitted or drifting model dates."""

import json

import pytest

from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.question_interpretation import interpret_question


def interpreted(question, start=None, end=None, **kwargs):
    plan = {
        "intent": "temporal_trend",
        "subject_terms": ["population"],
        "driver_terms": [],
        "geography_terms": ["Netherlands"],
        "evidence_preferences": [],
        "exclusion_terms": [],
    }
    strategy = {
        "route": "data",
        "rationale": "Official observed population.",
        "measurements": ["observed population"],
        "geography": "Netherlands",
        "start_year": start,
        "end_year": end,
    }
    payload = {
        "interpreted_question": question,
        "objective": "Find observed population counts.",
        "ambiguity": "clear",
        "research_plan": plan,
        "research_strategy": strategy,
        "options": [
            {
                "title": "Observed population",
                "summary": "Observed population over time.",
                "closest": True,
                "interpreted_question": question,
                "objective": "Find observed population counts.",
                "research_plan": plan,
                "research_strategy": strategy,
            }
        ],
    }
    analyzer = MistralAnalyzer(
        "secret",
        complete_json=lambda body, headers: {
            "choices": [{"message": {"content": json.dumps(payload)}}]
        },
    )
    return interpret_question(question, analyzer=analyzer, **kwargs)


@pytest.mark.parametrize("start,end", [(None, None), (2014, 2026), (2027, 2030)])
def test_future_observations_keep_requested_period_in_brief_and_closest_option(start, end):
    brief = interpreted(
        "Geef voor Nederland de definitief waargenomen jaarlijkse totale bevolking op 1 januari "
        "van 2027 tot en met 2030. Gebruik uitsluitend gerealiseerde waarnemingen, geen prognoses, "
        "scenario’s of extrapolaties. Als deze nog niet beschikbaar zijn, zeg dat expliciet.",
        start,
        end,
    )
    for item in (brief, brief["options"][0]["brief"]):
        scope = item["data_research"]
        assert scope is not None
        assert (scope["start_year"], scope["end_year"]) == (2027, 2030)
        assert scope["measurements"] == ["observed population"]


@pytest.mark.parametrize(
    "question",
    [
        "Observed population for 2000-2020.",
        "Observed population from 2000 to 2020.",
        "Observed population between 2000 and 2020.",
        "Waargenomen bevolking van 2000 tot en met 2020.",
        "Waargenomen bevolking tussen 2000 en 2020.",
    ],
)
def test_explicit_historical_interval_is_preserved(question):
    scope = interpreted(question)["data_research"]
    assert (scope["start_year"], scope["end_year"]) == (2000, 2020)


@pytest.mark.parametrize(
    "question",
    [
        "Observed population since 2000.",
        "Compare population in 1990–2000 and 2010–2020.",
        "Temperature anomalies relative to the 1991–2020 baseline.",
        "Temperature anomalies for 2000–2025 relative to 1991–2020.",
        "Population index for 2000–2020, 2015=100.",
        "Population up to 2020.",
    ],
)
def test_ambiguous_reference_and_open_intervals_do_not_override_model(question):
    scope = interpreted(question, 2001, None)["data_research"]
    assert (scope["start_year"], scope["end_year"]) == (2001, None)


def test_clarified_period_is_not_overwritten_by_original_question():
    scope = interpreted(
        "Population for 2000–2020.", 2010, 2025, clarification="Use 2010–2025 instead."
    )["data_research"]
    assert (scope["start_year"], scope["end_year"]) == (2010, 2025)


def test_historical_data_cannot_partially_cover_a_future_only_observation_request():
    from sci_search.data_research.coverage import evaluate

    scope = interpreted("Observed population in the Netherlands for 2027–2030, no projections.")[
        "data_research"
    ]
    result = evaluate(
        scope,
        [
            {
                "kind": "tabular",
                "source": {"sha256": "historical"},
                "series": [
                    {
                        "label": "observed population",
                        "entity": "Netherlands",
                        "unit": "persons",
                        "annual": [{"year": year, "value": 17000000} for year in range(2014, 2027)],
                    }
                ],
            }
        ],
    )
    assert result["complete_measurements"] == []
    assert result["gaps"][0]["status"] == "missing"
    assert result["gaps"][0]["available_years"] == []
    assert result["gaps"][0]["missing_years"] == [2027, 2028, 2029, 2030]


def test_unrelated_clarification_preserves_original_period():
    result = interpreted(
        "Population for 2027–2030.", 2014, 2026, clarification="Use official statistics only."
    )
    assert (result["data_research"]["start_year"], result["data_research"]["end_year"]) == (
        2027,
        2030,
    )
