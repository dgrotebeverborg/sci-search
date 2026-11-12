import json
from dataclasses import replace
from types import SimpleNamespace

from sci_search.metadata_recall import review_metadata_candidates
from tests.test_compound_subject_flow import example


def reviewer(decision, quote):
    def complete(body, headers):
        candidate = json.loads(body["messages"][1]["content"])["candidates"][0]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "decisions": [
                                    {
                                        "id": candidate["id"],
                                        "decision": decision,
                                        "reason": "The title describes off-grid solar steel production.",
                                        "quote": quote,
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    return SimpleNamespace(model="test", api_key="test", complete_json=complete)


def candidate():
    _, plan, base = example()
    paper = replace(
        base,
        title="A fully off-grid green steel production: Integrating concentrated solar power and hydrogen-based direct reduction",
        abstract="",
        full_text_url="https://example.org/source.pdf",
        has_pdf=True,
    )
    return plan, paper


def test_missing_abstract_is_pending_without_a_reviewer():
    plan, paper = candidate()
    result = review_metadata_candidates([paper], plan, analyzer=None)[0]
    assert result.screening_status == "uncertain"
    assert "abstract unavailable" in result.screening_reason


def test_grounded_potential_match_can_reach_full_text_without_being_included():
    plan, paper = candidate()
    result = review_metadata_candidates(
        [paper],
        plan,
        analyzer=reviewer("potentially_relevant", "fully off-grid green steel production"),
    )[0]
    assert result.screening_status == "selected"
    assert "full-text assessment required" in result.screening_reason


def test_unsupported_model_quote_does_not_resolve_uncertainty():
    plan, paper = candidate()
    result = review_metadata_candidates(
        [paper], plan, analyzer=reviewer("unrelated", "This text was invented")
    )[0]
    assert result.screening_status == "uncertain"


def test_retracted_source_is_never_rescued():
    plan, paper = candidate()
    result = review_metadata_candidates(
        [replace(paper, is_retracted=True)],
        plan,
        analyzer=reviewer("potentially_relevant", paper.title),
    )[0]
    assert result.screening_status == "excluded"


def test_budget_limit_keeps_candidates_pending():
    plan, paper = candidate()
    result = review_metadata_candidates(
        [paper], plan, analyzer=reviewer("potentially_relevant", paper.title), max_reviews=0
    )[0]
    assert result.screening_status == "uncertain"
    assert "limit" in result.screening_reason


def test_recovered_metadata_match_is_not_discarded_again_by_literal_fulltext_gate():
    from sci_search.fulltext_screening import screen_full_text

    plan, paper = candidate()
    selected = review_metadata_candidates(
        [paper],
        plan,
        analyzer=reviewer("potentially_relevant", "fully off-grid green steel production"),
    )[0]
    text = "This study evaluates solar powered hydrogen direct reduction of iron. Storage design and steel production costs are compared."
    decision = screen_full_text(plan.question, plan, selected, text)
    assert decision.decision == "uncertain"


def test_potentially_relevant_without_access_is_not_called_unrelated():
    plan, paper = candidate()
    paper = replace(paper, full_text_url=None, has_pdf=False)
    result = review_metadata_candidates(
        [paper],
        plan,
        analyzer=reviewer("potentially_relevant", "fully off-grid green steel production"),
    )[0]
    assert result.screening_status == "unavailable"
    assert "potentially relevant" in result.screening_reason


def test_cached_review_does_not_repeat_model_calls():
    plan, paper = candidate()
    cache = {}
    first = review_metadata_candidates(
        [paper],
        plan,
        analyzer=reviewer("potentially_relevant", "fully off-grid green steel production"),
        cache=cache,
    )

    def fail(*args):
        raise AssertionError("Repeated review")

    second = review_metadata_candidates(
        [paper], plan, analyzer=SimpleNamespace(model="test", complete_json=fail), cache=cache
    )
    assert first == second


def test_unrelated_application_requires_grounded_reason():
    plan, paper = candidate()
    paper = replace(
        paper,
        title="Off-grid hydrogen fuel supply for road vehicles",
        abstract="This study compares hydrogen production systems for road transport.",
    )
    result = review_metadata_candidates(
        [paper],
        plan,
        analyzer=reviewer("unrelated", "hydrogen production systems for road transport"),
    )[0]
    assert result.screening_status == "excluded"
    assert "Metadata quote:" in result.screening_reason


def test_selection_limit_is_distinct_from_relevance_exclusion():
    plan, paper = candidate()
    result = review_metadata_candidates(
        [paper], plan, analyzer=reviewer("potentially_relevant", paper.title), limit=0
    )[0]
    assert result.screening_status == "not_selected"
    assert "selection limit" in result.screening_reason


def test_distinctive_application_is_prioritized_over_generic_energy_matches():
    plan, paper = candidate()
    generic = replace(
        paper, id="general-energy", title="Off-grid solar wind hydrogen supply", abstract=""
    )
    result = review_metadata_candidates(
        [replace(generic, id=f"general-{i}") for i in range(8)] + [paper],
        plan,
        analyzer=reviewer("potentially_relevant", paper.title),
        max_reviews=1,
    )
    by_id = {item.id: item for item in result}
    assert by_id[paper.id].screening_status == "selected"
    assert by_id["general-0"].screening_status == "uncertain"
