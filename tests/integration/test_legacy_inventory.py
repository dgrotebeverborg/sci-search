from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sci_search.compatibility.legacy_import import inventory_legacy


def _fixture(root: Path) -> None:
    memory = root / "scientific_memory"
    papers = memory / "papers"
    papers.mkdir(parents=True)
    shared = papers / "shared.pdf"
    shared.write_bytes(b"shared publication bytes")
    unreadable = papers / "unreadable.pdf"
    unreadable.write_bytes(b"cannot read")
    unreadable.chmod(0)
    connection = sqlite3.connect(memory / "memory.sqlite3")
    connection.executescript(
        """
        CREATE TABLE publications (
          publication_id TEXT, canonical_key TEXT, metadata_json TEXT,
          content_sha256 TEXT, cache_path TEXT
        );
        CREATE TABLE evidence_records (
          evidence_id TEXT, publication_id TEXT, extraction_method TEXT,
          payload_json TEXT, first_seen_at TEXT
        );
        """
    )
    rows = [
        ("p1", "doi:10.1/shared", '{"title":"First title"}', "", "papers/shared.pdf"),
        ("p2", "doi:10.1/shared", '{"title":"Conflicting title"}', "", "papers/shared.pdf"),
        ("p3", "doi:10.1/unreadable", '{"title":"Unreadable"}', "", "papers/unreadable.pdf"),
    ]
    connection.executemany("INSERT INTO publications VALUES (?,?,?,?,?)", rows)
    connection.execute(
        "INSERT INTO evidence_records VALUES (?,?,?,?,?)",
        (
            "e1",
            "p1",
            "fixture",
            '{"statement":"claim","source_passage":"claim"}',
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.commit()
    connection.close()
    run = root / "research_runs" / "incomplete" / "run.json"
    run.parent.mkdir(parents=True)
    run.write_text(json.dumps({"run_id": "incomplete", "status": "failed"}), encoding="utf-8")


def test_inventory_is_deterministic_read_only_and_classifies_anomalies(tmp_path: Path) -> None:
    _fixture(tmp_path)
    before = sorted(
        (path.relative_to(tmp_path), path.stat().st_mtime_ns) for path in tmp_path.rglob("*")
    )

    first = inventory_legacy(tmp_path)
    second = inventory_legacy(tmp_path)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["counts"] == {
        "publications": 3,
        "runs": 1,
        "evidence": 1,
        "unique_blobs": 1,
        "unreadable_files": 1,
        "metadata_conflicts": 1,
        "incomplete_runs": 1,
    }
    assert first["blobs"][0]["reference_count"] == 2
    assert first["metadata_conflicts"][0]["canonical_key"] == "doi:10.1/shared"
    assert first["runs"][0]["classification"] == "incomplete"
    assert first["errors"][0]["kind"] == "unreadable_document"
    after = sorted(
        (path.relative_to(tmp_path), path.stat().st_mtime_ns) for path in tmp_path.rglob("*")
    )
    assert after == before
