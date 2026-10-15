"""Semantic review rejects extrapolation even when its quote is authentic."""

import json

import pytest

from sci_search.mistral_analysis import ModelAnalyzer

QUOTE = "Cultural affinities explained differences in plant-use composition in Brazil."
GOOD = "Cultural affinities explained plant-use composition differences in Brazil."
BAD = "Cultural affinities cause linguistic diversity throughout South America."


def payload():
    def assertion(text):
        return {
            "text": text,
            "evidence_ids": ["e1"],
            "quotes": [{"evidence_id": "e1", "quote": QUOTE}],
        }

    return {
        "answer": assertion(BAD),
        "claims": [assertion(GOOD), assertion(BAD)],
        **{
            key: []
            for key in (
                "agreements",
                "contradictions",
                "method_differences",
                "limitations",
                "uncertainties",
                "assumptions",
                "knowledge_gaps",
                "entities",
                "measurements",
                "contradiction_groups",
            )
        },
    }


def run_review(mode="mixed", failed_check="entailed", generation=None):
    calls = []

    def complete(body, headers):
        calls.append(body)
        if len(calls) == 1:
            data = generation or payload()
        else:
            if mode == "transport":
                raise TimeoutError("offline")
            request = json.loads(body["messages"][1]["content"])
            assert request["question"] == "What influences plant-use differences?"
            assert request["evidence"][0]["passage"] == QUOTE
            judgments = []
            for item in request["assertions"]:
                judgment = {
                    "id": item["id"],
                    "entailed": True,
                    "causal_direction_valid": True,
                    "geographic_scope_valid": True,
                    "relevant": True,
                    "reason": "Supported by the cited passage.",
                }
                if BAD in str(item):
                    judgment[failed_check] = False
                    judgment["reason"] = "The claim exceeds the source finding."
                judgments.append(judgment)
            if mode == "answer_rejected":
                for item in judgments:
                    item["entailed"] = item["id"] != "answer"
            if mode == "answer_missing":
                judgments = [item for item in judgments if item["id"] != "answer"]
            if mode == "missing":
                judgments = []
            if mode == "invalid":
                for item in judgments:
                    item["entailed"] = "true"
            if mode == "duplicate":
                judgments += judgments
            data = {"judgments": judgments}
        return {
            "choices": [{"message": {"content": json.dumps(data)}}],
            "usage": {"total_tokens": 10},
        }

    result = ModelAnalyzer("test", complete_json=complete).analyze(
        "What influences plant-use differences?",
        [{"id": "e1", "publication_id": "p1", "passage": QUOTE, "statement": QUOTE}],
    )
    return result, calls


@pytest.mark.parametrize(
    "failed_check", ["entailed", "causal_direction_valid", "geographic_scope_valid", "relevant"]
)
def test_unsupported_answer_is_withheld_and_distinct_bounded_findings_remain(failed_check):
    result, calls = run_review(failed_check=failed_check)
    assert [claim["text"] for claim in result["claims"]] == [GOOD]
    assert result["answer"] is None
    assert result["answer_withheld"] is True
    assert result["answer_withheld_reason"]
    assert result["status"] == "coverage_limited"
    assert result["semantic_review"]["status"] == "complete"
    assert len(result["rejected_records"]) == 2
    assert len(calls) == 2
    assert result["semantic_review"]["usage"] == {"total_tokens": 10}
    assert result["usage"] == {"total_tokens": 10}


@pytest.mark.parametrize("mode", ["missing", "invalid", "duplicate", "transport"])
def test_no_unchecked_findings_survive_failed_or_incomplete_review(mode):
    result, calls = run_review(mode)
    assert result["status"] == "unavailable"
    assert result["answer"] is None
    assert result["claims"] == []
    assert result["method"] == "deterministic_extractive_fallback"
    assert result["semantic_review"]["status"] == (
        "unavailable" if mode == "transport" else "complete"
    )
    assert len(result["rejected_records"]) == 3
    assert len(calls) == 2


