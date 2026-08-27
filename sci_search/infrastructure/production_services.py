"""Transaction-scoped production service adapters over PostgreSQL and object storage."""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
from collections.abc import Callable
from datetime import datetime
from io import BytesIO
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from pypdf import PdfReader
from sqlalchemy import func, select

from sci_search.application.authorization import (
    Action,
    AuthorizationContext,
    ProjectPolicy,
    ResourceNotFound,
)
from sci_search.application.blobs import BlobStore, content_addressed_key
from sci_search.application.projects import (
    Membership,
    Project,
    ProjectRole,
    ProjectService,
    Workspace,
)
from sci_search.application.research_api import (
    DocumentRecord,
    DownloadRecord,
    EvidenceRecord,
    ExportRecord,
    InvalidDocument,
    InvalidRiskOfBiasReference,
    ResearchApiService,
    ResearchAuditRecord,
    ResearchRunRecord,
    ResourceVersionConflict,
    ValidationRecord,
)
from sci_search.application.sessions import IssuedSession, Session, SessionService
from sci_search.domain.risk_of_bias import RiskJudgment, RiskOfBiasRecord
from sci_search.infrastructure.database import Database, lock_blob_key
from sci_search.infrastructure.queue import JobQueue
from sci_search.infrastructure.repositories import (
    SqlProjectAuditRepository,
    SqlProjectRepository,
    SqlResearchRepository,
    SqlSessionRepository,
)
from sci_search.infrastructure.tables import (
    ArtifactRow,
    AuditEventRow,
    DocumentRow,
    EvidenceRow,
    JobRow,
    PublicationDocumentRow,
    PublicationRow,
    ResearchRunRow,
    ReviewRevisionRow,
    RiskOfBiasRecordRow,
    RiskOfBiasRevisionRow,
    ValidationCheckRow,
)


class DatabaseSessionService:
    """Persist every browser-session operation in its own short transaction."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime],
        token_source: Callable[[int], str] | None = None,
    ) -> None:
        self._database = database
        self._clock = clock
        self._token_source = token_source

    def _service(self, session: Any) -> SessionService:
        arguments: dict[str, Any] = {"clock": self._clock}
        if self._token_source is not None:
            arguments["token_source"] = self._token_source
        return SessionService(SqlSessionRepository(session), **arguments)

    def create(self, user_id: str) -> IssuedSession:
        with self._database.transaction() as session:
            return self._service(session).create(user_id)

    def authenticate(self, token: str) -> Session:
        with self._database.transaction() as session:
            return self._service(session).authenticate(token)

    def rotate(self, token: str) -> IssuedSession:
        with self._database.transaction() as session:
            return self._service(session).rotate(token)

    def revoke(self, token: str) -> None:
        with self._database.transaction() as session:
            self._service(session).revoke(token)

    def revoke_user(self, user_id: str) -> int:
        with self._database.transaction() as session:
            return self._service(session).revoke_user(user_id)


class DatabaseProjectService:
    """Run each project use case in one database transaction, including audit writes."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime],
        id_source: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._database = database
        self._clock = clock
        self._id_source = id_source

    def _service(self, session: Any) -> ProjectService:
        return ProjectService(
            SqlProjectRepository(session),
            SqlProjectAuditRepository(session),
            clock=self._clock,
            id_source=self._id_source,
        )

    def list_for_user(self, user_id: str) -> list[Project]:
        with self._database.transaction() as session:
            return self._service(session).list_for_user(user_id)

    def list_workspaces_for_user(self, user_id: str) -> list[Workspace]:
        with self._database.transaction() as session:
            return self._service(session).list_workspaces_for_user(user_id)

    def get(self, user_id: str, project_id: str) -> Project:
        with self._database.transaction() as session:
            return self._service(session).get(user_id, project_id)

    def role_for_user(self, user_id: str, project_id: str) -> ProjectRole:
        with self._database.transaction() as session:
            return self._service(session).role_for_user(user_id, project_id)

    def create(self, user_id: str, workspace_id: str, name: str, is_private: bool) -> Project:
        with self._database.transaction() as session:
            return self._service(session).create(user_id, workspace_id, name, is_private)

    def rename(self, user_id: str, project_id: str, name: str) -> Project:
        with self._database.transaction() as session:
            return self._service(session).rename(user_id, project_id, name)

    def delete(self, user_id: str, project_id: str) -> None:
        with self._database.transaction() as session:
            self._service(session).delete(user_id, project_id)

    def list_members(self, user_id: str, project_id: str) -> list[Membership]:
        with self._database.transaction() as session:
            return self._service(session).list_members(user_id, project_id)

    def add_member(
        self,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
    ) -> Membership:
        with self._database.transaction() as session:
            return self._service(session).add_member(
                actor_user_id, project_id, subject_user_id, role
            )

    def change_member_role(
        self,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
    ) -> Membership:
        with self._database.transaction() as session:
            return self._service(session).change_member_role(
                actor_user_id, project_id, subject_user_id, role
            )

    def remove_member(self, actor_user_id: str, project_id: str, subject_user_id: str) -> None:
        with self._database.transaction() as session:
            self._service(session).remove_member(actor_user_id, project_id, subject_user_id)


