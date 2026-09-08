from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from alembic import command
from sqlalchemy import func, select

from sci_search.compatibility.legacy_import import apply_import, compare_parity, scan_legacy
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.tables import (
    EvidenceRow,
    LegacyImportRow,
    PublicationRow,
    ResearchRunRow,
)
from tests.integration.test_legacy_import import _legacy_fixture, _target
from tests.integration.test_migrations import DATABASE_URL, _configuration


def test_interrupted_import_resumes_without_duplicates_and_passes_parity(tmp_path: Path) -> None:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        legacy = tmp_path / "protected-legacy-copy"
        _legacy_fixture(legacy)
        manifest = scan_legacy(legacy)
        # A second source publication exercises a checkpoint within the publication phase.
        second = replace(
            manifest.publications[0],
            source_id="legacy-pub-2",
            title="Conflicting legacy title retained as a variant",
            metadata={"title": "Conflicting legacy title retained as a variant"},
        )
        manifest = replace(manifest, publications=(*manifest.publications, second))
        target = _target(database)
        blobs = FilesystemBlobStore(tmp_path / "new-blobs")

        interrupted = apply_import(
            manifest, target, blobs, apply=True, batch_size=1, maximum_batches=1
        )
        assert interrupted.completed is False
        assert interrupted.next_phase == "publications"

        resumed = apply_import(manifest, target, blobs, apply=True, batch_size=1)
        assert resumed.completed is True
        assert resumed.already_imported is False
        repeated = apply_import(manifest, target, blobs, apply=True, batch_size=1)
        assert repeated.already_imported is True

        with database.transaction() as session:
            assert session.scalar(select(func.count()).select_from(ResearchRunRow)) == 1
            assert session.scalar(select(func.count()).select_from(EvidenceRow)) == 1
            ledger = session.scalar(select(LegacyImportRow))
            assert ledger is not None
            assert ledger.status == "completed"
            assert ledger.checkpoint_json["publications"] == 2
            publication = session.scalar(select(PublicationRow))
            assert publication is not None
            variants = publication.metadata_json["legacy_source_variants"]
            assert variants[0]["source_id"] == "legacy-pub-2"

        parity = compare_parity(manifest, target)
        assert parity["passed"] is True
        assert parity["unexplained_losses"] == []
        assert parity["counts"]["publications"] == {"source": 2, "mapped": 2}
        assert parity["blob_hashes"]["matched"] == 2
    finally:
        database.dispose()


def test_protected_current_tree_import_has_exact_parity(tmp_path: Path) -> None:
    source = os.environ.get("SCI_SEARCH_PROTECTED_LEGACY_ROOT")
    if not source:
        import pytest

        pytest.skip("set SCI_SEARCH_PROTECTED_LEGACY_ROOT for the retained-corpus rehearsal")
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        root = Path(source)
        manifest = scan_legacy(root)
        fingerprint_before = manifest.source_fingerprint
        target = _target(database)
        result = apply_import(
            manifest,
            target,
            FilesystemBlobStore(tmp_path / "new-blobs"),
            apply=True,
            batch_size=50,
        )
        report = compare_parity(manifest, target)
        assert result.completed is True
        assert report["passed"] is True
        assert report["unexplained_losses"] == []
        assert scan_legacy(root).source_fingerprint == fingerprint_before
        print(
            "protected import parity:",
            result.publications_added,
            result.runs_added,
            result.evidence_added,
            result.blobs_added,
        )
    finally:
        database.dispose()
