import json

from sci_search.investigation_review import review_investigation


def matrix():
    return {
        "studies": [
            {
                "publication_id": "p1",
                "title": "Reef cover",
                "doi": "10.1/example",
                "screening": {"decision": "excluded", "reason": "Missing bleaching"},
                "selected_passages": [
                    {
                        "id": "passage1",
                        "passage": "Hard coral cover on the surveyed Great Barrier Reef sites declined between 2000 and 2010.",
                    }
                ],
            }
        ]
    }


def test_review_retains_verified_partial_evidence_without_promoting_overall_answer(tmp_path):
    calls = []

    def complete(prompt, schema):
        calls.append(prompt)
        if "action" in schema["properties"]:
            if len(calls) > 1:
                assert "retained" in prompt
                return {
                    "action": "stop",
                    "subject_index": -1,
                    "publication_ids": [],
                    "reason": "Partial evidence saved; remaining years absent",
                }
            assert "Missing bleaching" in prompt
            return {
                "action": "review_subquestion",
                "subject_index": 1,
                "publication_ids": ["p1"],
                "reason": "Review cover independently of bleaching",
            }
        return {
            "findings": [
                {
                    "publication_id": "p1",
                    "passage_id": "passage1",
                    "quote": matrix()["studies"][0]["selected_passages"][0]["passage"],
                    "qualification": "Surveyed sites and 2000–2010 only; not reef-wide or through 2026.",
                }
            ]
        }

    out = review_investigation(
        "bleaching and cover",
        ["bleaching", "coral cover"],
        matrix(),
        {"status": "insufficient"},
        directory=tmp_path,
        complete=complete,
    )
    assert out["steps"][0]["outcome"]["status"] == "retained"
    assert out["partial_findings"][0]["subject"] == "coral cover"
    assert out["partial_findings"][0]["publication_id"] == "p1"
    assert "not reef-wide" in out["partial_findings"][0]["qualification"]
    assert json.loads((tmp_path / "investigation_review.json").read_text()) == out


def test_review_rejects_invented_quotes_and_unknown_sources(tmp_path):
    def complete(prompt, schema):
        if "action" in schema["properties"]:
            return {
                "action": "review_subquestion",
                "subject_index": 0,
                "publication_ids": ["p1"],
                "reason": "Recheck",
            }
        return {
            "findings": [
                {
                    "publication_id": "p1",
                    "passage_id": "passage1",
                    "quote": "Cover doubled throughout the entire reef.",
                    "qualification": "None",
                }
            ]
        }

    out = review_investigation(
        "cover", ["cover"], matrix(), {}, directory=tmp_path, complete=complete
    )
    assert not out["partial_findings"]
    assert out["steps"][0]["outcome"]["rejected"] == 1
    assert len(out["steps"]) <= 2


def test_recovered_excluded_source_is_in_research_package(tmp_path, monkeypatch):
    import io
    import zipfile

    from sci_search.research_runs import DownloadPayload, ResearchRunManager

    review = {
        "partial_findings": [
            {
                "subject": "cover",
                "publication_id": "p1",
                "quote": "Exact original source text.",
                "source_artifact": "papers/partial.txt",
            }
        ]
    }
    investigation = {
        "question": "Cover and bleaching",
        "investigation_review": review,
        "evidence": [],
        "findings": [],
        "research_run": {},
        "answer_adequacy": {},
    }
    (tmp_path / "corpus/papers").mkdir(parents=True)
    (tmp_path / "corpus/papers/partial.txt").write_text("Exact original source text.")
    (tmp_path / "investigation.json").write_text(json.dumps(investigation))
    state = {
        "status": "complete",
        "result": investigation,
        "question": "Cover and bleaching",
        "full_text_screening": [{"publication_id": "p1", "decision": "excluded"}],
    }
    manager = ResearchRunManager(tmp_path, providers=(), openalex_api_key="test")
    monkeypatch.setattr(manager, "get", lambda _: state)
    monkeypatch.setattr(manager, "_run_directory", lambda _: tmp_path)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("manifest.json", json.dumps({"documents": []}))
    monkeypatch.setattr(
        manager,
        "download_publications",
        lambda *a, **k: DownloadPayload("papers.zip", "application/zip", stream.getvalue()),
    )
    package = manager.download_research_package("saved")
    with zipfile.ZipFile(io.BytesIO(package.body)) as z:
        assert z.read("reviewed-sources/papers/partial.txt") == b"Exact original source text."
        assert json.loads(z.read("data/investigation-review.json")) == review
        assert json.loads(z.read("data/publications-manifest.json"))["documents"] == []
