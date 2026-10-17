"""A cited scope-to-series relation survives coverage without changing source identity."""

import copy

import pytest

from sci_search.data_research import coverage, coverage_bindings


def fixture():
    scope = {
        "measurements": ["price"],
        "countries": ["NLD"],
        "start_year": 2020,
        "end_year": 2021,
        "requirements": [
            {
                "measurement": "price",
                "definition": "Municipal sale price",
                "entities": ["Delft municipality"],
                "breakdowns": [],
            }
        ],
    }
    analysis = {
        "source": {"sha256": "source-one"},
        "semantic_review": {"accepted": True},
        "series": [
            {
                "label": "price",
                "entity": "Delft",
                "unit": "euro",
                "identity": {"geography": "Delft", "dimensions": {}},
                "annual": [{"year": 2020, "value": 100}, {"year": 2021, "value": 120}],
            }
        ],
    }
    documents = {"selection": "Municipality GM0503 = Delft"}
    return scope, analysis, documents


def proposal(prompt, schema):
    return {
        "bindings": [
            {
                "cell": 0,
                "series": 0,
                "relation": "equivalent",
                "reason": "The municipality code identifies the requested entity.",
                "evidence": ["selection:0"],
            }
        ]
    }


def bind(scope, analysis, documents, complete=proposal):
    analysis["semantic_review"]["coverage_bindings"] = coverage_bindings.assess(
        scope=scope, analysis=analysis, documents=documents, complete=complete
    )


def test_cited_binding_resolves_missing_entity_without_rewriting_source():
    scope, analysis, docs = fixture()
    original = copy.deepcopy(analysis["series"])
    assert coverage.evaluate(scope, [analysis])["gaps"]
    bind(scope, analysis, docs)
    assert coverage.evaluate(scope, [analysis])["complete_measurements"] == ["price"]
    assert analysis["series"] == original
    assert analysis["semantic_review"]["coverage_bindings"]["bindings"][0]["evidence"]


@pytest.mark.parametrize("change", ["source", "identity", "definition", "category", "rejected"])
def test_binding_cannot_be_reused_for_changed_input_or_requirement(change):
    scope, analysis, docs = fixture()
    bind(scope, analysis, docs)
    if change == "source":
        analysis["source"]["sha256"] = "other"
    if change == "identity":
        analysis["series"][0]["identity"]["geography"] = "Delft province"
    if change == "definition":
        scope["requirements"][0]["definition"] = "Provincial sale price"
    if change == "category":
        scope["requirements"][0]["breakdowns"] = [{"dimension": "sex", "values": ["female"]}]
    if change == "rejected":
        analysis["semantic_review"]["accepted"] = False
    assert not coverage.evaluate(scope, [analysis])["complete_measurements"]


@pytest.mark.parametrize("relation", ["narrower", "conflicting", "unresolved"])
def test_narrower_and_uncertain_relations_never_cover_the_requested_cell(relation):
    scope, analysis, docs = fixture()

    def complete(prompt, schema):
        result = proposal(prompt, schema)
        result["bindings"][0]["relation"] = relation
        return result

    bind(scope, analysis, docs, complete)
    assert coverage.evaluate(scope, [analysis])["gaps"]


@pytest.mark.parametrize("fault", ["quote", "document", "series", "cell", "duplicate", "summary"])
def test_bad_binding_evidence_fails_closed(fault):
    scope, analysis, docs = fixture()

    def complete(prompt, schema):
        result = proposal(prompt, schema)
        item = result["bindings"][0]
        if fault == "quote":
            item["evidence"][0] = "invented:0"
        if fault == "document":
            item["evidence"][0] = "unknown:0"
        if fault == "series":
            item["series"] = 20
        if fault == "cell":
            item["cell"] = 20
        if fault == "duplicate":
            result["bindings"].append(copy.deepcopy(item))
        if fault == "summary":
            item["evidence"][0] = "table_summary:0"
        return result

    docs["table_summary"] = docs["selection"]
    bind(scope, analysis, docs, complete)
    assert coverage.evaluate(scope, [analysis])["gaps"]


def test_binding_does_not_hide_missing_years_or_conflicting_sources():
    scope, analysis, docs = fixture()
    bind(scope, analysis, docs)
    analysis["series"][0]["annual"].pop()
    result = coverage.evaluate(scope, [analysis])
    assert result["gaps"][0]["missing_years"] == [2021]
    other = copy.deepcopy(analysis)
    other["source"]["sha256"] = "source-two"
    other["series"][0]["annual"][0]["value"] = 999
    bind(scope, other, docs)
    assert coverage.evaluate(scope, [analysis, other])["gaps"][0]["conflicts"]


def test_matching_legacy_source_needs_no_additional_model_call():
    scope, analysis, docs = fixture()
    scope["requirements"][0]["entities"] = ["Delft"]

    def forbidden(*args):
        raise AssertionError("No review needed")

    bind(scope, analysis, docs, forbidden)
    assert coverage.evaluate(scope, [analysis])["complete_measurements"] == ["price"]


