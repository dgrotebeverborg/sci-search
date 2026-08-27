"""Reference-aware, fail-safe lifecycle management for stored blobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select

from sci_search.application.blobs import BlobNotFound, BlobStore
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.tables import (
    ArtifactRow,
    AuditEventRow,
    DocumentRow,
    EvidenceRow,
    ProjectDocumentGrantRow,
    PublicationDocumentRow,
    RunDocumentRow,
    StorageGCItemRow,
    StorageGCPlanRow,
)


@dataclass(frozen=True, slots=True)
class GCItem:
    object_kind: str
    object_id: str
    blob_key: str
    digest: str | None
    size: int
    reason: str
    reference_count: int


@dataclass(frozen=True, slots=True)
class GCPlan:
    id: str
    cutoff: datetime
    items: tuple[GCItem, ...]


@dataclass(frozen=True, slots=True)
class GCResult:
    plan_id: str
    deleted: int
    skipped: int
    stale: bool = False


class RetentionService:
    """Persist plans first and re-evaluate references immediately before deletion."""

    def __init__(
        self,
        database: Database,
        blobs: BlobStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_plan_age: timedelta = timedelta(hours=24),
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._database = database
        self._blobs = blobs
        self._clock = clock
        self._maximum_plan_age = maximum_plan_age
        self._batch_size = batch_size

    def plan_gc(self, now: datetime, grace_period: timedelta) -> GCPlan:
        if grace_period < timedelta(0):
            raise ValueError("grace period must not be negative")
        cutoff = now - grace_period
        plan_id = uuid4()
        candidates: list[StorageGCItemRow] = []
        with self._database.transaction() as session:
            session.add(
                StorageGCPlanRow(
                    id=plan_id,
                    status="planned",
                    cutoff=cutoff,
                    created_at=now,
                    applied_at=None,
                    version=1,
                )
            )
            session.flush()
            for document in session.scalars(
                select(DocumentRow).where(DocumentRow.created_at <= cutoff).order_by(DocumentRow.id)
            ):
                references = _document_references(session, document.id)
                if references != 0:
                    continue
                projects = [
                    str(value)
                    for value in session.scalars(
                        select(ProjectDocumentGrantRow.project_id).where(
                            ProjectDocumentGrantRow.document_id == document.id
                        )
                    )
                ]
                candidates.append(
                    StorageGCItemRow(
                        id=uuid4(),
                        plan_id=plan_id,
                        object_kind="document",
                        object_id=document.id,
                        blob_key=document.blob_key,
                        digest=document.sha256,
                        size=document.size,
                        reason="no active or scientific references after grace period",
                        reference_count=0,
                        project_ids_json=projects,
                        state="planned",
                    )
                )
            expired = session.scalars(
                select(ArtifactRow)
                .where(ArtifactRow.expires_at.is_not(None), ArtifactRow.expires_at <= cutoff)
                .order_by(ArtifactRow.id)
            )
            for artifact in expired:
                references = _artifact_blob_references(session, artifact)
                if references != 0:
                    continue
                try:
                    blob = self._blobs.stat(artifact.blob_key)
                    digest, size = blob.sha256, blob.size
                except BlobNotFound:
                    digest, size = None, 0
                candidates.append(
                    StorageGCItemRow(
                        id=uuid4(),
                        plan_id=plan_id,
                        object_kind="artifact",
                        object_id=artifact.id,
                        blob_key=artifact.blob_key,
                        digest=digest,
                        size=size,
                        reason="expired temporary or generated artifact after grace period",
                        reference_count=0,
                        project_ids_json=[str(artifact.project_id)],
                        state="planned",
                    )
                )
            session.add_all(candidates)
        return GCPlan(
            str(plan_id),
            cutoff,
            tuple(
                GCItem(
                    item.object_kind,
                    str(item.object_id),
                    item.blob_key,
                    item.digest,
                    item.size,
                    item.reason,
                    item.reference_count,
                )
                for item in candidates
            ),
        )

    def apply_gc(self, plan_id: str, confirmation: str) -> GCResult:
        if confirmation != plan_id:
            return GCResult(plan_id, 0, 0)
        plan_uuid = UUID(plan_id)
        with self._database.transaction() as session:
            plan = session.get(StorageGCPlanRow, plan_uuid)
            if plan is None or plan.status != "planned":
                return GCResult(plan_id, 0, 0, stale=True)
            if self._clock() - plan.created_at > self._maximum_plan_age:
                plan.status = "stale"
                return GCResult(plan_id, 0, 0, stale=True)
        deleted_count = 0
        skipped_count = 0
        while True:
            with self._database.transaction() as session:
                item_ids = list(
                    session.scalars(
                        select(StorageGCItemRow.id)
                        .where(
                            StorageGCItemRow.plan_id == plan_uuid,
                            StorageGCItemRow.state == "planned",
                        )
                        .order_by(StorageGCItemRow.id)
                        .limit(self._batch_size)
                    )
                )
            if not item_ids:
                break
            for item_id in item_ids:
                if self._apply_item(plan_uuid, item_id):
                    deleted_count += 1
                else:
                    skipped_count += 1
        with self._database.transaction() as session:
            plan = session.get(StorageGCPlanRow, plan_uuid)
            if plan is not None:
                plan.status = "applied"
                plan.applied_at = self._clock()
                plan.version += 1
        return GCResult(plan_id, deleted_count, skipped_count)

    def _apply_item(self, plan_id: UUID, item_id: UUID) -> bool:
        with self._database.transaction() as session:
            item = session.scalar(
                select(StorageGCItemRow)
                .where(
                    StorageGCItemRow.id == item_id,
                    StorageGCItemRow.plan_id == plan_id,
                    StorageGCItemRow.state == "planned",
                )
                .with_for_update()
            )
            if item is None:
                return False
            project_ids = list(item.project_ids_json)
            if item.object_kind == "document":
                document = session.scalar(
                    select(DocumentRow).where(DocumentRow.id == item.object_id).with_for_update()
                )
                if document is None or _document_references(session, document.id) != 0:
                    item.state = "skipped_referenced"
                    return False
                session.execute(
                    delete(ProjectDocumentGrantRow).where(
                        ProjectDocumentGrantRow.document_id == document.id,
                        ProjectDocumentGrantRow.revoked_at.is_not(None),
                    )
                )
                session.execute(
                    delete(PublicationDocumentRow).where(
                        PublicationDocumentRow.document_id == document.id
                    )
                )
                session.delete(document)
            else:
                artifact = session.scalar(
                    select(ArtifactRow).where(ArtifactRow.id == item.object_id).with_for_update()
                )
                if (
                    artifact is None
                    or artifact.expires_at is None
                    or artifact.expires_at > self._clock()
                    or _artifact_blob_references(session, artifact) != 0
                ):
                    item.state = "skipped_referenced"
                    return False
                session.delete(artifact)
            self._blobs.delete(item.blob_key)
            item.state = "deleted"
            for project_id in project_ids:
                session.add(
                    AuditEventRow(
                        id=uuid4(),
                        occurred_at=self._clock(),
                        actor_user_id=None,
                        project_id=UUID(project_id),
                        action="storage.blob_deleted",
                        entity_type=item.object_kind,
                        entity_id=str(item.object_id),
                        payload={
                            "blob_key": item.blob_key,
                            "digest": item.digest,
                            "size": item.size,
                            "reason": item.reason,
                        },
                    )
                )
            return True


def _document_references(session: Any, document_id: UUID) -> int:
    counts = (
        session.scalar(
            select(func.count())
            .select_from(ProjectDocumentGrantRow)
            .where(
                ProjectDocumentGrantRow.document_id == document_id,
                ProjectDocumentGrantRow.revoked_at.is_(None),
            )
        ),
        session.scalar(
            select(func.count())
            .select_from(EvidenceRow)
            .where(EvidenceRow.document_id == document_id)
        ),
        session.scalar(
            select(func.count())
            .select_from(RunDocumentRow)
            .where(RunDocumentRow.document_id == document_id)
        ),
    )
    return sum(int(value or 0) for value in counts)


def _artifact_blob_references(session: Any, artifact: ArtifactRow) -> int:
    documents = int(
        session.scalar(
            select(func.count())
            .select_from(DocumentRow)
            .where(DocumentRow.blob_key == artifact.blob_key)
        )
        or 0
    )
    artifacts = int(
        session.scalar(
            select(func.count())
            .select_from(ArtifactRow)
            .where(
                ArtifactRow.blob_key == artifact.blob_key,
                ArtifactRow.id != artifact.id,
                or_(ArtifactRow.expires_at.is_(None), ArtifactRow.expires_at > artifact.expires_at),
            )
        )
        or 0
    )
    return documents + artifacts
