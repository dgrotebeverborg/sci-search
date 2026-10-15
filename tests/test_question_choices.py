"""Clickable versions of a question and the researcher's changes to them."""

import copy

import pytest

from sci_search.question_choices import adjust, option_briefs
from sci_search.question_planning import plan_from_brief

QUESTION = "How does melting of Himalayan glaciers affect downstream water availability until 2100?"
PLAN = {
    "intent": "relationship",
    "relationship_type": "influence",
    "subject_terms": ["downstream water availability"],
    "driver_terms": ["glacier melt"],
    "geography_terms": ["Himalaya"],
    "evidence_preferences": [],
    "exclusion_terms": [],
    "population_terms": [],
    "time_terms": ["until 2100"],
    "outcome_measure_terms": [],
}
BASE = {
    "original_question": QUESTION,
    "interpreted_question": "How does Himalayan glacier melt affect downstream water availability to 2100?",
    "objective": "Assess evidence on glacier melt and downstream water availability.",
    "profile_id": "generic",
    "intent": "relationship",
    "concepts": [],
    "evidence_scope": [],
    "comparison_dimensions": [],
    "assumptions": [],
    "exclusions": [],
    "ambiguity": "clear",
    "clarification_question": None,
    "method": "codex_structured_question_interpretation_v1",
    "provider": "codex",
    "model": "m",
    "research_plan": PLAN,
    "data_research": {
        "adapter": "discovered_data_v1",
        "route": "literature",
        "rationale": "Mechanisms and impacts need studies.",
        "measurements": [],
        "geography": "Himalaya",
        "country_scope": "other",
        "countries": [],
        "start_year": None,
        "end_year": None,
    },
}
DATA_OPTION = {
    "title": "Projected glacier runoff to 2100",
    "summary": "Projected glacier mass and runoff per basin under emission scenarios.",
    "closest": False,
    "interpreted_question": "How are glacier mass and glacier runoff in the Indus, Ganges and Brahmaputra basins projected to change until 2100?",
    "objective": "Analyse projected glacier mass and runoff per basin and scenario.",
    "research_plan": {
        **PLAN,
        "intent": "temporal_trend",
        "relationship_type": "unspecified",
        "subject_terms": ["glacier runoff"],
        "driver_terms": [],
        "geography_terms": ["Indus basin", "Ganges basin", "Brahmaputra basin"],
    },
    "research_strategy": {
        "route": "data",
        "rationale": "Glacier model projections are published per basin.",
        "measurements": [
            "projected glacier mass (SSP scenarios)",
            "projected glacier runoff (SSP scenarios)",
        ],
        "geography": "Indus, Ganges and Brahmaputra basins",
        "country_scope": "other",
        "countries": [],
        "start_year": 2000,
        "end_year": 2100,
    },
    "alternatives": {
        "route": ["data", "both", "literature"],
        "measurements": [["projected glacier runoff (SSP scenarios)"]],
        "geography": [
            {
                "label": "Indus basin",
                "geography_terms": ["Indus basin"],
                "countries": ["PAK", "IND", "CHN", "AFG"],
            }
        ],
        "period": [{"label": "2000–2050", "start_year": 2000, "end_year": 2050}],
    },
}
CLOSEST_OPTION = {
    **DATA_OPTION,
    "title": "How glacier melt affects water downstream",
    "summary": "Studies on mechanisms and impacts in the Himalayan river basins.",
    "closest": True,
    "interpreted_question": BASE["interpreted_question"],
    "objective": BASE["objective"],
    "research_plan": PLAN,
    "research_strategy": {**BASE["data_research"], "rationale": "Studies explain the effects."},
}
INVALID_OPTION = {**DATA_OPTION, "research_plan": {**PLAN, "intent": "not an intent"}}


def test_valid_options_are_kept_with_the_closest_first():
    options = option_briefs(QUESTION, BASE, [DATA_OPTION, INVALID_OPTION, CLOSEST_OPTION])
    assert [o["title"] for o in options] == [CLOSEST_OPTION["title"], DATA_OPTION["title"]]
    assert [o["closest"] for o in options] == [True, False]
    data = options[1]["brief"]
    assert data["original_question"] == QUESTION
    assert data["data_research"]["end_year"] == 2100
    assert data["intent"] == "temporal_trend"
    assert data["evidence_scope"]
    assert "options" not in data
    assert options[1]["alternatives"]["geography"][0]["countries"] == ["PAK", "IND", "CHN", "AFG"]


def test_without_options_the_question_itself_is_the_only_choice():
    options = option_briefs(QUESTION, BASE, [])
    assert len(options) == 1
    assert options[0]["title"] == "Your question"
    assert options[0]["closest"] is True
    assert options[0]["brief"]["interpreted_question"] == BASE["interpreted_question"]


def data_brief():
    return option_briefs(QUESTION, BASE, [DATA_OPTION])[0]["brief"]


def test_a_geography_choice_changes_plan_and_strategy_together():
    value = DATA_OPTION["alternatives"]["geography"][0]
    brief = adjust(data_brief(), {"detail": "geography", "value": value})
    assert brief["research_plan"]["geography_terms"] == ["Indus basin"]
    assert brief["data_research"]["geography"] == "Indus basin"
    assert brief["data_research"]["countries"] == ["PAK", "IND", "CHN", "AFG"]
    plan_from_brief(QUESTION, brief)


def test_a_period_choice_changes_time_terms_and_years():
    brief = adjust(
        data_brief(), {"detail": "period", "value": DATA_OPTION["alternatives"]["period"][0]}
    )
    assert brief["research_plan"]["time_terms"] == ["2000–2050"]
    assert (brief["data_research"]["start_year"], brief["data_research"]["end_year"]) == (
        2000,
        2050,
    )


