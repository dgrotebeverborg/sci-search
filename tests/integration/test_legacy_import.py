from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.identity import ExternalIdentity, IdentityProfile, provision_user
from sci_search.application.projects import Project
from sci_search.compatibility.legacy_import import (
    LegacyImportTarget,
    apply_import,
    scan_legacy,
)
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.repositories import SqlUnitOfWork
from sci_search.infrastructure.tables import (
    AuditEventRow,
    DocumentRow,
    EvidenceRow,
    LegacyImportRow,
    PublicationRow,
    ResearchRunRow,
)
from tests.integration.test_migrations import DATABASE_URL, _configuration

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)


@pytest.fixture
def database() -> Database:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        yield database
    finally:
        database.dispose()


def _target(database: Database) -> LegacyImportTarget:
    with database.transaction() as session:
        repositories = SqlUnitOfWork(session)
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "legacy-owner"),
            IdentityProfile(email="legacy-owner@example.test"),
            repositories.provisioning,
            clock=lambda: NOW,
        )
        project = Project(
            "10000000-0000-0000-0000-000000000001",
            owner.workspace.id,
            "Imported legacy research",
            owner.user.id,
            True,
            NOW,
        )
        repositories.projects.add_project(project)
        return LegacyImportTarget(database, project.id, owner.user.id)


def _legacy_fixture(root: Path) -> None:
    memory = root / "scientific_memory"
    documents = memory / "documents"
    documents.mkdir(parents=True)
    body = b"Results\nRound-trip efficiency was measured as 70%.\n"
    source = documents / "iron-air.txt"
    source.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()

    connection = sqlite3.connect(memory / "memory.sqlite3")
    connection.executescript(
        """
        CREATE TABLE publications(
            publication_id TEXT PRIMARY KEY, canonical_key TEXT UNIQUE NOT NULL,
            metadata_json TEXT NOT NULL, search_text TEXT NOT NULL,
            content_sha256 TEXT, cache_path TEXT, download_cache_path TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE evidence_records(
            evidence_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
            evidence_fingerprint TEXT NOT NULL, document_sha256 TEXT NOT NULL,
            validation_status TEXT NOT NULL, review_state TEXT NOT NULL,
            schema_version TEXT NOT NULL, validator_version TEXT NOT NULL,
            extraction_method TEXT NOT NULL, payload_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO publications VALUES(?,?,?,?,?,?,?,?)",
        (
            "legacy-pub-1",
            "doi:10.1234/legacy",
            json.dumps({"title": "Legacy iron-air study", "doi": "10.1234/legacy"}),
            "legacy iron-air study",
            digest,
            "documents/iron-air.txt",
            None,
            NOW.isoformat(),
        ),
    )
    connection.execute(
        "INSERT INTO evidence_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "legacy-evidence-1",
            "legacy-pub-1",
            "fingerprint-1",
            digest,
            "valid",
            "unreviewed",
            "scientific_evidence_v1",
            "validator-v1",
            "mistral-structured-v1",
            json.dumps(
                {
                    "statement": "The measured round-trip efficiency was 70%.",
                    "source_passage": "Round-trip efficiency was measured as 70%.",
                    "section": "Results",
                    "page": 4,
                    "evidence_type": "laboratory_experiment",
                }
            ),
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    connection.commit()
    connection.close()

    run = root / "research_runs" / "legacy-run-1"
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "legacy-run-1",
                "question": "What efficiency was measured?",
                "status": "complete",
                "created_at": NOW.isoformat(),
                "active_publication_ids": ["legacy-pub-1"],
            }
        ),
        encoding="utf-8",
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_legacy_import_is_dry_run_by_default_repeatable_and_non_mutating(
    database: Database, tmp_path: Path
) -> None:
    legacy = tmp_path / "legacy"
    _legacy_fixture(legacy)
    before = _snapshot(legacy)
    manifest = scan_legacy(legacy)

    assert manifest.publication_count == 1
    assert manifest.run_count == 1
    assert manifest.evidence_count == 1
    assert manifest.blob_count == 1
    target = _target(database)
    blobs = FilesystemBlobStore(tmp_path / "new-blobs")

    dry_run = apply_import(manifest, target, blobs)
    assert dry_run.dry_run is True
    assert dry_run.publications_added == 0
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(PublicationRow)) == 0

    first = apply_import(manifest, target, blobs, apply=True)
    second = apply_import(manifest, target, blobs, apply=True)
    assert first.dry_run is False
    assert (
        first.publications_added,
        first.runs_added,
        first.evidence_added,
        first.blobs_added,
    ) == (1, 1, 1, 1)
    assert (
        second.publications_added,
        second.runs_added,
        second.evidence_added,
        second.blobs_added,
    ) == (0, 0, 0, 0)
    assert second.source_fingerprint == first.source_fingerprint == manifest.source_fingerprint

    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(PublicationRow)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentRow)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchRunRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceRow)) == 1
        assert session.scalar(select(func.count()).select_from(LegacyImportRow)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 1
        publication = session.scalar(select(PublicationRow))
        assert publication is not None
        assert publication.metadata_json["doi"] == "10.1234/legacy"
    assert _snapshot(legacy) == before


def test_scan_rejects_document_paths_outside_legacy_root(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    _legacy_fixture(legacy)
    database = sqlite3.connect(legacy / "scientific_memory" / "memory.sqlite3")
    database.execute("UPDATE publications SET cache_path='../../outside.txt'")
    database.commit()
    database.close()
    (tmp_path / "outside.txt").write_text("not authorized", encoding="utf-8")

    with pytest.raises(ValueError, match="outside legacy root"):
        scan_legacy(legacy)
