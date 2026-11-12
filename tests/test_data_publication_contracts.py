"""Publication and source identity contracts for bounded research recovery."""

import copy

import pytest

from sci_search.data_research.adaptive import research_candidates
from sci_search.data_research.source_review import inherit_context


def test_retained_context_follows_source_identity_after_assessment_reordering():
    assessments = [
        {"source_id": "second", "url": "https://example.test/b", "recovery_links": []},
        {
            "source_id": "first",
            "url": "https://example.test/a",
            "recovery_links": ["https://example.test/data"],
        },
    ]
    retained = {"first": {"metadata": "Unit: hectares"}}
    assert inherit_context(
        {"url": "https://example.test/data", "recovery_from": "https://example.test/a"},
        assessments,
        retained,
    ) == ("Unit: hectares", ["https://example.test/a"])


def test_planner_uses_snapshot_provider_instead_of_stale_result():
    result = {"analyses": [], "assessments": [], "limitations": []}
    current = copy.deepcopy(result)
    stream = research_candidates(
        "trend",
        {},
        {"candidates": [{"url": "https://example.test/a"}]},
        result,
        None,
        None,
        lambda *args: dict(
            action="retry_link", source_index=0, link_index=0, query="", reason="Read"
        ),
        lambda *args: None,
        lambda *args: None,
        lambda: None,
        snapshot_provider=lambda: copy.deepcopy(current),
        max_rounds=1,
    )
    next(stream)
    current["assessments"].append(
        dict(
            url="https://example.test/a",
            decision="blocked",
            reason="Viewer",
            recovery_links=["https://example.test/data"],
        )
    )
    assert next(stream)["url"] == "https://example.test/data"
    assert result["assessments"] == []


@pytest.mark.parametrize(
    "overlap_policy,accepted", [("allow", True), ("reject_source_series", False)]
)
def test_publication_enforces_its_explicit_overlap_policy(tmp_path, overlap_policy, accepted):
    from sci_search.data_research.publication import publish_analysis

    original = {"source": {"sha256": "abc"}, "series": [{"label": "cover", "entity": "A"}]}
    result = {"analyses": [copy.deepcopy(original)]}
    assessment = {"decision": "blocked", "reason": "Initial", "availability": "unreadable"}
    calls = []

    def execute(analysis, folder, **kwargs):
        calls.append(analysis)
        return analysis

    def publish():
        return publish_analysis(
            copy.deepcopy(original),
            tmp_path,
            result=result,
            assessment=assessment,
            reason="Validated",
            overlap_policy=overlap_policy,
            execute=execute,
            check_cancelled=lambda: None,
        )

    if accepted:
        publish()
        assert len(result["analyses"]) == 2
        assert assessment["decision"] == "analysed"
        assert "availability" not in assessment
        assert (tmp_path / "analysis.json").exists()
    else:
        with pytest.raises(ValueError, match="overlaps"):
            publish()
        assert result["analyses"] == [original]
        assert assessment["decision"] == "blocked"
        assert not (tmp_path / "analysis.json").exists()
    assert len(calls) == 1


def test_reassessment_finds_bytes_by_id_and_rejects_overlap(tmp_path, monkeypatch):
    from sci_search.data_research import source_review
    from sci_search.data_research.execution import digest

    body = b"observed data"
    original = {"source": {"sha256": digest(body)}, "series": [{"label": "cover", "entity": "A"}]}
    assessment = {"source_id": "original", "decision": "blocked", "reason": "Missing subset"}
    result = {
        "analyses": [copy.deepcopy(original)],
        "assessments": [{"source_id": "other"}, assessment],
    }
    retained = {
        "original": {
            "body": body,
            "source": original["source"],
            "metadata": "Observed units",
            "folder": "source-8",
        }
    }
    monkeypatch.setattr(source_review, "recover", lambda *args, **kwargs: copy.deepcopy(original))
    monkeypatch.setattr(
        source_review, "execute_analysis", lambda analysis, *args, **kwargs: analysis
    )
    outcome = source_review.reassess_source(
        1,
        ["cover"],
        -1,
        1,
        retained=retained,
        result=result,
        question="Cover",
        scope={"measurements": ["cover"], "geography": "A", "start_year": 2000, "end_year": 2001},
        directory=tmp_path,
        fetch=None,
        complete=None,
        progress=lambda _: None,
        check_cancelled=lambda: None,
    )
    assert outcome["status"] == "blocked"
    assert "overlaps" in outcome["reason"]
    assert result["analyses"] == [original]
    assert assessment["decision"] == "blocked"
    assert (tmp_path / "source-8-review-1/review.json").exists()


