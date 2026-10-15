"""A meaning rejection gets one re-selection of codes in the same dataset."""

import json

import pytest

from sci_search.data_research.connectors import base, eurostat, stage
from tests.data_meaning_fixtures import positive_review
from tests.test_connector_stage import STRATEGY, offline, scripted

CANDIDATE = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual")
FIRST = scripted("", {"title": "connector_selection"})
OTHER = {**FIRST, "filters": {**FIRST["filters"], "geo": ["NL", "DE"]}}


def rejected_review(prompt):
    review = positive_review(prompt)
    check = review["measurements"][0]["checks"][0]
    check.update(status="unresolved", reason="The selected field measures forest area only")
    return review


def reviewer(selections, verdicts):
    """Scripted selections and meaning verdicts, in call order; records the selection prompts."""
    prompts = []

    def complete(prompt, schema):
        if set(schema["properties"]) == {"measurements"}:
            return positive_review(prompt) if verdicts.pop(0) else rejected_review(prompt)
        if schema.get("title") == "connector_selection":
            prompts.append(prompt)
            return selections.pop(0)
        return scripted(prompt, schema)

    return complete, prompts


def analyse(tmp_path, complete, fetch=offline, check_cancelled=lambda: None):
    return stage.analyse_dataset(
        "How has life expectancy changed?",
        STRATEGY,
        tmp_path,
        eurostat,
        CANDIDATE,
        "life expectancy at birth",
        complete=complete,
        fetch=fetch,
        post=None,
        check_cancelled=check_cancelled,
        progress=lambda m: None,
    )


def test_a_different_selection_after_a_meaning_rejection_is_reviewed_and_accepted(tmp_path):
    complete, prompts = reviewer([FIRST, OTHER], [False, True])
    analysis, assessment = analyse(tmp_path, complete)
    assert analysis is not None, assessment
    assert assessment["decision"] == "analysed"
    assert assessment["selection"]["filters"]["geo"] == ["NL", "DE"]
    rejection = json.loads(prompts[1].split("\n", 1)[1])["previous_rejection"]
    assert rejection["selection"]["filters"]["geo"] == ["NL", "DE", "EL"]
    assert "forest area only" in rejection["reason"]
    assert [r["accepted"] for r in assessment["semantic_reviews"]] == [False, True]
    assert {"class": "meaning", "action": "reselect", "outcome": "accepted"} in assessment[
        "recovery"
    ]
    assert list(tmp_path.rglob("semantic-review-rejected-1.json"))


def test_repeating_the_rejected_selection_ends_the_dataset_without_a_second_fetch(tmp_path):
    complete, _ = reviewer([FIRST, FIRST], [False])
    data_requests = []

    def counting(url):
        if "/data/demo_mlexpec/" in url and "serieskeysonly" not in url:
            data_requests.append(url)
        return offline(url)

    analysis, assessment = analyse(tmp_path, complete, fetch=counting)
    assert analysis is None
    assert len(data_requests) == 1
    assert "Measurement meaning not confirmed" in assessment["reason"]
    assert assessment["recovery"][-1]["outcome"] == "no other codes"


def test_a_second_rejection_ends_the_dataset_after_one_reselection(tmp_path):
    complete, prompts = reviewer([FIRST, OTHER], [False, False])
    analysis, assessment = analyse(tmp_path, complete)
    assert analysis is None
    assert len(prompts) == 2
    assert len(assessment["semantic_reviews"]) == 2
    assert assessment["recovery"][-1]["outcome"] == "rejected again"
    assert assessment["failure_stage"] == "connector:meaning"


def test_cancellation_during_a_reselection_propagates(tmp_path):
    from sci_search.research_runs import ResearchCancelled

    complete, prompts = reviewer([FIRST, OTHER], [False, True])

    def cancelled_after_the_first_review():
        if len(prompts) == 1 and list(tmp_path.rglob("semantic-review-rejected-1.json")):
            raise ResearchCancelled("Research cancelled")

    with pytest.raises(ResearchCancelled):
        analyse(tmp_path, complete, check_cancelled=cancelled_after_the_first_review)
