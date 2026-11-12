"""Generation, authenticity validation and support review share the same evidence."""

import json
from pathlib import Path

import pytest

from sci_search.mistral_analysis import ModelAnalyzer, validate_analysis
from tests.semantic_review_fixtures import reviewed_response


def generation(evidence_id, quote, text="The cohort reported lower diabetes incidence."):
    return {
        "answer": {
            "text": text,
            "evidence_ids": [evidence_id],
            "quotes": [{"evidence_id": evidence_id, "quote": quote}],
        },
        **{
            key: []
            for key in (
                "claims",
                "agreements",
                "contradictions",
                "method_differences",
                "limitations",
                "uncertainties",
                "assumptions",
                "knowledge_gaps",
                "entities",
                "measurements",
            )
        },
    }


def test_norfolk_incidence_quote_outside_mediation_statement_reaches_support_review():
    packet = json.loads(
        (Path(__file__).parents[1] / "benchmarks/gpt_health_reference_v1.json").read_text()
    )
    evidence = next(item for item in packet["evidence"] if item["id"] == "health_norfolk")
    quote = "Individuals living in the greenest neighbourhood quartile had a 19% lower relative hazard of developing diabetes"
    assert quote in evidence["passage"] and quote not in evidence["statement"]
    calls = []
    response = {
        "choices": [{"message": {"content": json.dumps(generation(evidence["id"], quote))}}]
    }

    def complete(body, headers):
        calls.append(body)
        return reviewed_response(body, response)

    result = ModelAnalyzer("test", complete_json=complete).analyze(packet["question"], [evidence])
    assert result["answer"]["quotes"][0]["quote"] == quote
    assert result["semantic_review"]["reviewed_records"] == 1
    assert len(calls) == 2


def test_support_review_receives_identical_bounded_context_including_title():
    quote = "Lower incident diabetes was associated with tree canopy."
    source = {
        "id": "e1",
        "publication_id": "p1",
        "passage": quote + " x" * 2600 + "Unseen context.",
        "statement": quote,
        "publication_title": "A longitudinal study of 46 786 Australians",
        "study_design": "observational cohort",
        "locations": ["Australia"],
    }
    calls = []
    response = {"choices": [{"message": {"content": json.dumps(generation("e1", quote))}}]}

    def complete(body, headers):
        calls.append(json.loads(body["messages"][1]["content"]))
        return reviewed_response(body, response)

    ModelAnalyzer("test", complete_json=complete).analyze(
        "Is green space associated with diabetes?", [source]
    )
    assert calls[1]["evidence"] == calls[0]["evidence"]
    assert calls[1]["evidence"][0]["publication_title"] == source["publication_title"]
    assert "Unseen context" not in calls[1]["evidence"][0]["passage"]


def test_quote_in_unsupplied_tail_is_rejected_before_semantic_review():
    quote = "This result is outside the supplied evidence window."
    evidence = [{"id": "e1", "passage": "x" * 2500 + quote, "statement": quote}]
    with pytest.raises(ValueError, match="not present in its source passage"):
        validate_analysis(generation("e1", quote), evidence)


@pytest.mark.parametrize(
    "quote", ["A fabricated source finding.", "A longitudinal study of Australians"]
)
def test_fabrication_and_title_only_quotes_cannot_pass_authenticity(quote):
    evidence = [
        {
            "id": "e1",
            "publication_title": "A longitudinal study of Australians",
            "passage": "Tree canopy was associated with lower incidence.",
        }
    ]
    with pytest.raises(ValueError, match="not present in its source passage"):
        validate_analysis(generation("e1", quote), evidence)


@pytest.mark.parametrize(
    ("text", "failed_check"),
    [
        ("Tree canopy reduced mortality in this cohort.", "entailed"),
        ("Tree canopy caused the decrease in diabetes incidence.", "causal_direction_valid"),
        ("The background hypothesis was established by this study.", "entailed"),
    ],
)
def test_authentic_unselected_quotes_still_require_semantic_support(text, failed_check):
    quote = "Tree canopy was associated with lower diabetes incidence."
    evidence = [
        {
            "id": "e1",
            "publication_id": "p1",
            "publication_title": "Tree canopy and diabetes in an Australian cohort",
            "statement": "The mechanism remains uncertain.",
            "passage": quote + " The mechanism remains uncertain.",
        }
    ]
    data = generation("e1", quote, text=text)

    def complete(body, headers):
        if body["response_format"]["json_schema"]["name"] == "scientific_analysis":
            return {"choices": [{"message": {"content": json.dumps(data)}}]}
        judgment = {
            "id": "answer",
            "entailed": True,
            "causal_direction_valid": True,
            "geographic_scope_valid": True,
            "relevant": True,
            "reason": "The authentic quotation does not support the asserted finding.",
        }
        judgment[failed_check] = False
        return {"choices": [{"message": {"content": json.dumps({"judgments": [judgment]})}}]}

    result = ModelAnalyzer("test", complete_json=complete).analyze(
        "What did the cohort find?", evidence
    )
    assert result["answer"] is None
    assert result["status"] == "unavailable"
    assert result["semantic_review"]["rejected_records"] == 1
    assert result["rejected_records"][0]["stage"] == "semantic_support"


def test_complete_synthesis_and_final_caveat_fit_answer_schema_and_survive_review():
    packet = json.loads(
        (Path(__file__).parents[1] / "benchmarks/gpt_health_reference_v1.json").read_text()
    )
    evidence = packet["evidence"][:3]
    answer = (
        "The supplied observational cohorts report associations between greener residential "
        "environments and lower diabetes incidence, with differences by exposure measure. "
        "MESA reported lower diabetes risk with increasing greenspace. The older-adult cohort "
        "reported a lower relative hazard in the greenest neighbourhood quartile, but its tested "
        "physical-activity pathway was not statistically significant. The Australian study found "
        "lower odds of incident diabetes with greater tree canopy, but not total green space. "
        "These observational associations do not establish that green space causes lower diabetes risk."
    )
    assert len(answer) > 500
    data = generation(evidence[0]["id"], evidence[0]["statement"], text=answer)
    data["answer"]["evidence_ids"] = [item["id"] for item in evidence]
    data["answer"]["quotes"] = [
        {"evidence_id": item["id"], "quote": item["statement"]} for item in evidence
    ]
    data["answer"]["quotes"][1]["quote"] = (
        "Individuals living in the greenest neighbourhood quartile had a 19% lower relative "
        "hazard of developing diabetes (HR 0.81; 95% CI 0.67, 0.99; p = 0.035; linear trend p = 0.010)."
    )

    def complete(body, headers):
        if body["response_format"]["json_schema"]["name"] == "scientific_analysis":
            schema = body["response_format"]["json_schema"]["schema"]
            answer_def = schema["$defs"][schema["properties"]["answer"]["$ref"].split("/")[-1]]
            claim_ref = schema["properties"]["claims"]["items"]["$ref"].split("/")[-1]
            assert len(answer) <= answer_def["properties"]["text"]["maxLength"]
            assert schema["$defs"][claim_ref]["properties"]["text"]["maxLength"] == 500
        response = {"choices": [{"message": {"content": json.dumps(data)}}]}
        return reviewed_response(body, response)

    result = ModelAnalyzer("test", complete_json=complete).analyze(packet["question"], evidence)
    assert result["answer"]["text"] == answer
    assert result["answer"]["text"].endswith("causes lower diabetes risk.")
    assert result["semantic_review"]["accepted_records"] == 1
