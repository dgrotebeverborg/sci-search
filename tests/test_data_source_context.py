"""Source context must survive documented retries without leaking across datasets."""

import json

from sci_search.data_research.source_review import reassess_source
from tests.data_meaning_fixtures import with_positive_meaning_review
from tests.test_python_data_recovery import CODE, SCOPE, SOURCE


def test_reassessment_keeps_documentation_even_when_extraction_is_blocked(tmp_path):
    retained = {0: {"body": b'{"values":{"2001":9}}', "source": SOURCE, "metadata": "Population."}}
    result = {
        "analyses": [],
        "assessments": [{"reason": "No units", "recovery_links": ["https://example.test/units"]}],
    }

    def model(prompt, schema):
        if "code" in schema["properties"]:
            return {"code": CODE, "explanation": "Read values"}
        if "action" in schema["properties"]:
            return {"action": "stop", "reason": "Need definition", "measurements": []}
        return {"accepted": False, "reason": "Need definition", "limitations": []}

    outcome = reassess_source(
        0,
        ["population"],
        0,
        1,
        retained=retained,
        result=result,
        question="Population",
        scope=SCOPE,
        directory=tmp_path,
        fetch=lambda u: (b"<p>Population is measured in people.</p>", "text/html", u),
        complete=with_positive_meaning_review(model),
        progress=lambda _: None,
        check_cancelled=lambda: None,
    )
    assert outcome["status"] == "blocked"
    assert "Population is measured in people." in retained[0]["metadata"]
    assert retained[0]["documentation"][0]["url"] == "https://example.test/units"
    dossier = json.loads((tmp_path / "source-1/source-context.json").read_text())
    assert dossier["documentation"][0]["sha256"] == outcome["documentation"]["sha256"]


def test_new_definitions_remain_visible_after_a_long_source_preview(tmp_path):
    from sci_search.data_research.python_recovery import recover

    def model(prompt, schema):
        if "code" in schema["properties"]:
            return {"code": CODE, "explanation": "Read values"}
        if "action" in schema["properties"]:
            return {"action": "stop", "reason": "Missing metadata", "measurements": []}
        context = json.loads(prompt.split("\n", 1)[1])
        return {
            "accepted": "Unit: people" in context["evidence_documents"]["metadata"],
            "reason": "Check retained units",
            "limitations": [],
        }

    result = recover(
        "Population",
        SCOPE,
        b'{"values":{"2001":9}}',
        SOURCE,
        tmp_path,
        complete=with_positive_meaning_review(model),
        reason="Read",
        metadata="Source preview. " * 3000 + "\nUnit: people",
    )
    assert result["series"][0]["annual"][0]["value"] == 9


def test_unrelated_dataset_on_same_host_does_not_inherit_metadata():
    from sci_search.data_research.source_review import inherit_context

    assessments = [
        {"url": "https://example.test/a", "recovery_links": ["https://example.test/a.csv"]}
    ]
    retained = {0: {"metadata": "Unit: hectares"}}
    assert inherit_context(
        {"url": "https://example.test/b.csv", "recovery_from": "https://example.test/a"},
        assessments,
        retained,
    ) == ("", [])


def test_retry_download_inherits_its_parent_metadata_but_not_other_sources(tmp_path, monkeypatch):
    from sci_search.data_research.workflow import execute

    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")
    plans = iter(
        [
            dict(
                action="retry_link",
                source_index=0,
                link_index=0,
                query="",
                measurements=["population"],
                reason="Read linked data",
            ),
            dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                measurements=[],
                reason="Partial period",
            ),
        ]
    )

    def model(prompt, schema):
        if "adapter" in schema["properties"]:
            ctx = json.loads(prompt.split("\n", 1)[1])
            direct = ctx["source"]["url"].endswith(".json")
            return dict(
                adapter="python" if direct else "unsupported",
                download_link_index=-1,
                reason="Read linked observations",
                definition_quote="",
                license_note="unknown",
                covered_measurements=["population"] if direct else [],
            )
        if "action" in schema["properties"]:
            return next(plans)
        if "code" in schema["properties"]:
            return dict(code=CODE, explanation="Read values")
        ctx = json.loads(prompt.split("\n", 1)[1])
        has_units = "Population is measured in people." in ctx["metadata"]
        return dict(
            accepted=has_units,
            reason="Documented" if has_units else "Missing units",
            limitations=[],
        )

    def fetch(url):
        if url.endswith(".json"):
            return b'{"values":{"2001":9}}', "application/json", url
        return (
            b'<p>Population is measured in people.</p><a href="/data.json">Download</a>',
            "text/html",
            url,
        )

    result = execute(
        "Population",
        {**SCOPE, "route": "data", "rationale": "Trend"},
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                {
                    "url": "https://example.test/dataset",
                    "title": "Population",
                    "publisher": "Agency",
                }
            ]
        },
        fetch=fetch,
        complete=with_positive_meaning_review(model),
    )
    assert result["analyses"][0]["series"][0]["annual"][0]["value"] == 9
    assert result["assessments"][1]["context_from"] == ["https://example.test/dataset"]
