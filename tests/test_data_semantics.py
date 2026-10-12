"""Publication requires grounded meaning, independently of successful arithmetic."""

import copy

import pytest

from sci_search.data_research import semantics


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


DOCUMENTS = {
    "metadata": "Population counts residents in people in the Netherlands at 1 January of the reporting year."
}


def judgment(measurement="population"):
    return {
        "measurement": measurement,
        "transformation": "direct",
        "checks": [
            {
                "aspect": aspect,
                "status": "supported",
                "reason": "Explicit definition",
                "evidence": [{"document": "metadata", "quote": DOCUMENTS["metadata"]}],
            }
            for aspect in ("definition", "unit", "geography", "time", "calculation")
        ],
        "followup_question": "",
    }


def test_grounded_meaning_is_retained_with_exact_source_quotes():
    result = semantics.validate({"measurements": [judgment()]}, ["population"], DOCUMENTS)
    assert result["accepted"] is True
    assert result["measurements"][0]["checks"][0]["evidence"][0]["quote"] == DOCUMENTS["metadata"]


@pytest.mark.parametrize("aspect", ["definition", "unit", "geography", "time", "calculation"])
def test_uncertain_meaning_blocks_even_with_positive_overall_model_verdict(aspect):
    item = judgment()
    check = next(c for c in item["checks"] if c["aspect"] == aspect)
    check.update(status="unresolved", reason="Needs source documentation")
    item["followup_question"] = "What exactly does this variable measure?"
    result = semantics.validate(
        {"accepted": True, "measurements": [item]}, ["population"], DOCUMENTS
    )
    assert not result["accepted"]
    assert aspect in result["reason"]
    assert result["followup_questions"] == ["What exactly does this variable measure?"]


@pytest.mark.parametrize(
    "mutation",
    [
        "fabricated",
        "script_as_source",
        "missing_measurement",
        "missing_aspect",
        "duplicate",
        "empty",
    ],
)
def test_incomplete_or_fabricated_evidence_cannot_pass(mutation):
    item = judgment()
    review = {"measurements": [item]}
    if mutation == "fabricated":
        item["checks"][0]["evidence"][0]["quote"] = "A statement not present in the actual document"
    if mutation == "script_as_source":
        item["checks"][0]["evidence"][0]["document"] = "code"
    if mutation == "missing_measurement":
        item["measurement"] = "capacity"
    if mutation == "missing_aspect":
        item["checks"].pop()
    if mutation == "duplicate":
        review["measurements"].append(copy.deepcopy(item))
    if mutation == "empty":
        item["checks"][0]["evidence"] = []
    assert not semantics.validate(review, ["population"], DOCUMENTS)["accepted"]


def test_conflicting_component_definitions_block_derived_total():
    item = judgment("total coral cover")
    item["transformation"] = "derived"
    item["checks"][-1].update(
        status="conflicting",
        reason="Both columns are defined as live coral; addition may double count.",
    )
    result = semantics.validate({"measurements": [item]}, ["total coral cover"], DOCUMENTS)
    assert not result["accepted"]
    assert "double count" in result["reason"]


def test_one_supported_measure_does_not_validate_another():
    result = semantics.validate(
        {"measurements": [judgment()]}, ["population", "energy consumption"], DOCUMENTS
    )
    assert not result["accepted"]
    assert "energy consumption" in result["reason"]


def test_executed_python_without_definition_evidence_is_not_published(tmp_path):
    from sci_search.data_research.python_recovery import recover
    from tests.test_python_data_recovery import CODE, SCOPE, SOURCE

    def model(prompt, schema):
        if "code" in schema["properties"]:
            return {"code": CODE, "explanation": "Read actual values"}
        if "action" in schema["properties"]:
            return {"action": "stop", "measurements": [], "reason": "Needs documentation"}
        return {"accepted": True, "reason": "Numbers look plausible", "limitations": []}

    with pytest.raises(ValueError, match="measurement review missing"):
        recover(
            "Population",
            SCOPE,
            b'{"values":{"2001":9}}',
            SOURCE,
            tmp_path,
            complete=model,
            reason="Nested data",
        )
    assert not (tmp_path / "observations.json").exists()
    assert (tmp_path / "python/attempt-1/output/observations.json").exists()


