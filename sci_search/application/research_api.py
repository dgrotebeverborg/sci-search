"""Project-scoped research API use cases and deterministic in-memory adapter."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import PurePath
from typing import Protocol

from pypdf import PdfReader

from sci_search.application.authorization import (
    Action,
    AuthorizationContext,
    ProjectPolicy,
    ResourceNotFound,
)
from sci_search.application.projects import ProjectRepository


class ResourceVersionConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("resource version conflict")


class InvalidDocument(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResearchRunRecord:
    id: str
    project_id: str
    question: str
    review_depth: str
    status: str
    created_at: datetime
    updated_at: datetime
    version: int = 1


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    id: str
    project_id: str
    filename: str
    content_type: str
    content: bytes
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    project_id: str
    statement: str
    source_passage: str
    section: str | None
    page: int | None
    version: int
    created_at: datetime
    review_decision: str | None = None
    review_note: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationRecord:
    id: str
    project_id: str
    check_name: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DownloadRecord:
    filename: str
    content_type: str
    chunks: tuple[bytes, ...]

    def iter_chunks(self) -> Iterator[bytes]:
        yield from self.chunks


@dataclass(frozen=True, slots=True)
class ResearchAuditRecord:
    id: str
    project_id: str
    action: str
    entity_type: str
    occurred_at: datetime


class ResearchApiService(Protocol):
    def start_run(
        self,
        user_id: str,
        project_id: str,
        *,
        question: str,
        review_depth: str,
        idempotency_key: str,
    ) -> ResearchRunRecord: ...

    def get_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord: ...

    def cancel_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord: ...

    def retry_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord: ...

    def open_document(
        self, user_id: str, project_id: str, document_id: str
    ) -> DownloadRecord: ...

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
    ) -> DocumentRecord: ...

    def list_evidence(
        self, user_id: str, project_id: str, *, offset: int, limit: int
    ) -> tuple[list[EvidenceRecord], int]: ...

    def review_evidence(
        self,
        user_id: str,
        project_id: str,
        evidence_id: str,
        *,
        expected_version: int,
        decision: str,
        note: str | None,
    ) -> EvidenceRecord: ...

    def list_validation(self, user_id: str, project_id: str) -> list[ValidationRecord]: ...

    def open_export(self, user_id: str, project_id: str, export_id: str) -> DownloadRecord: ...

    def list_audit(self, user_id: str, project_id: str) -> list[ResearchAuditRecord]: ...


class InMemoryResearchApiService:
    """Reference adapter exercising the exact authorization contract used by HTTP routes."""

    def __init__(
        self,
        projects: ProjectRepository,
        *,
        clock: Callable[[], datetime],
        id_source: Callable[[], str],
        maximum_upload_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self._policy = ProjectPolicy(projects)
        self._clock = clock
        self._id_source = id_source
        self._maximum_upload_bytes = maximum_upload_bytes
        self._runs: dict[tuple[str, str], ResearchRunRecord] = {}
        self._run_idempotency: dict[tuple[str, str], str] = {}
        self._documents: dict[tuple[str, str], DocumentRecord] = {}
        self._evidence: dict[tuple[str, str], EvidenceRecord] = {}
        self._validations: dict[tuple[str, str], ValidationRecord] = {}
        self._exports: dict[tuple[str, str], DownloadRecord] = {}
        self._audits: list[ResearchAuditRecord] = []

    def start_run(
        self,
        user_id: str,
        project_id: str,
        *,
        question: str,
        review_depth: str,
        idempotency_key: str,
    ) -> ResearchRunRecord:
        self._require(Action.MANAGE_RUNS, user_id, project_id)
        existing_id = self._run_idempotency.get((project_id, idempotency_key))
        if existing_id is not None:
            return self._runs[(project_id, existing_id)]
        now = self._clock()
        run = ResearchRunRecord(
            self._id_source(), project_id, question, review_depth, "queued", now, now
        )
        self._runs[(project_id, run.id)] = run
        self._run_idempotency[(project_id, idempotency_key)] = run.id
        self._audit(project_id, "research_run.created", "research_run")
        return run

    def get_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord:
        self._require(Action.READ, user_id, project_id)
        try:
            return self._runs[(project_id, run_id)]
        except KeyError as error:
            raise ResourceNotFound from error

    def cancel_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord:
        self._require(Action.MANAGE_RUNS, user_id, project_id)
        run = self.get_run(user_id, project_id, run_id)
        if run.status not in {"queued", "running"}:
            raise ValueError("only queued or running jobs can be cancelled")
        updated = replace(run, status="cancel_requested", updated_at=self._clock(), version=run.version + 1)
        self._runs[(project_id, run_id)] = updated
        self._audit(project_id, "research_run.cancel_requested", "research_run")
        return updated

    def retry_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord:
        self._require(Action.MANAGE_RUNS, user_id, project_id)
        run = self.get_run(user_id, project_id, run_id)
        if run.status != "failed":
            raise ValueError("only failed jobs can be retried")
        updated = replace(run, status="queued", updated_at=self._clock(), version=run.version + 1)
        self._runs[(project_id, run_id)] = updated
        self._audit(project_id, "research_run.retry_scheduled", "research_run")
        return updated

    def open_document(self, user_id: str, project_id: str, document_id: str) -> DownloadRecord:
        self._require(Action.DOWNLOAD, user_id, project_id)
        try:
            document = self._documents[(project_id, document_id)]
        except KeyError as error:
            raise ResourceNotFound from error
        return DownloadRecord(document.filename, document.content_type, (document.content,))

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
        self._require(Action.MANAGE_RUNS, user_id, project_id)
        self.get_run(user_id, project_id, run_id)
        content = self._validate_pdf(filename, content_base64, authorization_confirmed)
        document = DocumentRecord(
            self._id_source(), project_id, filename, "application/pdf", content, self._clock()
        )
        self._documents[(project_id, document.id)] = document
        self._audit(project_id, "document.authorized_upload", "document")
        del candidate_id
        return document

    def list_evidence(
        self,
        user_id: str,
        project_id: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[EvidenceRecord], int]:
        self._require(Action.READ, user_id, project_id)
        records = sorted(
            (record for (scope, _), record in self._evidence.items() if scope == project_id),
            key=lambda record: (record.created_at, record.id),
        )
        return records[offset : offset + limit], len(records)

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
        self._require(Action.REVIEW, user_id, project_id)
        try:
            evidence = self._evidence[(project_id, evidence_id)]
        except KeyError as error:
            raise ResourceNotFound from error
        if evidence.version != expected_version:
            self._audit(project_id, "evidence.review_conflict", "evidence")
            raise ResourceVersionConflict
        updated = replace(
            evidence,
            version=evidence.version + 1,
            review_decision=decision,
            review_note=note,
        )
        self._evidence[(project_id, evidence_id)] = updated
        self._audit(project_id, "evidence.review_accepted", "evidence")
        return updated

    def list_validation(self, user_id: str, project_id: str) -> list[ValidationRecord]:
        self._require(Action.READ, user_id, project_id)
        return sorted(
            (record for (scope, _), record in self._validations.items() if scope == project_id),
            key=lambda record: (record.created_at, record.id),
        )

    def open_export(self, user_id: str, project_id: str, export_id: str) -> DownloadRecord:
        self._require(Action.DOWNLOAD, user_id, project_id)
        try:
            return self._exports[(project_id, export_id)]
        except KeyError as error:
            raise ResourceNotFound from error

    def list_audit(self, user_id: str, project_id: str) -> list[ResearchAuditRecord]:
        self._require(Action.MANAGE_MEMBERSHIP, user_id, project_id)
        return sorted(
            (record for record in self._audits if record.project_id == project_id),
            key=lambda record: (record.occurred_at, record.id),
        )

    def seed_run(
        self, project_id: str, run_id: str, question: str, *, status: str
    ) -> ResearchRunRecord:
        now = self._clock()
        run = ResearchRunRecord(run_id, project_id, question, "focused", status, now, now)
        self._runs[(project_id, run_id)] = run
        return run

    def seed_document(
        self,
        project_id: str,
        document_id: str,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> DocumentRecord:
        record = DocumentRecord(
            document_id, project_id, filename, content_type, content, self._clock()
        )
        self._documents[(project_id, document_id)] = record
        return record

    def seed_evidence(
        self,
        project_id: str,
        evidence_id: str,
        *,
        statement: str,
        source_passage: str,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            evidence_id,
            project_id,
            statement,
            source_passage,
            None,
            None,
            1,
            self._clock(),
        )
        self._evidence[(project_id, evidence_id)] = record
        return record

    def seed_validation(
        self, project_id: str, validation_id: str, check_name: str, status: str
    ) -> ValidationRecord:
        record = ValidationRecord(validation_id, project_id, check_name, status, self._clock())
        self._validations[(project_id, validation_id)] = record
        return record

    def seed_export(
        self,
        project_id: str,
        export_id: str,
        *,
        filename: str,
        content_type: str,
        chunks: tuple[bytes, ...],
    ) -> None:
        self._exports[(project_id, export_id)] = DownloadRecord(filename, content_type, chunks)

    def seed_audit(self, project_id: str, action: str, entity_type: str) -> None:
        self._audits.append(
            ResearchAuditRecord(self._id_source(), project_id, action, entity_type, self._clock())
        )

    def _validate_pdf(
        self, filename: str, content_base64: str, authorization_confirmed: bool
    ) -> bytes:
        if (
            not authorization_confirmed
            or not filename
            or PurePath(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or not filename.casefold().endswith(".pdf")
        ):
            raise InvalidDocument("invalid authorized upload")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error) as error:
            raise InvalidDocument("invalid authorized upload") from error
        if len(content) > self._maximum_upload_bytes or not content.startswith(b"%PDF-"):
            raise InvalidDocument("invalid authorized upload")
        try:
            reader = PdfReader(BytesIO(content))
            if not reader.pages:
                raise InvalidDocument("invalid authorized upload")
        except InvalidDocument:
            raise
        except Exception as error:
            raise InvalidDocument("invalid authorized upload") from error
        return content

    def _require(self, action: Action, user_id: str, project_id: str) -> None:
        self._policy.require(action, AuthorizationContext(user_id), project_id)

    def _audit(self, project_id: str, action: str, entity_type: str) -> None:
        self._audits.append(
            ResearchAuditRecord(self._id_source(), project_id, action, entity_type, self._clock())
        )