class DatabaseResearchApiService(ResearchApiService):
    """Durable project-scoped API records backed by SQL, S3, and a wakeup queue."""

    def __init__(
        self,
        database: Database,
        blob_store: BlobStore,
        queue: JobQueue,
        *,
        clock: Callable[[], datetime],
        maximum_upload_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self._database = database
        self._blobs = blob_store
        self._queue = queue
        self._clock = clock
        self._maximum_upload_bytes = maximum_upload_bytes

    def start_run(
        self,
        user_id: str,
        project_id: str,
        *,
        question: str,
        review_depth: str,
        idempotency_key: str,
    ) -> ResearchRunRecord:
        from sci_search.infrastructure.jobs import SqlJobRepository

        with self._database.transaction() as session:
            self._require(session, Action.MANAGE_RUNS, user_id, project_id)
            jobs = SqlJobRepository(session)
            job = jobs.create(
                project_id,
                created_by_user_id=user_id,
                idempotency_key=idempotency_key,
                first_stage="research",
                input_payload={
                    "question": question,
                    "review_depth": review_depth,
                    "project_id": project_id,
                },
                created_at=self._clock(),
            )
            existing = session.scalar(
                select(ResearchRunRow).where(
                    ResearchRunRow.project_id == UUID(project_id),
                    ResearchRunRow.configuration_json["job_id"].as_string() == job.id,
                )
            )
            if existing is None:
                existing = ResearchRunRow(
                    id=uuid4(),
                    project_id=UUID(project_id),
                    created_by_user_id=UUID(user_id),
                    question=question,
                    configuration_json={
                        "review_depth": review_depth,
                        "idempotency_key": idempotency_key,
                        "job_id": job.id,
                    },
                    status=job.status.value,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    version=job.version,
                )
                session.add(existing)
                session.flush([existing])
                job_row = session.get(JobRow, UUID(job.id))
                if job_row is None:
                    raise RuntimeError("created job disappeared")
                job_row.input_json = {**job_row.input_json, "run_id": str(existing.id)}
            record = self._run_record(existing, job)
        self._queue.enqueue(job.id, job.current_stage)
        return record

    def get_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord:
        with self._database.transaction() as session:
            self._require(session, Action.READ, user_id, project_id)
            row, job = self._run_and_job(session, project_id, run_id)
            return self._run_record(row, job)

    def cancel_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord:
        from sci_search.infrastructure.jobs import SqlJobRepository

        with self._database.transaction() as session:
            self._require(session, Action.MANAGE_RUNS, user_id, project_id)
            row, job = self._run_and_job(session, project_id, run_id)
            updated = SqlJobRepository(session).request_cancel(
                project_id, job.id, now=self._clock()
            )
            return self._run_record(row, updated)

    def retry_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord:
        from sci_search.infrastructure.jobs import SqlJobRepository

        with self._database.transaction() as session:
            self._require(session, Action.MANAGE_RUNS, user_id, project_id)
            row, job = self._run_and_job(session, project_id, run_id)
            updated = SqlJobRepository(session).retry_failed(job.id, now=self._clock())
            record = self._run_record(row, updated)
        self._queue.enqueue(updated.id, updated.current_stage)
        return record

    def open_document(self, user_id: str, project_id: str, document_id: str) -> DownloadRecord:
        with self._database.transaction() as session:
            self._require(session, Action.DOWNLOAD, user_id, project_id)
            key = SqlResearchRepository(session).resolve_blob_key(project_id, document_id)
            row = session.get(DocumentRow, UUID(document_id))
            if row is None:
                from sci_search.application.authorization import ResourceNotFound

                raise ResourceNotFound
            title = session.scalar(
                select(PublicationRow.title)
                .join(
                    PublicationDocumentRow,
                    PublicationDocumentRow.publication_id == PublicationRow.id,
                )
                .where(PublicationDocumentRow.document_id == row.id)
                .limit(1)
            )
            content_type = row.content_type
        return DownloadRecord(
            _download_filename(str(title or document_id), content_type),
            content_type,
            _read_chunks(self._blobs.open(key)),
        )

    def upload_document(
        self,
        user_id: str,
        project_id: str,
        *,
        run_id: str,
        candidate_id: str,
        filename: str,
        content_base64: str,
        authorization_confirmed: bool,
    ) -> DocumentRecord:
        now = self._clock()
        with self._database.transaction() as session:
            self._require(session, Action.MANAGE_RUNS, user_id, project_id)
            try:
                run_uuid = UUID(run_id)
            except ValueError:
                raise ResourceNotFound from None
            run_exists = session.scalar(
                select(ResearchRunRow.id).where(
                    ResearchRunRow.id == run_uuid,
                    ResearchRunRow.project_id == UUID(project_id),
                )
            )
            if run_exists is None:
                raise ResourceNotFound
            content = _validate_pdf(
                filename,
                content_base64,
                authorization_confirmed,
                self._maximum_upload_bytes,
            )
            expected_digest = hashlib.sha256(content).hexdigest()
            lock_blob_key(session, content_addressed_key(expected_digest))
            blob = self._blobs.put(
                BytesIO(content),
                self._maximum_upload_bytes,
                content_type="application/pdf",
                expected_sha256=expected_digest,
            )
            repository = SqlResearchRepository(session)
            document_id = repository.grant_document(
                project_id,
                canonical_publication_key=f"candidate:{candidate_id}",
                title=filename,
                blob=blob,
                metadata={"researcher_supplied": True},
            )
            repository.link_run_document(
                project_id, run_id, document_id, relation="researcher_supplied"
            )
        return DocumentRecord(document_id, project_id, filename, "application/pdf", content, now)

    def list_evidence(
        self, user_id: str, project_id: str, *, offset: int, limit: int
    ) -> tuple[list[EvidenceRecord], int]:
        with self._database.transaction() as session:
            self._require(session, Action.READ, user_id, project_id)
            scope = EvidenceRow.project_id == UUID(project_id)
            total = int(
                session.scalar(select(func.count()).select_from(EvidenceRow).where(scope)) or 0
            )
            rows = list(
                session.scalars(
                    select(EvidenceRow)
                    .where(scope)
                    .order_by(EvidenceRow.created_at, EvidenceRow.id)
                    .offset(offset)
                    .limit(limit)
                )
            )
            return [self._evidence_record(session, row) for row in rows], total

    def review_evidence(
        self,
        user_id: str,
        project_id: str,
        evidence_id: str,
        *,
        expected_version: int,
        decision: str,
        note: str | None,
    ) -> EvidenceRecord:
        with self._database.transaction() as session:
            self._require(session, Action.REVIEW, user_id, project_id)
            accepted = SqlResearchRepository(session).try_review(
                project_id,
                evidence_id,
                reviewer_user_id=user_id,
                expected_version=expected_version,
                decision=decision,
                note=note,
                reviewed_at=self._clock(),
            )
            if not accepted:
                raise ResourceVersionConflict
            row = session.scalar(
                select(EvidenceRow).where(
                    EvidenceRow.id == UUID(evidence_id),
                    EvidenceRow.project_id == UUID(project_id),
                )
            )
            if row is None:
                from sci_search.application.authorization import ResourceNotFound

                raise ResourceNotFound
            return self._evidence_record(session, row)

    def list_validation(self, user_id: str, project_id: str) -> list[ValidationRecord]:
        with self._database.transaction() as session:
            self._require(session, Action.READ, user_id, project_id)
            rows = session.execute(
                select(ValidationCheckRow, EvidenceRow.project_id)
                .join(EvidenceRow, EvidenceRow.id == ValidationCheckRow.evidence_id)
                .where(EvidenceRow.project_id == UUID(project_id))
                .order_by(ValidationCheckRow.created_at, ValidationCheckRow.id)
            ).all()
            return [
                ValidationRecord(
                    str(row.id), project_id, row.check_name, row.status, row.created_at
                )
                for row, _scope in rows
            ]

    def open_export(self, user_id: str, project_id: str, export_id: str) -> DownloadRecord:
        with self._database.transaction() as session:
            self._require(session, Action.DOWNLOAD, user_id, project_id)
            row = session.scalar(
                select(ArtifactRow).where(
                    ArtifactRow.id == UUID(export_id), ArtifactRow.project_id == UUID(project_id)
                )
            )
            if row is None:
                from sci_search.application.authorization import ResourceNotFound

                raise ResourceNotFound
            filename, content_type = _artifact_metadata(row.kind, row.id)
            key = row.blob_key
        return DownloadRecord(filename, content_type, _read_chunks(self._blobs.open(key)))

    def list_exports(self, user_id: str, project_id: str) -> list[ExportRecord]:
        with self._database.transaction() as session:
            self._require(session, Action.DOWNLOAD, user_id, project_id)
            rows = list(
                session.scalars(
                    select(ArtifactRow)
                    .where(ArtifactRow.project_id == UUID(project_id))
                    .order_by(ArtifactRow.created_at, ArtifactRow.id)
                )
            )
            return [
                ExportRecord(str(row.id), *_artifact_metadata(row.kind, row.id)) for row in rows
            ]

    def list_audit(self, user_id: str, project_id: str) -> list[ResearchAuditRecord]:
        with self._database.transaction() as session:
            self._require(session, Action.MANAGE_MEMBERSHIP, user_id, project_id)
            rows = list(
                session.scalars(
                    select(AuditEventRow)
                    .where(AuditEventRow.project_id == UUID(project_id))
                    .order_by(AuditEventRow.occurred_at, AuditEventRow.id)
                )
            )
            return [
                ResearchAuditRecord(
                    str(row.id), project_id, row.action, row.entity_type, row.occurred_at
                )
                for row in rows
            ]

    def list_risk_of_bias(
        self, user_id: str, project_id: str, *, study_id: str | None = None
    ) -> list[RiskOfBiasRecord]:
        with self._database.transaction() as session:
            self._require(session, Action.READ, user_id, project_id)
            statement = (
                select(RiskOfBiasRecordRow, RiskOfBiasRevisionRow)
                .join(
                    RiskOfBiasRevisionRow,
                    (RiskOfBiasRevisionRow.risk_of_bias_id == RiskOfBiasRecordRow.id)
                    & (RiskOfBiasRevisionRow.revision == RiskOfBiasRecordRow.current_revision),
                )
                .where(RiskOfBiasRecordRow.project_id == UUID(project_id))
            )
            if study_id is not None:
                statement = statement.where(RiskOfBiasRecordRow.study_id == UUID(study_id))
            rows = session.execute(
                statement.order_by(
                    RiskOfBiasRecordRow.study_id,
                    RiskOfBiasRecordRow.tool,
                    RiskOfBiasRecordRow.domain,
                )
            ).all()
            return [self._risk_record(record, revision) for record, revision in rows]

    def create_risk_of_bias(
        self,
        user_id: str,
        project_id: str,
        *,
        study_id: str,
        tool: str,
        domain: str,
        judgment: RiskJudgment,
        rationale: str | None,
        source_evidence_ids: tuple[str, ...],
    ) -> RiskOfBiasRecord:
        with self._database.transaction() as session:
            self._require(session, Action.REVIEW, user_id, project_id)
            try:
                record_id = SqlResearchRepository(session).add_risk_of_bias(
                    project_id,
                    study_id=study_id,
                    reviewer_user_id=user_id,
                    tool=tool,
                    domain=domain,
                    judgment=judgment.value,
                    rationale=rationale,
                    source_evidence_ids=source_evidence_ids,
                    reviewed_at=self._clock(),
                )
            except ValueError as error:
                raise InvalidRiskOfBiasReference(str(error)) from error
            return self._one_risk(session, project_id, record_id)

    def revise_risk_of_bias(
        self,
        user_id: str,
        project_id: str,
        record_id: str,
        *,
        expected_revision: int,
        study_id: str,
        tool: str,
        domain: str,
        judgment: RiskJudgment,
        rationale: str | None,
        source_evidence_ids: tuple[str, ...],
    ) -> RiskOfBiasRecord:
        del study_id, tool, domain
        with self._database.transaction() as session:
            self._require(session, Action.REVIEW, user_id, project_id)
            try:
                accepted = SqlResearchRepository(session).try_revise_risk_of_bias(
                    project_id,
                    record_id,
                    reviewer_user_id=user_id,
                    expected_revision=expected_revision,
                    judgment=judgment.value,
                    rationale=rationale,
                    source_evidence_ids=source_evidence_ids,
                    reviewed_at=self._clock(),
                )
            except ValueError as error:
                raise InvalidRiskOfBiasReference(str(error)) from error
            if not accepted:
                raise ResourceVersionConflict
            return self._one_risk(session, project_id, record_id)

    @staticmethod
    def _require(session: Any, action: Action, user_id: str, project_id: str) -> None:
        ProjectPolicy(SqlProjectRepository(session)).require(
            action, AuthorizationContext(user_id), project_id
        )

    @staticmethod
    def _run_record(row: ResearchRunRow, job: Any) -> ResearchRunRecord:
        return ResearchRunRecord(
            str(row.id),
            str(row.project_id),
            row.question,
            str(row.configuration_json.get("review_depth") or "research"),
            job.status.value,
            row.created_at,
            job.updated_at,
            job.version,
        )

    @staticmethod
    def _run_and_job(session: Any, project_id: str, run_id: str) -> tuple[ResearchRunRow, Any]:
        from sci_search.application.authorization import ResourceNotFound
        from sci_search.infrastructure.jobs import SqlJobRepository

        row = session.scalar(
            select(ResearchRunRow).where(
                ResearchRunRow.id == UUID(run_id),
                ResearchRunRow.project_id == UUID(project_id),
            )
        )
        if row is None:
            raise ResourceNotFound
        job_id = str(row.configuration_json.get("job_id") or "")
        if not job_id:
            raise ResourceNotFound
        return row, SqlJobRepository(session).get(project_id, job_id)

    @staticmethod
    def _evidence_record(session: Any, row: EvidenceRow) -> EvidenceRecord:
        review = session.scalar(
            select(ReviewRevisionRow)
            .where(ReviewRevisionRow.evidence_id == row.id)
            .order_by(ReviewRevisionRow.evidence_version.desc())
            .limit(1)
        )
        return EvidenceRecord(
            str(row.id),
            str(row.project_id),
            row.statement,
            row.source_passage,
            row.section,
            row.page,
            row.version,
            row.created_at,
            review.decision if review else None,
            review.note if review else None,
        )

    @staticmethod
    def _risk_record(
        record: RiskOfBiasRecordRow, revision: RiskOfBiasRevisionRow
    ) -> RiskOfBiasRecord:
        return RiskOfBiasRecord(
            str(record.id),
            str(revision.id),
            str(record.project_id),
            str(record.study_id),
            record.tool,
            record.domain,
            RiskJudgment(revision.judgment),
            revision.rationale,
            tuple(revision.source_evidence_ids),
            str(revision.reviewer_user_id),
            revision.created_at,
            revision.revision,
            str(revision.previous_revision_id) if revision.previous_revision_id else None,
        )

    def _one_risk(self, session: Any, project_id: str, record_id: str) -> RiskOfBiasRecord:
        row = session.execute(
            select(RiskOfBiasRecordRow, RiskOfBiasRevisionRow)
            .join(
                RiskOfBiasRevisionRow,
                (RiskOfBiasRevisionRow.risk_of_bias_id == RiskOfBiasRecordRow.id)
                & (RiskOfBiasRevisionRow.revision == RiskOfBiasRecordRow.current_revision),
            )
            .where(
                RiskOfBiasRecordRow.id == UUID(record_id),
                RiskOfBiasRecordRow.project_id == UUID(project_id),
            )
        ).one()
        return self._risk_record(*row)


def _validate_pdf(filename: str, encoded: str, confirmed: bool, maximum: int) -> bytes:
    if (
        not confirmed
        or not filename
        or PurePath(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or not filename.casefold().endswith(".pdf")
    ):
        raise InvalidDocument("invalid authorized upload")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise InvalidDocument("invalid authorized upload") from error
    if len(content) > maximum or not content.startswith(b"%PDF-"):
        raise InvalidDocument("invalid authorized upload")
    try:
        if not PdfReader(BytesIO(content)).pages:
            raise InvalidDocument("invalid authorized upload")
    except InvalidDocument:
        raise
    except Exception as error:
        raise InvalidDocument("invalid authorized upload") from error
    return content


def _read_chunks(stream: Any) -> tuple[bytes, ...]:
    try:
        chunks: list[bytes] = []
        while chunk := stream.read(1024 * 1024):
            chunks.append(chunk)
        return tuple(chunks)
    finally:
        stream.close()


def _download_filename(title: str, content_type: str) -> str:
    suffix = mimetypes.guess_extension(content_type) or ".bin"
    safe = "".join(
        character if character.isalnum() or character in " ._-" else "_" for character in title
    )
    return (safe.strip() or "document")[:180] + suffix


def _artifact_metadata(kind: str, identifier: UUID) -> tuple[str, str]:
    lower = kind.casefold()
    if lower.endswith(".pdf") or "pdf" in lower:
        return f"{kind.removesuffix('.pdf')}-{identifier}.pdf", "application/pdf"
    if lower.endswith(".zip") or "package" in lower:
        return f"{kind.removesuffix('.zip')}-{identifier}.zip", "application/zip"
    if lower.endswith(".json") or "json" in lower:
        return f"{kind.removesuffix('.json')}-{identifier}.json", "application/json"
    return f"{kind}-{identifier}.bin", "application/octet-stream"