def test_standard_csv_cannot_bypass_meaning_check(tmp_path):
    from sci_search.data_research.workflow import execute
    from tests.test_autonomous_data import mapping, strategy

    def model(prompt, schema):
        properties = schema["properties"]
        if "adapter" in properties:
            return dict(
                adapter="csv",
                download_link_index=-1,
                reason="Population",
                definition_quote="",
                license_note="unknown",
                covered_measurements=["population"],
            )
        if "mapping" in properties:
            return dict(
                suitable=True,
                reason="Population",
                unit_evidence="Population (people)",
                measurement="population",
                mapping={**mapping(), "value_column": "Population (people)"},
            )
        if "measurements" in properties and "action" not in properties:
            item = judgment()
            item["checks"][0].update(
                status="unresolved", reason="Resident versus registered population is undefined"
            )
            return {"measurements": [item]}
        if "action" in properties:
            return dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                measurements=[],
                reason="Need definitions",
            )
        if "code" in properties:
            return dict(
                code="raise ValueError('No definitions')", explanation="Cannot infer definition"
            )
        raise AssertionError(properties)

    result = execute(
        "Population",
        strategy(),
        tmp_path,
        complete=model,
        search=lambda *a, **k: {
            "candidates": [
                {
                    "url": "https://example.test/data.csv",
                    "title": "Population",
                    "publisher": "Stats",
                }
            ]
        },
        fetch=lambda url: (
            b"Year,Country,Population (people)\n2001,Netherlands,9\n",
            "text/csv",
            url,
        ),
    )
    assert not result["analyses"]
    assert result["assessments"][0]["semantic_reviews"][0]["accepted"] is False


def test_missing_definition_triggers_documentation_and_retained_source_reassessment(tmp_path):
    import json

    from sci_search.data_research.workflow import execute
    from tests.test_python_data_recovery import CODE

    method = DOCUMENTS["metadata"]
    actions = 0

    def model(prompt, schema):
        nonlocal actions
        fields = schema["properties"]
        if "adapter" in fields:
            return dict(
                adapter="python",
                download_link_index=0,
                reason="Nested population data",
                definition_quote="",
                license_note="unknown",
                covered_measurements=["population"],
            )
        if "code" in fields:
            return dict(code=CODE, explanation="Read actual source values")
        if "accepted" in fields:
            context = json.loads(prompt.split("\n", 1)[1])
            item = judgment()
            if method not in context["evidence_documents"]["metadata"]:
                item["checks"][0].update(status="unresolved", reason="Definition missing")
                item["followup_question"] = "Does population count residents at 1 January?"
            return dict(
                accepted=True, reason="Script executed", limitations=[], measurements=[item]
            )
        if "source_index" in fields:
            actions += 1
            if actions == 1:
                assert "Does population count residents" in prompt
                return dict(
                    action="reassess",
                    source_index=0,
                    link_index=1,
                    query="",
                    measurements=["population"],
                    reason="Consult observed methods documentation",
                )
            return dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                measurements=[],
                reason="Resolved",
            )
        return dict(action="stop", measurements=[], reason="Code cannot fix a missing definition")

    pages = {
        "https://example.test/page": (
            b'<html>Population <a href="/data.json">Data</a><a href="/methods">Methods</a></html>',
            "text/html",
        ),
        "https://example.test/data.json": (b'{"values":{"2001":9}}', "application/json"),
        "https://example.test/methods": (method.encode(), "text/plain"),
    }
    result = execute(
        "Population",
        dict(
            route="data",
            rationale="Trend",
            geography="Netherlands",
            measurements=["population"],
            start_year=2001,
            end_year=2001,
        ),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.test/page", title="Population", publisher="Stats")
            ]
        },
        fetch=lambda url: (*pages[url], url),
        complete=model,
    )
    assert len(result["analyses"]) == 1, result["assessments"]
    assert result["analyses"][0]["series"][0]["annual"][0]["value"] == 9
    assert result["analyses"][0]["semantic_review"]["accepted"] is True
    assert result["research_process"]["steps"][0]["outcome"]["status"] == "retained"
    assert not (tmp_path / "source-1/observations.json").exists()
    assert (tmp_path / "source-1/python/attempt-1/output/observations.json").exists()
    assert (tmp_path / "source-1-review-1/documentation.bin").read_text() == method