def test_choosing_data_without_measurements_gives_a_readable_reason():
    with pytest.raises(ValueError, match="Choose or type at least one measurement"):
        adjust(BASE, {"detail": "route", "value": "data"})


def test_measurements_on_a_literature_brief_keep_its_route_and_then_allow_data():
    brief = adjust(BASE, {"detail": "measurements", "value": ["projected glacier runoff"]})
    assert brief["data_research"]["route"] == "literature"
    assert brief["data_research"]["measurements"] == ["projected glacier runoff"]
    assert adjust(brief, {"detail": "route", "value": "both"})["data_research"]["route"] == "both"


def test_a_brief_without_a_strategy_gets_one_when_measurements_are_typed():
    brief = {**copy.deepcopy(BASE), "data_research": None}
    adjusted = adjust(brief, {"detail": "measurements", "value": ["river discharge"]})
    assert adjusted["data_research"]["measurements"] == ["river discharge"]
    assert adjusted["data_research"]["geography"] == "Himalaya"


def test_free_typed_geography_and_period_are_accepted():
    brief = adjust(
        data_brief(),
        {
            "detail": "geography",
            "value": {"label": "Upper Indus", "geography_terms": ["Upper Indus"], "countries": []},
        },
    )
    assert brief["data_research"]["countries"] == []
    brief = adjust(
        brief, {"detail": "period", "value": {"label": "", "start_year": 1990, "end_year": 2100}}
    )
    assert brief["research_plan"]["time_terms"] == ["1990–2100"]


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"detail": "colour", "value": "red"}, "Unknown detail"),
        ({"detail": "route", "value": "guess"}, "Unknown research approach"),
        (
            {"detail": "period", "value": {"label": "", "start_year": 2000, "end_year": 2200}},
            "years",
        ),
        (
            {"detail": "geography", "value": {"label": "", "geography_terms": [], "countries": []}},
            "Give a place",
        ),
        (
            {
                "detail": "geography",
                "value": {"label": "X", "geography_terms": ["X"], "countries": ["NOTACODE"]},
            },
            "country",
        ),
    ],
)
def test_invalid_changes_are_refused_with_a_reason(change, reason):
    with pytest.raises(ValueError, match=reason):
        adjust(data_brief(), change)


def test_adjust_never_changes_its_input():
    brief = data_brief()
    before = copy.deepcopy(brief)
    adjust(brief, {"detail": "route", "value": "both"})
    assert brief == before


def scripted_analyzer(payload, seen):
    import json

    from sci_search.mistral_analysis import MistralAnalyzer

    def complete(body, headers):
        seen.append(json.loads(body["messages"][-1]["content"]))
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return MistralAnalyzer("key", model="m", complete_json=complete)


def model_payload(**extra):
    return {
        "interpreted_question": BASE["interpreted_question"],
        "objective": BASE["objective"],
        "evidence_scope": [],
        "assumptions": [],
        "exclusions": [],
        "ambiguity": "clear",
        "clarification_question": None,
        "research_plan": PLAN,
        "research_strategy": {k: v for k, v in BASE["data_research"].items() if k != "adapter"},
        **extra,
    }


def test_the_interpretation_returns_validated_options():
    from sci_search.question_interpretation import interpret_question

    seen = []
    options = [DATA_OPTION, CLOSEST_OPTION, INVALID_OPTION]
    result = interpret_question(QUESTION, scripted_analyzer(model_payload(options=options), seen))
    assert [o["title"] for o in result["options"]] == [
        CLOSEST_OPTION["title"],
        DATA_OPTION["title"],
    ]
    assert result["options"][1]["brief"]["data_research"]["end_year"] == 2100
    assert result["clarification_options"] == []


def test_steering_and_a_clarification_reach_the_model():
    from sci_search.question_interpretation import interpret_question

    seen = []
    steer = {"direction": "more_data", "option": {"title": "Projected glacier runoff to 2100"}}
    interpret_question(
        QUESTION,
        scripted_analyzer(model_payload(), seen),
        steer=steer,
        clarification="Only the Indus basin",
    )
    assert seen[0]["steer"] == steer
    assert seen[0]["clarification_answer"] == "Only the Indus basin"
    assert seen[0]["question"] == QUESTION


def test_clarification_options_are_returned_with_a_material_ambiguity():
    from sci_search.question_interpretation import interpret_question

    payload = model_payload(
        ambiguity="material",
        clarification_question="Which rivers do you mean?",
        clarification_options=["Indus", "Ganges and Brahmaputra", "All Himalayan rivers"],
    )
    result = interpret_question(QUESTION, scripted_analyzer(payload, []))
    assert result["clarification_options"] == [
        "Indus",
        "Ganges and Brahmaputra",
        "All Himalayan rivers",
    ]
    assert len(result["options"]) == 1


def test_without_a_model_the_question_is_the_only_option(monkeypatch):
    from sci_search.question_interpretation import interpret_question

    monkeypatch.setenv("MISTRAL_API_KEY", "")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral")
    result = interpret_question("How does vegetation structure affect goat foraging behaviour?")
    assert [o["title"] for o in result["options"]] == ["Your question"]


def test_a_brief_without_a_research_plan_can_still_change_its_data_strategy():
    brief = {**copy.deepcopy(BASE), "research_plan": None}
    brief["data_research"].update(route="data", measurements=["population"])
    adjusted = adjust(brief, {"detail": "route", "value": "both"})
    assert adjusted["data_research"]["route"] == "both"
    adjusted = adjust(
        adjusted, {"detail": "period", "value": {"label": "", "start_year": 2001, "end_year": 2024}}
    )
    assert adjusted["data_research"]["start_year"] == 2001
    assert adjusted["research_plan"] is None