def test_semantic_assessment_retains_binding_for_downstream_coverage():
    from sci_search.data_research import semantics

    scope, analysis, docs = fixture()

    def complete(prompt, schema):
        if "bindings" in schema["properties"]:
            return proposal(prompt, schema)
        return {
            "measurements": [
                {
                    "measurement": "price",
                    "transformation": "direct",
                    "checks": [
                        {
                            "aspect": aspect,
                            "status": "supported",
                            "reason": "Documented",
                            "evidence": [{"document": "selection", "quote": docs["selection"]}],
                        }
                        for aspect in semantics.ASPECTS
                    ],
                    "followup_question": "",
                }
            ]
        }

    analysis["semantic_review"] = semantics.assess(
        question="Municipal sale prices",
        scope=scope,
        analysis=analysis,
        documents=docs,
        complete=complete,
    )
    assert coverage.evaluate(scope, [analysis])["complete_measurements"] == ["price"]


def test_equivalent_sex_encodings_do_not_hide_conflicting_values():
    scope, left, docs = fixture()
    scope["requirements"][0]["breakdowns"] = [{"dimension": "sex", "values": ["male"]}]
    left["series"][0]["identity"]["dimensions"]["sex"] = "M"
    right = copy.deepcopy(left)
    right["source"]["sha256"] = "other"
    right["series"][0]["identity"]["dimensions"]["sex"] = "male"
    right["series"][0]["annual"][0]["value"] = 999
    bind(scope, left, docs)
    bind(scope, right, docs)
    assert coverage.evaluate(scope, [left, right])["gaps"][0]["conflicts"]


def test_one_series_cannot_represent_disjoint_requested_categories():
    scope, analysis, docs = fixture()
    scope["requirements"][0]["breakdowns"] = [{"dimension": "sex", "values": ["male", "female"]}]

    def complete(prompt, schema):
        result = proposal(prompt, schema)
        result["bindings"].append({**copy.deepcopy(result["bindings"][0]), "cell": 1})
        return result

    bind(scope, analysis, docs, complete)
    assert all(c["status"] == "missing" for c in coverage.evaluate(scope, [analysis])["cells"])


def test_definition_selection_can_use_bound_source_without_changing_definition():
    scope, analysis, docs = fixture()
    scope["requirements"][0]["definition_policy"] = "choose_documented"
    analysis["execution"] = {"status": "verified"}
    analysis["semantic_review"]["measurements"] = [
        {
            "measurement": "price",
            "checks": [
                {
                    "aspect": "definition",
                    "status": "supported",
                    "evidence": [{"quote": docs["selection"]}],
                }
            ],
        }
    ]
    bind(scope, analysis, docs)
    assert coverage.evaluate(scope, [analysis])["complete_measurements"] == ["price"]


def test_existing_assignment_cannot_be_reused_for_another_category():
    scope, analysis, docs = fixture()
    scope["requirements"][0]["entities"] = ["Delft"]
    scope["requirements"][0]["breakdowns"] = [{"dimension": "sex", "values": ["male", "female"]}]
    analysis["series"][0]["identity"]["dimensions"]["sex"] = "male"
    bind(scope, analysis, docs)
    cells = coverage.evaluate(scope, [analysis])["cells"]
    assert [(c["dimensions"]["sex"], c["status"]) for c in cells] == [
        ("male", "complete"),
        ("female", "missing"),
    ]


def test_mutating_scope_does_not_mutate_saved_judgment():
    scope, analysis, docs = fixture()
    bind(scope, analysis, docs)
    scope["countries"][:] = ["BEL"]
    assert coverage.evaluate(scope, [analysis])["gaps"]


def test_bound_series_in_one_source_still_report_conflicts():
    scope, analysis, docs = fixture()
    other = copy.deepcopy(analysis["series"][0])
    other["entity"] = "GM0503"
    other["annual"][0]["value"] = 999
    analysis["series"].append(other)

    def complete(prompt, schema):
        result = proposal(prompt, schema)
        result["bindings"].append({**copy.deepcopy(result["bindings"][0]), "series": 1})
        return result

    bind(scope, analysis, docs, complete)
    assert coverage.evaluate(scope, [analysis])["gaps"][0]["conflicts"]


def test_component_binding_survives_merged_analysis():
    scope, analysis, docs = fixture()
    bind(scope, analysis, docs)
    merged = {**analysis, "semantic_review": {"accepted": True}, "components": [analysis]}
    assert coverage.evaluate(scope, [merged])["complete_measurements"] == ["price"]


def test_country_missing_from_source_does_not_spend_a_binding_call():
    scope, analysis, docs = fixture()
    scope["requirements"][0].update(entities=[], breakdowns=[])
    scope["countries"] = ["NLD", "BEL"]
    analysis["series"][0]["entity"] = "Netherlands"
    analysis["series"][0]["identity"]["geography"] = "Netherlands"

    def forbidden(*args):
        raise AssertionError("An absent country cannot be recovered by matching")

    bind(scope, analysis, docs, forbidden)
    assert len(coverage.evaluate(scope, [analysis])["gaps"]) == 1


def test_binding_budget_exhaustion_preserves_accepted_raw_analysis():
    from sci_search.data_research import semantics
    from sci_search.data_research.run_control import BudgetExhausted

    scope, analysis, docs = fixture()

    def exhausted(*args):
        raise BudgetExhausted("Data investigation budget exhausted")

    semantics.bind_coverage(
        analysis["semantic_review"],
        scope=scope,
        analysis=analysis,
        documents=docs,
        complete=exhausted,
    )
    assert analysis["semantic_review"]["accepted"] is True
    assert coverage.evaluate(scope, [analysis])["gaps"]