def test_category_arrays_and_auxiliary_records_cannot_bypass_review():
    from sci_search.claim_support import review_support

    analysis = {
        "answer": {"text": GOOD},
        "claims": [{"text": GOOD, "category": "claims"}, {"text": BAD, "category": "limitations"}],
        "limitations": [{"text": BAD, "category": "limitations"}],
        "contradiction_groups": [{"positions": [{"stance": BAD}], "topic": BAD}],
        "entities": [{"label": "unsupported"}],
        "measurements": [{"metric": "unsupported"}],
    }

    def complete(body, headers):
        request = json.loads(body["messages"][1]["content"])
        judgments = [
            {
                "id": item["id"],
                "entailed": item["id"] in {"answer", "claims:0"},
                "causal_direction_valid": True,
                "geographic_scope_valid": True,
                "relevant": True,
                "reason": "Unsupported extension.",
            }
            for item in request["assertions"]
        ]
        return {"content": json.dumps({"judgments": judgments})}

    review_support(
        analysis,
        "Question",
        [{"id": "e1", "passage": QUOTE}],
        "test",
        complete,
        {},
        lambda response: response["content"],
    )
    assert analysis["answer"]["text"] == GOOD
    assert [item["text"] for item in analysis["claims"]] == [GOOD]
    for category in ("limitations", "entities", "measurements", "contradiction_groups"):
        assert analysis[category] == []
    assert len(analysis["rejected_records"]) == 4


def test_provider_preserves_semantic_failure_audit_and_extractive_packet():
    from sci_search.application.analysis import MistralAnalysisProvider, analyze_evidence

    responses = iter(
        [
            {
                "choices": [{"message": {"content": json.dumps(payload())}}],
                "usage": {"total_tokens": 17},
            },
            {"choices": [{"message": {"content": "not json"}}]},
        ]
    )
    analyzer = ModelAnalyzer("test", complete_json=lambda body, headers: next(responses))
    result = analyze_evidence(
        "Question",
        [{"id": "e1", "publication_id": "p1", "passage": QUOTE, "statement": QUOTE}],
        {},
        MistralAnalysisProvider(analyzer),
    )
    assert result["status"] == "unavailable"
    assert result["fallback_reason"]
    assert result["semantic_review"]["status"] == "unavailable"
    assert result["evidence_packet"]["selected_ids"] == ["e1"]
    assert result["usage"]["total_tokens"] == 17
    assert result["answer"] is None
    assert len(result["rejected_records"]) == 3


@pytest.mark.parametrize("mode", ["answer_rejected", "answer_missing"])
def test_rejected_or_unreviewed_answer_cannot_be_resurrected_from_identical_claim(mode):
    generation = payload()
    generation["answer"] = generation["claims"][0].copy()
    generation["claims"] = [generation["claims"][0]]
    result, _ = run_review(mode, generation=generation)
    assert result["answer"] is None
    assert result["answer_withheld"] is True
    assert result["status"] == "coverage_limited"
    assert [item["text"] for item in result["claims"]] == [GOOD]
    assert result["answer_withheld_reason"]
    assert result["rejected_records"][0]["category"] == "answer"


def test_review_schema_constrains_outer_ids_without_mutating_assertions():
    result, calls = run_review()
    review_body = calls[1]
    request = json.loads(review_body["messages"][1]["content"])
    id_schema = review_body["response_format"]["json_schema"]["schema"]["properties"]["judgments"][
        "items"
    ]["properties"]["id"]
    assert id_schema["enum"] == ["answer", "claims:0", "claims:1"]
    assert all("id" not in item["assertion"] for item in request["assertions"])
    assert result["claims"][0]["id"].startswith("ai-claim:")


def test_concurrent_reviews_keep_dynamic_id_schemas_isolated():
    import copy
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sci_search.claim_support import SUPPORT_SCHEMA, review_support
    from tests.semantic_review_fixtures import reviewed_response

    original = copy.deepcopy(SUPPORT_SCHEMA)
    barrier = Barrier(2)

    def run(claim_count):
        analysis = {
            "answer": {"id": "inner-answer", "text": GOOD},
            "claims": [
                {"id": f"inner-{index}", "text": GOOD, "category": "claims"}
                for index in range(claim_count)
            ],
        }
        bodies = []

        def complete(body, headers):
            bodies.append(body)
            barrier.wait(timeout=5)
            return reviewed_response(body, {})

        review_support(
            analysis,
            "Question",
            [],
            "test",
            complete,
            {},
            lambda response: response["choices"][0]["message"]["content"],
        )
        return bodies[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(run, [1, 2]))
    schemas = [body["response_format"]["json_schema"]["schema"] for body in (first, second)]
    assert schemas[0]["properties"]["judgments"]["items"]["properties"]["id"]["enum"] == [
        "answer",
        "claims:0",
    ]
    assert schemas[1]["properties"]["judgments"]["items"]["properties"]["id"]["enum"] == [
        "answer",
        "claims:0",
        "claims:1",
    ]
    assert SUPPORT_SCHEMA == original
    assert schemas[0] is not schemas[1]
