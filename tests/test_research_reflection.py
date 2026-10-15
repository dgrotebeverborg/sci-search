"""A running investigation diagnoses its own failures before repeating work."""

import io
import json
import zipfile

import pytest

from sci_search.data_research import python_recovery
from sci_search.data_research.packages import prepare_table
from tests.data_meaning_fixtures import with_positive_meaning_review


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


def coral_archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("data.csv", "Year,Reef,HC\n2024,A,0.4\n2025,A,0.5\n")
        z.writestr(
            "readme.txt",
            "HC is hard coral cover, a proportion of the surveyed reef. Bleaching is not measured.",
        )
    return stream.getvalue()


def test_archive_documentation_reaches_mapping():
    _, prepared = prepare_table(coral_archive())
    assert "HC is hard coral cover" in prepared["metadata"]
    assert "readme.txt" in prepared["metadata"]


def test_failed_extraction_is_replanned_for_a_supported_subquestion(tmp_path):
    calls = []

    def model(prompt, schema):
        calls.append(prompt)
        if "action" in schema["properties"]:
            assert "no bleaching" in prompt
            assert "HC is hard coral cover" in prompt
            return dict(
                action="extract_subset",
                measurements=["coral cover"],
                reason="Preserve cover; bleaching needs another source.",
            )
        if "code" in schema["properties"]:
            if sum("Write executable Python" in p for p in calls) == 1:
                return dict(
                    code="raise ValueError('no bleaching in this file')",
                    explanation="Missing bleaching",
                )
            assert "extract_subset" in prompt
            return dict(
                code="""import csv,io,json,zipfile
from pathlib import Path
with zipfile.ZipFile('/input/source.bin') as z:
 rows=list(csv.DictReader(io.StringIO(z.read('data.csv').decode())))
Path('/output/observations.json').write_text(json.dumps({'observations':[dict(entity=r['Reef'],year=int(r['Year']),value=float(r['HC']),unit='proportion',measurement='coral cover',source_reference='data.csv:'+str(i+2)) for i,r in enumerate(rows)]}))
""",
                explanation="Extract actual cover observations only",
            )
        return dict(accepted=True, reason="Documented cover", limitations=["Bleaching unavailable"])

    result = python_recovery.recover(
        "Cover and bleaching",
        dict(measurements=["bleaching", "coral cover"], start_year=2024, end_year=2026),
        coral_archive(),
        dict(title="Coral", url="https://example.org/data"),
        tmp_path,
        complete=with_positive_meaning_review(model),
        reason="No standard mapping",
    )
    assert [s["label"] for s in result["series"]] == ["coral cover"]
    assert result["scope"]["measurements"] == ["bleaching", "coral cover"]
    assert result["uncovered_measurements"] == ["bleaching"]
    review = result["python_extraction"]["reflection"]
    assert review[0]["action"] == "extract_subset"
    assert json.loads((tmp_path / "python/attempt-1/reflection.json").read_text()) == review[0]


def test_reflection_cannot_expand_the_requested_measurements(tmp_path):
    import pytest

    calls = []

    def model(prompt, schema):
        if "action" in schema["properties"]:
            return dict(action="extract_subset", measurements=["fish count"], reason="Wrong scope")
        calls.append(prompt)
        return dict(code="raise ValueError('no bleaching')", explanation="Unsupported")

    with pytest.raises(ValueError):
        python_recovery.recover(
            "Bleaching",
            dict(measurements=["bleaching"]),
            coral_archive(),
            dict(title="Coral", url="https://example.org/data"),
            tmp_path,
            complete=with_positive_meaning_review(model),
            reason="Missing",
        )
    assert all('"measurements": ["fish count"]' not in p for p in calls)


