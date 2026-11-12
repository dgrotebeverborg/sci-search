"""Every question is researched in English, whatever language it was asked in."""

import json

from sci_search.discovery import plan_search_queries
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.question_interpretation import interpret_question
from sci_search.question_planning import plan_from_brief

DUTCH = "Hoe beïnvloedt het smelten van gletsjers in de Himalaya de waterbeschikbaarheid stroomafwaarts?"
ENGLISH = "How does Himalayan glacier melt affect downstream water availability?"
PLAN = {
    "intent": "relationship",
    "relationship_type": "influence",
    "subject_terms": ["downstream water availability"],
    "driver_terms": ["glacier melt"],
    "geography_terms": ["Himalaya"],
    "exclusion_terms": [],
    "population_terms": [],
    "time_terms": [],
    "outcome_measure_terms": [],
    "evidence_preferences": [],
}


def brief():
    return {
        "original_question": DUTCH,
        "english_question": ENGLISH,
        "ambiguity": "clear",
        "research_plan": PLAN,
    }


def test_the_interpretation_is_asked_in_english_and_keeps_the_translation():
    sent = []

    def complete(body, headers):
        sent.append(body)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "english_question": ENGLISH,
                                "interpreted_question": ENGLISH,
                                "objective": "Synthesize evidence on glacier melt and water supply.",
                                "evidence_scope": [],
                                "assumptions": [],
                                "exclusions": [],
                                "research_plan": PLAN,
                                "ambiguity": "clear",
                                "clarification_question": None,
                            }
                        )
                    }
                }
            ]
        }

    result = interpret_question(DUTCH, analyzer=MistralAnalyzer("k", complete_json=complete))
    system = sent[0]["messages"][0]["content"]
    assert "Write every field in English" in system
    assert "english_question" in sent[0]["response_format"]["json_schema"]["schema"]["required"]
    assert result["english_question"] == ENGLISH
    assert result["original_question"] == DUTCH
    assert all(option["brief"]["english_question"] == ENGLISH for option in result["options"])


def test_the_literature_search_uses_the_english_question():
    plan = plan_from_brief(DUTCH, brief())
    assert plan.question == ENGLISH
    _, queries = plan_search_queries(DUTCH, plan=plan)
    texts = " ".join(query.text for query in queries)
    assert "beïnvloedt" not in texts
    assert ENGLISH.rstrip("?") in texts


def test_a_brief_without_a_translation_keeps_the_question():
    plan = plan_from_brief(DUTCH, {**brief(), "english_question": None})
    assert plan.question == DUTCH


def test_data_and_literature_research_receive_the_english_question(tmp_path, monkeypatch):
    from sci_search.data_research import workflow
    from sci_search.data_research.strategy import validate_strategy
    from sci_search.research_runs import ResearchLimits, ResearchRunManager

    strategy = validate_strategy(
        {
            "route": "both",
            "rationale": "Projections answer part of the question.",
            "measurements": ["glacier runoff"],
            "geography": "Himalaya",
            "start_year": 2000,
            "end_year": 2010,
        }
    )
    asked = []

    def execute(question, *args, **kwargs):
        asked.append(question)
        result = {"kind": "discovered", "status": "blocked", "strategy": strategy}
        result |= {"analyses": [], "limitations": [], "assessments": []}
        args[1].mkdir(parents=True, exist_ok=True)
        workflow.save(args[1] / "analysis.json", result)
        return result

    monkeypatch.setattr(workflow, "execute", execute)

    class Provider:
        name = "fixture"
        queries = []

        def search(self, query, *a, **k):
            self.queries.append(query.text)
            return ()

    provider = Provider()
    manager = ResearchRunManager(tmp_path, providers=(provider,), openalex_api_key="unused")
    state = manager.run_sync(
        DUTCH,
        question_brief={**brief(), "data_research": strategy},
        limits=ResearchLimits(max_full_texts=1),
    )
    assert state["status"] == "complete", state.get("error")
    assert asked == [ENGLISH]
    assert provider.queries and not any("beïnvloedt" in q for q in provider.queries)
    assert state["question"] == DUTCH
