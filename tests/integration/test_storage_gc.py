from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import select, update

from sci_search.application.blobs import BlobNotFound
from sci_search.application.projects import Project
from sci_search.application.retention import RetentionService
from sci_search.compatibility.legacy_import import LegacyImportTarget
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.repositories import SqlResearchRepository, SqlUnitOfWork
from sci_search.infrastructure.tables import ArtifactRow, AuditEventRow, DocumentRow, ProjectRow
from tests.integration.test_legacy_import import _target
from tests.integration.test_migrations import DATABASE_URL, _configuration

NOW = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)


def _database() -> Database:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    return Database(DATABASE_URL)


def test_gc_is_dry_run_and_keeps_shared_active_and_recent_objects(tmp_path: Path) -> None:
    database = _database()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    try:
        target = _target(database)
        old = blobs.put(BytesIO(b"old unreferenced"), 100)
        active = blobs.put(BytesIO(b"shared active"), 100)
        recent = blobs.put(BytesIO(b"recent revoked"), 100)
        with database.transaction() as session:
            repository = SqlResearchRepository(session)
            old_id = repository.grant_document(
                target.project_id, canonical_publication_key="old", title="Old", blob=old
            )
            active_id = repository.grant_document(
                target.project_id, canonical_publication_key="active", title="Active", blob=active
            )
            recent_id = repository.grant_document(
                target.project_id, canonical_publication_key="recent", title="Recent", blob=recent
            )
            repository.revoke_document(
                target.project_id, old_id, revoked_at=NOW - timedelta(days=40)
            )
            repository.revoke_document(
                target.project_id, recent_id, revoked_at=NOW - timedelta(days=2)
            )
            session.execute(
                update(DocumentRow)
                .where(DocumentRow.id.in_([UUID(old_id), UUID(active_id)]))
                .values(created_at=NOW - timedelta(days=60))
            )
        service = RetentionService(database, blobs)
        plan = service.plan_gc(NOW, timedelta(days=30))
        assert [item.object_id for item in plan.items] == [old_id]
        assert blobs.stat(old.key).sha256 == old.sha256
        assert service.apply_gc(plan.id, confirmation="wrong").deleted == 0
        assert blobs.stat(old.key).sha256 == old.sha256
    finally:
        database.dispose()


def test_gc_rechecks_references_and_deletes_only_still_unreferenced_objects(tmp_path: Path) -> None:
    database = _database()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    try:
        first = _target(database)
        with database.transaction() as session:
            first_row = session.get(ProjectRow, UUID(first.project_id))
            assert first_row is not None
            second_id = "10000000-0000-0000-0000-000000000002"
            SqlUnitOfWork(session).projects.add_project(
                Project(
                    second_id,
                    str(first_row.workspace_id),
                    "Second migration project",
                    first.actor_user_id,
                    True,
                    NOW,
                )
            )
            second = LegacyImportTarget(database, second_id, first.actor_user_id)
        blob = blobs.put(BytesIO(b"candidate"), 100)
        with database.transaction() as session:
            repository = SqlResearchRepository(session)
            document_id = repository.grant_document(
                first.project_id,
                canonical_publication_key="candidate",
                title="Candidate",
                blob=blob,
            )
            repository.revoke_document(
                first.project_id, document_id, revoked_at=NOW - timedelta(days=50)
            )
            session.execute(
                update(DocumentRow)
                .where(DocumentRow.id == UUID(document_id))
                .values(created_at=NOW - timedelta(days=50))
            )
        service = RetentionService(database, blobs)
        stale_plan = service.plan_gc(NOW, timedelta(days=30))
        with database.transaction() as session:
            SqlResearchRepository(session).grant_document(
                second.project_id,
                canonical_publication_key="candidate",
                title="Candidate",
                blob=blob,
            )
        result = service.apply_gc(stale_plan.id, confirmation=stale_plan.id)
        assert result.deleted == 0
        assert result.skipped == 1
        assert blobs.stat(blob.key).sha256 == blob.sha256
    finally:
        database.dispose()


def test_gc_expires_temporary_artifacts_but_preserves_active_exports(tmp_path: Path) -> None:
    database = _database()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    try:
        target = _target(database)
        temporary = blobs.put(BytesIO(b"temporary"), 100)
        active = blobs.put(BytesIO(b"active export"), 100)
        with database.transaction() as session:
            repository = SqlResearchRepository(session)
            repository.add_artifact(
                target.project_id,
                run_id=None,
                kind="temporary_upload",
                blob_key=temporary.key,
                input_fingerprint="temp",
                generator_version="test",
                created_at=NOW - timedelta(days=50),
                expires_at=NOW - timedelta(days=40),
            )
            repository.add_artifact(
                target.project_id,
                run_id=None,
                kind="literature_review_pdf",
                blob_key=active.key,
                input_fingerprint="active",
                generator_version="test",
                created_at=NOW - timedelta(days=1),
                expires_at=None,
            )
        service = RetentionService(database, blobs)
        plan = service.plan_gc(NOW, timedelta(days=30))
        assert len(plan.items) == 1
        assert plan.items[0].object_kind == "artifact"
        result = service.apply_gc(plan.id, confirmation=plan.id)
        assert result.deleted == 1
        assert blobs.stat(active.key).sha256 == active.sha256
        with pytest.raises(BlobNotFound):
            blobs.stat(temporary.key)
        with database.transaction() as session:
            assert (
                session.scalar(select(ArtifactRow).where(ArtifactRow.blob_key == temporary.key))
                is None
            )
            audit = session.scalar(select(AuditEventRow))
            assert audit is not None
            assert audit.payload["size"] == len(b"temporary")
            assert "bytes" not in audit.payload
    finally:
        database.dispose()


def test_gc_refuses_stale_plan(tmp_path: Path) -> None:
    database = _database()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    try:
        target = _target(database)
        blob = blobs.put(BytesIO(b"stale"), 100)
        with database.transaction() as session:
            repository = SqlResearchRepository(session)
            document_id = repository.grant_document(
                target.project_id, canonical_publication_key="stale", title="Stale", blob=blob
            )
            repository.revoke_document(target.project_id, document_id, revoked_at=NOW)
            session.execute(
                update(DocumentRow)
                .where(DocumentRow.id == UUID(document_id))
                .values(created_at=NOW - timedelta(days=60))
            )
        service = RetentionService(
            database,
            blobs,
            clock=lambda: NOW + timedelta(days=2),
            maximum_plan_age=timedelta(days=1),
        )
        plan = service.plan_gc(NOW, timedelta(days=30))
        result = service.apply_gc(plan.id, confirmation=plan.id)
        assert result.stale is True
        assert result.deleted == 0
        assert blobs.stat(blob.key).sha256 == blob.sha256
    finally:
        database.dispose()
