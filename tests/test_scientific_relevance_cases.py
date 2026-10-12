"""Offline scientific judgment checks, not a live-model accuracy estimate.

The reusable JSON contains synthetic vignettes, never invented publications.
Removing confirmed scope, admitting topic-only matches, requiring every driver
in each paper, or dropping task intent should each break these expectations.
"""

import json
from pathlib import Path

import pytest

from sci_search.discovery import PublicationCandidate, plan_search_queries
from sci_search.fulltext_screening import screen_full_text
from sci_search.question_planning import plan_from_brief

BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "benchmarks/relevance_cases_v1.json"


@pytest.fixture(scope="module")
def benchmark():
    assert BENCHMARK_PATH.exists(), "The reusable scientific relevance cases are missing"
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def test_benchmark_has_honest_provenance_and_contrasting_judgments(benchmark):
    assert benchmark["source_type"] == "synthetic_vignettes"
    assert 4 <= len(benchmark["cases"]) <= 6
    ids = [case["id"] for case in benchmark["cases"]]
    assert len(ids) == len(set(ids))
    for case in benchmark["cases"]:
        assert {source["expected_included"] for source in case["sources"]} == {True, False}
        assert {claim["supported"] for claim in case["assertion_examples"]} == {True, False}
        sources = {source["id"]: source for source in case["sources"]}
        for source in sources.values():
            assert source["synthetic"] is True
            assert source["rationale"]
            assert not source.get("doi") and not source.get("source_url")
        for claim in case["assertion_examples"]:
            assert claim["source_id"] in sources
            assert claim["rationale"]


@pytest.mark.parametrize("case_index", range(5))
def test_confirmed_scientific_scope_survives_query_planning(benchmark, case_index):
    case = benchmark["cases"][case_index]
    plan = plan_from_brief(case["question"], {
        "original_question": case["question"], "research_plan": case["research_plan"]
    })
    actual_plan, queries = plan_search_queries(case["question"], plan=plan)
    assert actual_plan.intent == case["research_plan"]["intent"], case["id"]
    texts = [query.text.casefold() for query in queries]
    for term in case["research_plan"]["subject_terms"]:
        assert any(term.casefold() in text for text in texts), (case["id"], term, texts)
    for term in case["research_plan"]["geography_terms"]:
        assert any(term.casefold() in text for text in texts), (case["id"], term, texts)
    assert any(case["expected_query_purpose"] == query.purpose for query in queries), (
        case["id"], [(query.text, query.purpose) for query in queries]
    )


@pytest.mark.parametrize("case_index", range(5))
def test_full_text_scientific_inclusion_decisions(benchmark, case_index):
    case = benchmark["cases"][case_index]
    plan = plan_from_brief(case["question"], {
        "original_question": case["question"], "research_plan": case["research_plan"]
    })
    failures = []
    for source in case["sources"]:
        candidate = PublicationCandidate(
            id=source["id"], title=source["title"], abstract=source["abstract"],
            year=None, doi=None, authors=(), publication_type="synthetic_vignette",
            source_url=None,
        )
        result = screen_full_text(case["question"], plan, candidate, source["full_text"])
        if (result.decision == "included") != source["expected_included"]:
            failures.append(
                f"{source['id']}: expected included={source['expected_included']}; "
                f"got {result.decision}: {result.reason}. Scientific rationale: "
                f"{source['rationale']}"
            )
    assert not failures, case["id"] + "\n" + "\n".join(failures)
