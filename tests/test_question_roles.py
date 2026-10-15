import pytest

from sci_search.coverage import decompose_question
from sci_search.discovery import PublicationCandidate, plan_search_queries
from sci_search.fulltext_screening import screen_full_text
from sci_search.question_planning import plan_from_brief

QUESTION = "Is neighborhood green space associated with a lower risk of type 2 diabetes?"
STRUCTURE = dict(
    intent="relationship",
    relationship_type="association",
    subject_terms=["type 2 diabetes"],
    driver_terms=["neighborhood green space"],
    geography_terms=[],
    population_terms=[],
    time_terms=[],
    evidence_preferences=[],
    exclusion_terms=[],
)


def plan(**changes):
    return plan_from_brief(
        QUESTION, {"original_question": QUESTION, "research_plan": {**STRUCTURE, **changes}}
    )


def test_relationship_roles_cannot_be_mixed_or_missing():
    with pytest.raises(ValueError, match="factor"):
        plan(driver_terms=[])
    with pytest.raises(ValueError, match="distinct"):
        plan(subject_terms=["neighborhood green space", "type 2 diabetes"])


def test_association_queries_preserve_roles_without_assuming_causation():
    p = plan()
    scope = decompose_question(QUESTION, p)
    assert scope["dimensions"][0]["terms"] == ["type 2 diabetes"]
    driver_terms = next(d for d in scope["dimensions"] if d["kind"] == "topic")["terms"]
    assert "neighborhood green space" in driver_terms
    assert "residential greenness" in driver_terms
    assert "type 2 diabetes" not in driver_terms
    _, queries = plan_search_queries(QUESTION, plan=p)
    assert any("association" in q.text for q in queries)
    assert not any("drivers mechanisms" in q.text for q in queries)


