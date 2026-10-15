"""Documented subpopulations may be shown, but never fulfil the broader measurement."""

import json

import pytest

from sci_search.data_research.coverage import evaluate
from sci_search.data_research.python_rows import analyse_observations, measurement_definitions

SCOPE = {
    "measurements": ["population"],
    "geography": "Netherlands",
    "start_year": 2020,
    "end_year": 2020,
}
DEFINITION = {
    "requested_measurement": "population",
    "label": "adult population",
    "definition": "Residents aged 18 or older.",
    "relation": "narrower",
}
PAYLOAD = {
    "measurement_definitions": [DEFINITION],
    "observations": [
        {
            "measurement": "population",
            "entity": "Netherlands",
            "year": 2020,
            "value": 12,
            "unit": "people",
            "source_reference": "/value",
            "source_locator": {"format": "json", "path": ["value"]},
        }
    ],
}


@pytest.mark.parametrize("payload", [None, [], 3, "text"])
def test_nonobject_extraction_is_a_recoverable_validation_error(payload):
    with pytest.raises(ValueError):
        measurement_definitions(payload, SCOPE)


def test_narrower_series_keeps_its_actual_label_and_does_not_close_broad_gap():
    result = analyse_observations(PAYLOAD, SCOPE)
    series = result["series"][0]
    assert series["label"] == "adult population"
    assert series["requested_measurement"] == "population"
    assert series["coverage_relation"] == "narrower"
    assert series["annual"][0]["value"] == 12
    assert evaluate(SCOPE, [result])["complete_measurements"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"label": "population"},
        {"requested_measurement": "income"},
        {"relation": "proxy"},
        {"definition": ""},
    ],
)
def test_invalid_subset_declarations_are_rejected(change):
    with pytest.raises(ValueError):
        analyse_observations(
            {**PAYLOAD, "measurement_definitions": [{**DEFINITION, **change}]}, SCOPE
        )


@pytest.mark.parametrize(
    "relation,citation,accepted",
    [
        ("narrower", "Residents aged 18 or older.", True),
        ("proxy", "Residents aged 18 or older.", False),
        ("narrower", "Invented scope definition", False),
        ("unresolved", "Residents aged 18 or older.", False),
    ],
)
def test_publication_requires_independent_cited_subset_review(
    tmp_path, relation, citation, accepted
):
    from sci_search.data_research.artifacts import execute_analysis
    from sci_search.data_research.python_recovery import recover
    from tests.data_meaning_fixtures import positive_review

    code = """import json
from pathlib import Path
source=json.loads(Path('/input/source.bin').read_text())
payload=json.loads(%r)
payload['observations'][0]['value']=source['value']
Path('/output/observations.json').write_text(json.dumps(payload))
""" % json.dumps(PAYLOAD)

    def model(prompt, schema):
        if "code" in schema["properties"]:
            return {"code": code, "explanation": "Extract adult count"}
        if "action" in schema["properties"]:
            return {"action": "stop", "measurements": [], "reason": "Not supported"}
        return {
            "accepted": True,
            "reason": "Documented adults",
            "limitations": [],
            **positive_review(prompt),
            "scope_relations": [
                {
                    "measurement": "adult population",
                    "relation": relation,
                    "reason": "Adults are a documented subset of residents.",
                    "evidence": [{"document": "metadata", "quote": citation}],
                }
            ],
        }

    def run():
        return recover(
            "Population",
            SCOPE,
            b'{"value":12}',
            {"url": "https://example.test/data", "title": "Adult residents"},
            tmp_path,
            complete=model,
            reason="Inspect",
            metadata="Residents aged 18 or older.",
        )

    if not accepted:
        with pytest.raises(ValueError):
            run()
        assert not (tmp_path / "observations.json").exists()
        review = json.loads((tmp_path / "python/attempt-1/semantic-review.json").read_text())
        assert review["accepted"] is False
    else:
        result = execute_analysis(run(), tmp_path)
        assert result["series"][0]["label"] == "adult population"
        assert result["source_verification"]["value_verified"] == 1
        assert result["uncovered_measurements"] == ["population"]
        assert result["execution"]["status"] == "verified"