def test_workflow_reassesses_a_rejected_download_for_a_partial_answer(tmp_path):
    from sci_search.data_research.workflow import execute

    calls = []

    def model(prompt, schema):
        if "adapter" in schema["properties"]:
            return dict(
                adapter="unsupported",
                download_link_index=-1,
                reason="No bleaching",
                definition_quote="",
                license_note="Unknown",
                covered_measurements=[],
            )
        if "action" in schema["properties"]:
            if calls:
                return dict(
                    action="stop",
                    source_index=-1,
                    link_index=-1,
                    query="",
                    measurements=[],
                    reason="Cover retained; bleaching absent",
                )
            calls.append("reassess")
            return dict(
                action="reassess",
                source_index=0,
                link_index=-1,
                query="",
                measurements=["coral cover"],
                reason="Use the supported cover subset",
            )
        if "code" in schema["properties"]:
            return dict(
                code="""import csv,json
from pathlib import Path
rows=list(csv.DictReader(Path('/input/source.bin').read_text().splitlines()))
Path('/output/observations.json').write_text(json.dumps({'observations':[dict(entity=r['Reef'],year=int(r['Year']),value=float(r['Cover']),unit='percent',measurement='coral cover',source_reference='row '+str(i+2)) for i,r in enumerate(rows)]}))
""",
                explanation="Extract cover only",
            )
        return dict(accepted=True, reason="Documented subset", limitations=["Bleaching missing"])

    result = execute(
        "cover and bleaching",
        dict(
            route="data",
            rationale="Trends",
            geography="A",
            measurements=["bleaching", "coral cover"],
            start_year=2024,
            end_year=2026,
        ),
        tmp_path,
        search=lambda *a, **k: dict(
            candidates=[dict(url="https://example.org/data.csv", title="Cover", publisher="Agency")]
        ),
        fetch=lambda u: (b"Year,Reef,Cover\n2024,A,40\n2025,A,50\n", "text/csv", u),
        complete=with_positive_meaning_review(model),
    )
    assert result["status"] == "partial"
    assert result["uncovered_measurements"] == ["bleaching"]
    assert result["analyses"][0]["series"][0]["annual"][0]["value"] == 40
    assert result["research_process"]["steps"][0]["outcome"]["status"] == "retained"
    assert (tmp_path / "source-1-review-1/analysis.json").exists()
    assessment = json.loads((tmp_path / "source-1/assessment.json").read_text())
    assert assessment["decision"] == "analysed"
    assert assessment["initial_assessment"]["decision"] == "blocked"
    assert "availability" not in assessment


def test_source_review_keeps_existing_measurement_and_extracts_only_missing_one(
    tmp_path, monkeypatch
):
    from sci_search.data_research import source_review
    from sci_search.data_research.execution import digest

    body = b"data"
    source = {"sha256": digest(body), "title": "Data"}
    result = {
        "analyses": [{"source": source, "series": [{"label": "cover", "entity": "A"}]}],
        "assessments": [{"reason": "Partial cover only"}],
    }

    def recover(question, scope, *args, **kwargs):
        assert scope["measurements"] == ["bleaching"]
        return {"source": source, "series": [{"label": "bleaching", "entity": "A"}]}

    monkeypatch.setattr(source_review, "recover", recover)
    monkeypatch.setattr(source_review, "execute_analysis", lambda analysis, *a, **k: analysis)
    outcome = source_review.reassess_source(
        0,
        ["cover", "bleaching"],
        -1,
        1,
        retained={0: {"body": body, "source": source, "metadata": ""}},
        result=result,
        question="cover and bleaching",
        scope={"measurements": ["cover", "bleaching"]},
        directory=tmp_path,
        fetch=None,
        complete=None,
        progress=lambda x: None,
        check_cancelled=lambda: None,
    )
    assert outcome["status"] == "retained"
    assert len(result["analyses"]) == 2
    assert result["analyses"][0]["series"][0]["label"] == "cover"


def test_broken_documentation_response_does_not_abort_investigation(tmp_path):
    import http.client

    from sci_search.data_research.source_review import reassess_source

    result = {
        "analyses": [],
        "assessments": [
            {
                "reason": "Missing units",
                "decision": "blocked",
                "recovery_links": ["https://example.org/methods"],
            }
        ],
    }

    def broken(url):
        raise http.client.IncompleteRead(b"partial", 10)

    outcome = reassess_source(
        0,
        ["cover"],
        0,
        1,
        retained={0: {"body": b"data", "source": {}, "metadata": ""}},
        result=result,
        question="cover",
        scope={"measurements": ["cover"]},
        directory=tmp_path,
        fetch=broken,
        complete=None,
        progress=lambda x: None,
        check_cancelled=lambda: None,
    )
    assert outcome["status"] == "blocked"
    assert result["analyses"] == []


def test_site_level_partial_data_keeps_more_than_200_entities_without_aggregation():
    from sci_search.data_research.python_rows import analyse_observations

    rows = [
        dict(
            entity=f"Reef {i}",
            year=2025,
            value=0.4,
            unit="proportion",
            measurement="cover",
            source_reference=f"data.csv:{i + 2}",
        )
        for i in range(271)
    ]
    analysis = analyse_observations(
        {"observations": rows}, {"measurements": ["cover"], "start_year": 2000, "end_year": 2026}
    )
    assert len(analysis["series"]) == 271
    assert all(s["annual"][-1]["value"] is None for s in analysis["series"])