@pytest.mark.parametrize("result", ["lower risk", "higher risk", "no association"])
def test_screening_accepts_all_directions_of_the_requested_association(result):
    text = f"We studied neighborhood green space and type 2 diabetes. Neighborhood green space showed {result} for type 2 diabetes."
    candidate = PublicationCandidate(
        id="study",
        title="Neighborhood green space and type 2 diabetes",
        abstract=text,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    assert screen_full_text(QUESTION, plan(), candidate, text).decision == "included"


def test_green_space_paper_without_diabetes_outcome_is_not_answer_evidence():
    text = "Neighborhood green space was associated with lower noise levels. Neighborhood green space reduced noise levels."
    candidate = PublicationCandidate(
        id="study",
        title="Neighborhood green space and noise",
        abstract=text,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    assert screen_full_text(QUESTION, plan(), candidate, text).decision == "excluded"


def test_confirmed_population_and_period_become_required_scope():
    p = plan(population_terms=["adults"], time_terms=["2010–2020"], outcome_measure_terms=["risk"])
    dimensions = decompose_question(QUESTION, p)["dimensions"]
    assert any(
        d["kind"] == "population" and d["required"] and d["terms"] == ["adults"] for d in dimensions
    )
    assert any(
        d["kind"] == "time" and d["start_year"] == 2010 and d["end_year"] == 2020
        for d in dimensions
    )


def test_invalid_mixed_model_roles_require_clarification(monkeypatch):
    import json

    from sci_search.mistral_analysis import MistralAnalyzer
    from sci_search.question_interpretation import interpret_question

    payload = dict(
        interpreted_question=QUESTION,
        objective="Evaluate the association.",
        ambiguity="clear",
        clarification_question=None,
        assumptions=[],
        exclusions=[],
        evidence_scope=["neighborhood green space", "type 2 diabetes"],
        research_plan={
            **STRUCTURE,
            "subject_terms": ["neighborhood green space", "type 2 diabetes"],
            "driver_terms": [],
        },
    )
    analyzer = MistralAnalyzer(
        "test",
        complete_json=lambda *_: {"choices": [{"message": {"content": json.dumps(payload)}}]},
    )
    brief = interpret_question(QUESTION, analyzer)
    assert brief["ambiguity"] == "material"
    with pytest.raises(ValueError, match="Clarify"):
        plan_from_brief(QUESTION, brief)


def test_model_evidence_description_explains_studies_not_keyword_list():
    import json

    from sci_search.mistral_analysis import MistralAnalyzer
    from sci_search.question_interpretation import interpret_question

    payload = dict(
        interpreted_question=QUESTION,
        objective="Evaluate the association.",
        ambiguity="clear",
        clarification_question=None,
        assumptions=[],
        exclusions=[],
        evidence_scope=["neighborhood green space", "type 2 diabetes"],
        research_plan=STRUCTURE,
    )
    analyzer = MistralAnalyzer(
        "test",
        complete_json=lambda *_: {"choices": [{"message": {"content": json.dumps(payload)}}]},
    )
    brief = interpret_question(QUESTION, analyzer)
    assert brief["research_plan"]["driver_terms"] == ["neighborhood green space"]
    assert "Studies examining" in brief["evidence_scope"][0]
    assert "no association" in brief["evidence_scope"][1]


def test_explicit_unrestricted_period_does_not_gain_hidden_date_filter():
    question = "Is neighborhood green space associated with type 2 diabetes since 2000?"
    p = plan_from_brief(question, {"original_question": question, "research_plan": STRUCTURE})
    assert not any(d["kind"] == "time" for d in decompose_question(question, p)["dimensions"])


def test_confirmed_population_excludes_a_different_study_population():
    p = plan(population_terms=["adults"])
    text = "In children, neighborhood green space had no association with type 2 diabetes. Neighborhood green space and type 2 diabetes were measured in children."
    candidate = PublicationCandidate(
        id="children",
        title="Neighborhood green space and type 2 diabetes in children",
        abstract=text,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    decision = screen_full_text(QUESTION, p, candidate, text)
    assert decision.decision == "excluded"
    assert "adults" in decision.missing_groups


def test_new_scope_fields_survive_saved_plan_roundtrip():
    from dataclasses import asdict

    from sci_search.research_runs import _research_plan

    p = plan(population_terms=["adults"], time_terms=["2010–2020"], outcome_measure_terms=["risk"])
    assert _research_plan(asdict(p)) == p


@pytest.mark.parametrize("year,expected", [(2015, "included"), (2005, "excluded")])
def test_association_period_accepts_one_study_year_in_range(year, expected):
    from sci_search.coverage import evidence_context

    p = plan(time_terms=["2010–2020"])
    text = f"In {year}, we studied neighborhood green space and type 2 diabetes. Neighborhood green space showed no association with type 2 diabetes."
    candidate = PublicationCandidate(
        id="study",
        title="Neighborhood green space and type 2 diabetes",
        abstract=text,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    assert screen_full_text(QUESTION, p, candidate, text).decision == expected
    context = evidence_context(text, decompose_question(QUESTION, p))
    assert ("time:requested_period" in context["scope_dimension_ids"]) == (expected == "included")


def test_risk_measure_is_preserved_and_required_beyond_disease_topic():
    p = plan(outcome_measure_terms=["risk"])
    dimensions = decompose_question(QUESTION, p)["dimensions"]
    measure = next(d for d in dimensions if d["kind"] == "outcome")
    assert measure["label"] == "risk"
    text = "We studied neighborhood green space and type 2 diabetes. Neighborhood green space was related to gene expression in type 2 diabetes."
    candidate = PublicationCandidate(
        id="study",
        title="Neighborhood green space and type 2 diabetes",
        abstract=text,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    assert screen_full_text(QUESTION, p, candidate, text).decision != "included"
    text = "We studied neighborhood green space and type 2 diabetes risk. Neighborhood green space showed no association with type 2 diabetes risk."
    from dataclasses import replace

    candidate = replace(candidate, abstract=text)
    assert screen_full_text(QUESTION, p, candidate, text).decision == "included"


def test_explicit_measure_outside_builtin_aliases_is_supported():
    p = plan(outcome_measure_terms=["hospital admissions"])
    dimensions = decompose_question(QUESTION, p)["dimensions"]
    assert any(d["kind"] == "outcome" and d["label"] == "hospital admissions" for d in dimensions)
