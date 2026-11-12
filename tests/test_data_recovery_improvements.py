"""Synthetic regressions for failures observed in live data acceptance runs."""

import pytest

from sci_search.data_research import semantics
from sci_search.data_research.connectors import base, eurostat
from sci_search.data_research.verification import verify_observations


def test_text_reference_resolves_original_line_and_unit_conversion():
    body = b"# Monthly mean temperature (0.1 degrees C)\n260,2023,58,57\n"
    result = verify_observations(
        body,
        {
            "observations": [
                {
                    "value": 5.8,
                    "source_locator": {
                        "format": "text",
                        "line": 2,
                        "column": 3,
                        "delimiter": ",",
                        "factor": 0.1,
                    },
                }
            ]
        },
    )
    assert result["value_verified"] == 1
    assert result["references"][0]["text"] == "260,2023,58,57"
    assert result["references"][0]["line"] == 2


@pytest.mark.parametrize("line,column,value", [(1, 2, 414.21), (2, 1, 414.21), (2, 2, 999)])
def test_text_reference_rejects_wrong_line_column_or_value(line, column, value):
    with pytest.raises(ValueError):
        verify_observations(
            b"# annual means\n2020 414.21 0.12\n",
            {
                "observations": [
                    {
                        "value": value,
                        "source_locator": {"format": "text", "line": line, "column": column},
                    }
                ]
            },
        )


def test_eurostat_retrieves_definition_document_with_provenance():
    candidate = base.DatasetCandidate("eurostat", "sdg_07_40", "Renewable share", "annual")
    description = base.DatasetDescription(candidate, (), (), "", "Code labels", "Eurostat")
    url = "https://ec.europa.eu/eurostat/cache/metadata/en/sdg_07_40_esmsip2.htm"
    body = b"<html><p>Electricity share uses gross electricity consumption.</p></html>"
    calls = []

    def fetch(target):
        calls.append(target)
        assert target == url
        return body, "text/html", target

    documents = eurostat.documentation(description, fetch=fetch)
    assert len(calls) == 1
    assert documents[0]["url"] == url
    assert documents[0]["body"] == body
    assert "gross electricity consumption" in documents[0]["text"]


def test_semantic_failure_routes_missing_definitions_differently_from_wrong_values():
    review = {
        "accepted": False,
        "measurements": [{"checks": [{"aspect": "definition", "status": "unresolved"}]}],
    }
    assert semantics.needs_documentation(review)
    review["measurements"][0]["checks"] = [{"aspect": "unit", "status": "conflicting"}]
    assert not semantics.needs_documentation(review)


def test_connector_rechecks_same_values_after_fetching_missing_definition(tmp_path):
    import json

    from tests.data_meaning_fixtures import positive_review
    from tests.test_connector_eurostat import offline
    from tests.test_connector_recovery import GOOD, model, run

    transport, seen = model([GOOD])
    reviews = []

    def complete(prompt, schema):
        if set(schema["properties"]) != {"measurements"}:
            return transport(prompt, schema)
        context = json.loads(prompt.split("\n", 1)[1])
        reviews.append(context)
        reply = positive_review(prompt)
        if not any(k.startswith("definition:") for k in context["evidence_documents"]):
            reply["measurements"][0]["checks"][0].update(
                status="unresolved", reason="Missing definition"
            )
        return reply

    def fetch(url):
        if "/cache/metadata/" in url:
            return b"<html>Life expectancy at birth in years.</html>", "text/html", url
        return offline(url)

    result = run(tmp_path, complete, fetch=fetch)
    assert len(result["analyses"]) == 1
    assert len(reviews) == 2
    assert seen.count("connector_selection") == 1
    assert list(tmp_path.rglob("definition-1.bin"))


def test_supported_year_subset_is_retained_with_original_coverage_gap(tmp_path):
    import json

    from sci_search.data_research.python_recovery import recover
    from tests.data_meaning_fixtures import positive_review
    from tests.test_python_data_recovery import CODE, SCOPE, SOURCE

    def complete(prompt, schema):
        context = json.loads(prompt.split("\n", 1)[1])
        if "code" in schema["properties"]:
            years = context["scope"].get("retained_years", [])
            code = CODE
            if years:
                code = code.replace(
                    'Path("/output/observations.json")',
                    'rows=[r for r in rows if r["year"] == 2001]\nPath("/output/observations.json")',
                )
            return {"code": code, "explanation": "Read supported year"}
        if "action" in schema["properties"]:
            return {
                "action": "extract_subset",
                "measurements": ["population"],
                "years": [2001],
                "entities": [],
                "reason": "2002 changes definition",
            }
        reply = positive_review(prompt)
        supported = all(r["year"] == 2001 for r in context["extracted_sample"])
        if not supported:
            reply["measurements"][0]["checks"][0].update(
                status="conflicting", reason="2002 definition differs"
            )
        return {
            **reply,
            "accepted": supported,
            "reason": "Review supplied years",
            "limitations": [],
        }

    analysis = recover(
        "Population",
        SCOPE,
        b'{"values":{"2001":9,"2002":12}}',
        SOURCE,
        tmp_path,
        complete=complete,
        reason="Nested JSON",
        metadata="Annual resident count",
    )
    series = analysis["series"][0]
    assert series["annual"][0]["value"] == 9
    assert series["missing_years"] == [2002, 2003]
    assert analysis["semantic_review"]["accepted"]


