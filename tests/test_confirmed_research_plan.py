import json

import pytest

from sci_search.discovery import plan_search_queries
from sci_search.generic_research import GenericResearchEngine
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.profiles import PROFILES
from sci_search.question_interpretation import interpret_question
from sci_search.question_planning import plan_from_brief, plan_question

QUESTION = "Which conditions explain the distribution of languages in South America?"
STRUCTURE = {
    "intent": "relationship",
    "subject_terms": ["language diversity"],
    "driver_terms": ["social", "biophysical"],
    "geography_terms": ["South America"],
    "evidence_preferences": [],
    "exclusion_terms": [],
}


def brief():
    return {"original_question": QUESTION, "research_plan": STRUCTURE}


def test_confirmed_structure_controls_search_and_extraction():
    plan = plan_from_brief(QUESTION, brief())
    assert plan.subject_terms == ("language diversity",)
    assert plan.intent == "relationship"
    assert "conditions" not in plan.concepts
    actual, queries = plan_search_queries(QUESTION, plan=plan)
    assert actual == plan
    assert any("language diversity" in q.text.lower() for q in queries)
    result = GenericResearchEngine(()).investigate(QUESTION, plan=plan)
    assert result.plan == plan
    assert result.research_scope["dimensions"][0]["terms"] == ["language diversity"]
    # Ordinary independent calls retain their own question, with no global override.
    assert plan_question("How does rainfall affect crop yield?").question != plan.question


def test_confirmed_brief_must_belong_to_the_question():
    with pytest.raises(ValueError, match="question"):
        plan_from_brief("A different question", brief())


@pytest.mark.parametrize(
    "bad",
    [
        {**STRUCTURE, "intent": "anything"},
        {**STRUCTURE, "subject_terms": []},
        {**STRUCTURE, "geography_terms": "South America"},
    ],
)
def test_invalid_structured_plan_does_not_silently_change_scope(bad):
    with pytest.raises(ValueError):
        plan_from_brief(QUESTION, {**brief(), "research_plan": bad})


def test_model_supplies_executable_interpretation():
    payload = {
        "interpreted_question": QUESTION,
        "objective": "Explain the drivers of language diversity.",
        "evidence_scope": [],
        "assumptions": [],
        "exclusions": [],
        "ambiguity": "clear",
        "clarification_question": None,
        "research_plan": STRUCTURE,
    }
    analyzer = MistralAnalyzer(
        "test",
        complete_json=lambda *_: {"choices": [{"message": {"content": json.dumps(payload)}}]},
    )
    result = interpret_question(QUESTION, analyzer)
    assert result["intent"] == "relationship"
    assert result["research_plan"]["subject_terms"] == ["language diversity"]
    assert plan_from_brief(QUESTION, result).subject_terms == ("language diversity",)


def test_legacy_brief_remains_readable():
    assert plan_from_brief(QUESTION, {"original_question": QUESTION}) == plan_question(QUESTION)


def test_unsupported_study_filter_is_rejected_instead_of_ignored():
    with pytest.raises(ValueError, match="Unsupported evidence filter"):
        plan_from_brief(
            QUESTION,
            {
                **brief(),
                "research_plan": {
                    **STRUCTURE,
                    "evidence_preferences": ["randomized controlled trials"],
                },
            },
        )


def test_multiple_evidence_categories_are_alternatives():
    from types import SimpleNamespace

    from sci_search.generic_research import _apply_evidence_preferences

    plan = plan_from_brief(
        QUESTION,
        {
            **brief(),
            "research_plan": {**STRUCTURE, "evidence_preferences": ["empirical", "review"]},
        },
    )
    records = tuple(
        SimpleNamespace(evidence_type=kind, study_design=kind, result_nature="reported")
        for kind in ["observational_study", "review", "simulation_or_model"]
    )
    assert _apply_evidence_preferences(records, plan) == records[:2]


def test_driver_category_labels_keep_their_synonyms():
    assert "cultural" in PROFILES["generic"].expand("social factors")
    assert "environmental" in PROFILES["generic"].expand("biophysical factors")


def test_confirmed_followup_does_not_inherit_original_time_scope(tmp_path, monkeypatch):
    import sci_search.research_runs as runs

    manager = runs.ResearchRunManager(tmp_path, openalex_api_key="test")
    manager._states["saved"] = {
        "status": "complete",
        "question": "How has crop yield evolved in Europe since 1990?",
    }
    monkeypatch.setattr(manager, "_run_directory", lambda _: tmp_path)
    monkeypatch.setattr(runs, "load_corpus", lambda _: ())
    monkeypatch.setattr(manager, "_analyze", lambda *_: {"status": "disabled"})
    question = "How does rainfall affect crop yield in Africa?"
    result = manager.investigate(
        "saved",
        question,
        question_brief={
            "original_question": question,
            "research_plan": {
                **STRUCTURE,
                "subject_terms": ["crop yield"],
                "driver_terms": ["rainfall"],
                "geography_terms": ["Africa"],
            },
        },
    )
    assert result["contextualized_question"] is None
    assert not any(d["kind"] == "time" for d in result["research_scope"]["dimensions"])


def test_run_and_saved_rebuild_preserve_confirmed_plan(tmp_path, monkeypatch):
    from sci_search.discovery import PublicationCandidate
    from sci_search.fulltext_acquisition import AcquisitionOutcome
    from sci_search.research_runs import ResearchLimits, ResearchRunManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    text = (
        "## Results\n\nSocial factors explain language diversity in South America. "
        "Language diversity in South America is also explained by biophysical factors.\n"
    )
    item = PublicationCandidate(
        id="publication:synthetic",
        title="Language diversity in South America",
        abstract=text,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
        has_local_fulltext=True,
    )

    class Provider:
        name = "synthetic"

        def search(self, query, *, limit):
            return (item,)

    def acquire(candidate, corpus):
        path = corpus / "paper.txt"
        path.write_text(text)
        return AcquisitionOutcome(
            candidate.id, "acquired", "synthetic", "paper.txt", "text/plain", len(text), len(text)
        )

    manager = ResearchRunManager(
        tmp_path, providers=(Provider(),), acquirer=acquire, openalex_api_key="test"
    )
    confirmed = brief()
    confirmed["research_plan"] = {
        **STRUCTURE,
        "relationship_type": "influence",
        "population_terms": [],
        "time_terms": [],
        "outcome_measure_terms": [],
    }
    state = manager.run_sync(
        QUESTION,
        question_brief=confirmed,
        limits=ResearchLimits(
            max_selected=1, max_full_texts=1, max_acquisition_attempts=1, citation_seed_count=0
        ),
    )
    assert state["status"] == "complete", state.get("error")
    assert state["plan"]["subject_terms"] == ["language diversity"]
    assert state["result"]["plan"]["subject_terms"] == ["language diversity"]
    assert state["result"]["evidence"]
    # Restore from disk, not the manager's in-memory plan.
    restored = ResearchRunManager(
        tmp_path, providers=(Provider(),), acquirer=acquire, openalex_api_key="test"
    )
    restored._rebuild_evidence(state["run_id"])
    result = restored.get(state["run_id"])["result"]
    assert result["plan"]["subject_terms"] == ["language diversity"]
    assert result["evidence"]
    for key in ("relationship_type", "population_terms", "time_terms", "outcome_measure_terms"):
        assert result["plan"][key] == confirmed["research_plan"][key]