def test_publication_cancellation_preserves_analysis_and_assessment(tmp_path):
    from sci_search.data_research.publication import publish_analysis

    class Cancelled(RuntimeError):
        pass

    def execute(*args, **kwargs):
        raise Cancelled()

    result = {"analyses": []}
    assessment = {"decision": "blocked"}
    with pytest.raises(Cancelled):
        publish_analysis(
            {},
            tmp_path,
            result=result,
            assessment=assessment,
            reason="Validated",
            overlap_policy="allow",
            execute=execute,
            check_cancelled=lambda: None,
        )
    assert result["analyses"] == []
    assert assessment == {"decision": "blocked"}
    assert not (tmp_path / "analysis.json").exists()


def test_resume_restores_context_by_persisted_identity_and_exact_digests(tmp_path):
    import hashlib
    import json

    from sci_search.data_research.source_state import restore_retained

    folder = tmp_path / "source-7"
    folder.mkdir()
    body, metadata = b"original bytes", "Observed units"
    assessment = {
        "source_id": "source-7",
        "url": "https://example.test/data",
        "decision": "blocked",
        "source_digest": hashlib.sha256(body).hexdigest(),
        "context_digest": hashlib.sha256(metadata.encode()).hexdigest(),
    }
    record = {
        "source_id": "source-7",
        "folder": "source-7",
        "metadata": metadata,
        "source": {"sha256": assessment["source_digest"]},
    }
    (folder / "source-context.json").write_text(json.dumps(record))
    (folder / "assessment.json").write_text(json.dumps(assessment))
    (folder / "download.bin").write_bytes(body)
    retained = restore_retained(tmp_path, [{"source_id": "other"}, assessment])
    assert retained["source-7"]["body"] == body
    assert retained["source-7"]["metadata"] == metadata
    (folder / "download.bin").write_bytes(b"tampered")
    assert restore_retained(tmp_path, [assessment]) == {}
    (folder / "download.bin").write_bytes(body)
    record["metadata"] = "unverified definitions"
    (folder / "source-context.json").write_text(json.dumps(record))
    assert restore_retained(tmp_path, [assessment]) == {}


def test_legacy_resume_context_requires_unambiguous_assessment_match(tmp_path):
    import hashlib
    import json

    from sci_search.data_research.source_state import restore_retained

    folder = tmp_path / "source-9"
    folder.mkdir()
    body, metadata = b"observed bytes", "Observed definitions"
    assessment = {
        "url": "https://example.test/data",
        "source_digest": hashlib.sha256(body).hexdigest(),
        "context_digest": hashlib.sha256(metadata.encode()).hexdigest(),
    }
    (folder / "assessment.json").write_text(json.dumps(assessment))
    (folder / "source-context.json").write_text(
        json.dumps(
            {
                "folder": folder.name,
                "metadata": metadata,
                "source": {"sha256": assessment["source_digest"]},
            }
        )
    )
    (folder / "download.bin").write_bytes(body)
    assert restore_retained(tmp_path, [copy.deepcopy(assessment), copy.deepcopy(assessment)]) == {}
    reordered = [{"url": "https://example.test/other"}, copy.deepcopy(assessment)]
    restored = restore_retained(tmp_path, reordered)
    assert restored["source-9"]["body"] == body
    assert reordered[1]["source_id"] == "source-9"
    (folder / "download.bin").unlink()
    other = tmp_path / "other.bin"
    other.write_bytes(body)
    (folder / "download.bin").symlink_to(other)
    assert restore_retained(tmp_path, reordered) == {}


@pytest.mark.parametrize("reference", [-1, 99, True, "unknown"])
def test_source_reference_rejects_invalid_positions_and_unknown_ids(reference):
    from sci_search.data_research.source_state import resolve_source

    with pytest.raises(ValueError):
        resolve_source(reference, [{"source_id": "source-1"}], {"source-1": {"body": b"one"}})


def test_duplicate_source_ids_are_not_resolved_by_list_order():
    from sci_search.data_research.source_state import resolve_source

    with pytest.raises(ValueError):
        resolve_source("source-1", [{"source_id": "source-1"}, {"source_id": "source-1"}], {})