@pytest.mark.parametrize("value,accepted", [(58 * 0.1, True), (5.800001, False)])
def test_converted_reference_allows_only_floating_point_roundoff(value, accepted):
    payload = {
        "observations": [
            {
                "value": value,
                "source_locator": {"format": "text", "line": 1, "column": 1, "factor": 0.1},
            }
        ]
    }
    if accepted:
        assert verify_observations(b"58", payload)["value_verified"] == 1
    else:
        with pytest.raises(ValueError, match="differs"):
            verify_observations(b"58", payload)


def test_eurostat_follows_observed_related_methodology_link_once():
    candidate = base.DatasetCandidate("eurostat", "sdg_07_40", "Share", "annual")
    description = base.DatasetDescription(candidate, (), (), "", "", "Eurostat")
    root = "https://ec.europa.eu/eurostat/cache/metadata/en/sdg_07_40_esmsip2.htm"
    related = "https://ec.europa.eu/eurostat/cache/metadata/EN/nrg_ind_share_esmsip2.htm"
    calls = []

    def fetch(url):
        calls.append(url)
        if url == root:
            return (
                (
                    f'<html>Sector share<a href="{root}#definitions">self</a>'
                    f'<a href="{related}">Underlying indicator metadata</a></html>'
                ).encode(),
                "text/html",
                url,
            )
        assert url == related
        return (
            b"<html>Electricity consumption includes imports minus exports.</html>",
            "text/html",
            url,
        )

    docs = eurostat.documentation(description, fetch=fetch)
    assert calls == [root, related]
    assert "imports minus exports" in docs[1]["text"]


def test_web_discovery_stops_when_retained_subset_completes_requested_coverage():
    from sci_search.data_research.adaptive import research_candidates

    scope = {"measurements": ["use"], "geography": "A", "start_year": 2020, "end_year": 2020}
    result = {"analyses": [], "assessments": [], "limitations": []}
    candidates = [{"url": "https://example.org/first"}, {"url": "https://example.org/second"}]

    def unexpected(*args, **kwargs):
        raise AssertionError("No model or search needed after coverage is complete")

    iterator = research_candidates(
        "Use in A",
        scope,
        {"candidates": candidates},
        result,
        unexpected,
        None,
        unexpected,
        lambda *a: None,
        lambda *a: None,
        lambda: None,
    )
    assert next(iterator) == candidates[0]
    result["analyses"].append(
        {
            "series": [
                {
                    "label": "use",
                    "entity": "A",
                    "unit": "kWh",
                    "annual": [{"year": 2020, "value": 9}],
                }
            ]
        }
    )
    assert list(iterator) == []
    assert result["research_process"]["stop_reason"]


def test_connector_uses_targeted_definition_search_when_provider_documentation_is_missing(
    tmp_path, monkeypatch
):
    import json

    from tests.data_meaning_fixtures import positive_review
    from tests.test_connector_reselection import FIRST
    from tests.test_connector_stage import scripted

    monkeypatch.setattr(eurostat, "documentation", lambda *a, **k: [])
    searched = []

    def definition_search(candidate, review):
        searched.append(candidate.dataset)
        return [
            {
                "url": "https://ec.europa.eu/eurostat/methods",
                "body": b"At birth in years",
                "text": "At birth in years",
            }
        ]

    def complete(prompt, schema):
        if set(schema["properties"]) == {"measurements"}:
            context = json.loads(prompt.split("\n", 1)[1])
            reply = positive_review(prompt)
            if not any(k.startswith("definition:") for k in context["evidence_documents"]):
                reply["measurements"][0]["checks"][0].update(
                    status="unresolved", reason="Missing definition"
                )
            return reply
        if schema.get("title") == "connector_selection":
            return FIRST
        return scripted(prompt, schema)

    from sci_search.data_research.connectors import stage
    from tests.test_connector_reselection import CANDIDATE, STRATEGY, offline

    analysis, _ = stage.analyse_dataset(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        eurostat,
        CANDIDATE,
        "life expectancy at birth",
        complete=complete,
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        definition_search=definition_search,
    )
    assert analysis is not None
    assert searched == ["demo_mlexpec"]