@pytest.mark.parametrize("reflection_failure", [False, True])
def test_semantic_rejection_cannot_be_repaired_by_rerunning_code(tmp_path, reflection_failure):
    from sci_search.data_research.python_recovery import recover
    from tests.test_python_data_recovery import CODE, SCOPE, SOURCE

    def model(prompt, schema):
        if "code" in schema["properties"]:
            return dict(code=CODE, explanation="Read actual values")
        if "action" in schema["properties"]:
            if reflection_failure:
                raise ValueError("Reviewer unavailable")
            return dict(action="repair", measurements=[], reason="Try the same calculation again")
        item = judgment()
        item["checks"][0].update(status="conflicting", reason="Source definitions conflict")
        return dict(
            accepted=False,
            reason="Source definitions conflict",
            limitations=[],
            measurements=[item],
        )

    with pytest.raises(ValueError, match="Source definitions conflict"):
        recover(
            "Population",
            SCOPE,
            b'{"values":{"2001":9}}',
            SOURCE,
            tmp_path,
            complete=model,
            reason="Nested data",
            metadata=DOCUMENTS["metadata"],
        )
    assert not (tmp_path / "python/attempt-2").exists()


def test_unresolved_measurement_does_not_discard_a_supported_measurement(tmp_path):
    from sci_search.data_research.workflow import execute
    from tests.data_meaning_fixtures import positive_review
    from tests.test_autonomous_data import mapping, strategy

    def model(prompt, schema):
        fields = schema["properties"]
        if "adapter" in fields:
            return dict(
                adapter="csv",
                download_link_index=-1,
                reason="Annual table",
                definition_quote="",
                license_note="unknown",
                covered_measurements=["population", "energy use"],
            )
        if "mapping" in fields:
            energy = '"measurements": ["energy use"]' in prompt
            label, column = (
                ("energy use", "Capacity MW") if energy else ("population", "Population people")
            )
            return dict(
                suitable=True,
                reason="Map field",
                measurement=label,
                unit_evidence=column,
                mapping={
                    **mapping(),
                    "label": label,
                    "value_column": column,
                    "unit": "MW" if energy else "people",
                    "output_unit": "MW" if energy else "people",
                },
            )
        if set(fields) == {"measurements"}:
            review = positive_review(prompt)
            if review["measurements"][0]["measurement"] == "energy use":
                review["measurements"][0]["checks"][0].update(
                    status="conflicting", reason="Installed capacity does not measure energy used"
                )
            return review
        return dict(
            action="stop",
            source_index=-1,
            link_index=-1,
            query="",
            measurements=[],
            reason="Separate use data needed",
        )

    result = execute(
        "Population and energy use",
        {**strategy(), "measurements": ["population", "energy use"]},
        tmp_path,
        complete=model,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.test/data.csv", title="Annual data", publisher="Stats")
            ]
        },
        fetch=lambda url: (
            b"Year,Country,Population people,Capacity MW\n2001,Netherlands,9,100\n",
            "text/csv",
            url,
        ),
    )
    assert result["uncovered_measurements"] == ["energy use"]
    assert [s["label"] for s in result["analyses"][0]["series"]] == ["population"]
    assert result["analyses"][0]["series"][0]["annual"][0]["value"] == 9
    assert [r["accepted"] for r in result["assessments"][0]["semantic_reviews"]] == [True, False]
