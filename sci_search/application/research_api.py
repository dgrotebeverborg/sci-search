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
from sci_search.domain.risk_of_bias import RiskJudgment, RiskOfBiasRecord


class ResourceVersionConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("resource version conflict")


class InvalidDocument(ValueError):
    pass


class InvalidRiskOfBiasReference(ValueError):
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
    analysis_selection: dict[str, str] | None = None


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


@dataclass(frozen=True, slots=True)
class ExportRecord:
    id: str
    filename: str
    content_type: str


class ResearchApiService(Protocol):
    def list_runs(
        self,
        user_id: str,
        project_id: str,
        *,
        query: str = "",
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict: ...

    def get_dashboard(
        self, user_id: str, project_id: str, run_id: str, *, revision: int | None = None
    ) -> dict: ...

    def list_revisions(self, user_id: str, project_id: str, run_id: str) -> dict: ...

    def record_article_feedback(
        self,
        user_id: str,
        project_id: str,
        run_id: str,
        publication_id: str,
        *,
        decision: str,
        reason: str,
        expected_sequence: int,
        idempotency_key: str,
        reviewed_revision: int | None = None,
    ) -> dict: ...

    def retry_rebuild(self, user_id: str, project_id: str, run_id: str) -> dict: ...

    def analysis_models(self, user_id: str, project_id: str) -> dict: ...

    def interpret_question(
        self,
        user_id: str,
        project_id: str,
        question: str,
        *,
        analysis_selection: dict[str, str] | None = None,
    ) -> dict: ...

    def start_run(
        self,
        user_id: str,
        project_id: str,
        *,
        question: str,
        review_depth: str,
        idempotency_key: str,
        question_brief: dict | None = None,
        analysis_selection: dict[str, str] | None = None,
    ) -> ResearchRunRecord: ...

    def get_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord: ...

    def cancel_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord: ...

    def retry_run(self, user_id: str, project_id: str, run_id: str) -> ResearchRunRecord: ...

    def open_document(self, user_id: str, project_id: str, document_id: str) -> DownloadRecord: ...

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

    def list_exports(self, user_id: str, project_id: str) -> list[ExportRecord]: ...

    def list_audit(self, user_id: str, project_id: str) -> list[ResearchAuditRecord]: ...

    def list_risk_of_bias(
        self, user_id: str, project_id: str, *, study_id: str | None = None
    ) -> list[RiskOfBiasRecord]: ...

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
    ) -> RiskOfBiasRecord: ...

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
    ) -> RiskOfBiasRecord: ...


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
        self._risk_of_bias: dict[tuple[str, str], RiskOfBiasRecord] = {}
        self._risk_of_bias_revisions: dict[str, RiskOfBiasRecord] = {}

    def analysis_models(self, user_id: str, project_id: str) -> dict:
        from sci_search.model_provider import analysis_choices

        self._require(Action.READ, user_id, project_id)
        return analysis_choices()

    def interpret_question(
        self,
        user_id: str,
        project_id: str,
        question: str,
        *,
        analysis_selection: dict[str, str] | None = None,
    ) -> dict:
        from sci_search.question_interpretation import interpret_question

        self._require(Action.MANAGE_RUNS, user_id, project_id)
        from sci_search.model_provider import analysis_scope, resolve_selection

        with analysis_scope(resolve_selection(analysis_selection)):
            return interpret_question(question)

    def start_run(
        self,
        user_id: str,
        project_id: str,
        *,
        question: str,
        review_depth: str,
        idempotency_key: str,
        question_brief: dict | None = None,
        analysis_selection: dict[str, str] | None = None,
    ) -> ResearchRunRecord:
        self._require(Action.MANAGE_RUNS, user_id, project_id)
        existing_id = self._run_idempotency.get((project_id, idempotency_key))
        if existing_id is not None:
            return self._runs[(project_id, existing_id)]
        from sci_search.model_provider import resolve_selection

        selection = resolve_selection(analysis_selection)
        now = self._clock()
        run = ResearchRunRecord(
            self._id_source(),
            project_id,
            question,
            review_depth,
            "queued",
            now,
            now,
            analysis_selection=selection,
        )
        self._runs[(project_id, run.id)] = run
        self._run_idempotency[(project_id, idempotency_key)] = run.id
        self._audit(project_id, "research_run.created", "research_run")
        return run

    def list_runs(self, user_id, project_id, *, query="", cursor=None, limit=30):
        from dataclasses import asdict

        self._require(Action.READ, user_id, project_id)
        rows = sorted(
            (
                r
                for (p, _), r in self._runs.items()
                if p == project_id and query.casefold() in r.question.casefold()
            ),
            key=lambda r: (r.created_at, r.id),
            reverse=True,
        )
        if cursor:
            matching = next((i for i, r in enumerate(rows) if r.id == cursor), None)
            if matching is None:
                raise ValueError("invalid history cursor")
            rows = rows[matching + 1 :]
        return {
            "items": [asdict(r) for r in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        }

    def get_dashboard(self, user_id, project_id, run_id, *, revision=None) -> dict:
        self.get_run(user_id, project_id, run_id)
        raise ResourceNotFound

    def list_revisions(self, user_id, project_id, run_id):
        self.get_run(user_id, project_id, run_id)
        return {"items": []}

    def record_article_feedback(
        self,
        user_id,
        project_id,
        run_id,
        publication_id,
        *,
        decision,
        reason,
        expected_sequence,
        idempotency_key,
        reviewed_revision=None,
    ) -> dict:
        self._require(Action.REVIEW, user_id, project_id)
        self.get_run(user_id, project_id, run_id)
        raise ValueError("article feedback requires a saved dashboard")

    def retry_rebuild(self, user_id, project_id, run_id) -> dict:
        self._require(Action.REVIEW, user_id, project_id)
        self.get_run(user_id, project_id, run_id)
        raise ValueError("dashboard rebuilding requires a persistent research service")

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
        updated = replace(
            run, status="cancel_requested", updated_at=self._clock(), version=run.version + 1
        )
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

    def list_exports(self, user_id: str, project_id: str) -> list[ExportRecord]:
        self._require(Action.DOWNLOAD, user_id, project_id)
        return [
            ExportRecord(export_id, download.filename, download.content_type)
            for (scope, export_id), download in sorted(self._exports.items())
            if scope == project_id
        ]

    def list_audit(self, user_id: str, project_id: str) -> list[ResearchAuditRecord]:
        self._require(Action.MANAGE_MEMBERSHIP, user_id, project_id)
        return sorted(
            (record for record in self._audits if record.project_id == project_id),
            key=lambda record: (record.occurred_at, record.id),
        )

    def list_risk_of_bias(
        self, user_id: str, project_id: str, *, study_id: str | None = None
    ) -> list[RiskOfBiasRecord]:
        self._require(Action.READ, user_id, project_id)
        return sorted(
            (
                record
                for (scope, _), record in self._risk_of_bias.items()
                if scope == project_id and (study_id is None or record.study_id == study_id)
            ),
            key=lambda record: (record.study_id, record.tool, record.domain, record.id),
        )

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
        self._require(Action.REVIEW, user_id, project_id)
        self._validate_risk_sources(project_id, source_evidence_ids)
        try:
            record = RiskOfBiasRecord(
                id=self._id_source(),
                revision_id=self._id_source(),
                project_id=project_id,
                study_id=study_id,
                tool=tool,
                domain=domain,
                judgment=judgment,
                rationale=rationale,
                source_evidence_ids=source_evidence_ids,
                reviewer_user_id=user_id,
                created_at=self._clock(),
                revision=1,
                previous_revision_id=None,
            )
        except ValueError as error:
            raise InvalidRiskOfBiasReference("invalid risk-of-bias judgment") from error
        self._risk_of_bias[(project_id, record.id)] = record
        self._risk_of_bias_revisions[record.revision_id] = record
        self._audit(project_id, "risk_of_bias.created", "risk_of_bias")
        return record

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
        self._require(Action.REVIEW, user_id, project_id)
        try:
            current = self._risk_of_bias[(project_id, record_id)]
        except KeyError as error:
            raise ResourceNotFound from error
        if current.revision != expected_revision:
            self._audit(project_id, "risk_of_bias.revision_conflict", "risk_of_bias")
            raise ResourceVersionConflict
        self._validate_risk_sources(project_id, source_evidence_ids)
        try:
            revised = RiskOfBiasRecord(
                id=current.id,
                revision_id=self._id_source(),
                project_id=project_id,
                study_id=study_id,
                tool=tool,
                domain=domain,
                judgment=judgment,
                rationale=rationale,
                source_evidence_ids=source_evidence_ids,
                reviewer_user_id=user_id,
                created_at=self._clock(),
                revision=current.revision + 1,
                previous_revision_id=current.revision_id,
            )
        except ValueError as error:
            raise InvalidRiskOfBiasReference("invalid risk-of-bias judgment") from error
        self._risk_of_bias[(project_id, record_id)] = revised
        self._risk_of_bias_revisions[revised.revision_id] = revised
        self._audit(project_id, "risk_of_bias.revised", "risk_of_bias")
        return revised

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

    def seed_risk_of_bias(
        self,
        project_id: str,
        record_id: str,
        *,
        study_id: str,
        tool: str,
        domain: str,
        judgment: str,
        reviewer_user_id: str,
    ) -> RiskOfBiasRecord:
        record = RiskOfBiasRecord(
            id=record_id,
            revision_id=f"{record_id}:revision:1",
            project_id=project_id,
            study_id=study_id,
            tool=tool,
            domain=domain,
            judgment=RiskJudgment(judgment),
            rationale=None,
            source_evidence_ids=(),
            reviewer_user_id=reviewer_user_id,
            created_at=self._clock(),
            revision=1,
            previous_revision_id=None,
        )
        self._risk_of_bias[(project_id, record.id)] = record
        self._risk_of_bias_revisions[record.revision_id] = record
        return record

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

    def _validate_risk_sources(self, project_id: str, source_evidence_ids: tuple[str, ...]) -> None:
        if any(
            (project_id, evidence_id) not in self._evidence for evidence_id in source_evidence_ids
        ):
            raise InvalidRiskOfBiasReference("source evidence is not available in this project")

    def _audit(self, project_id: str, action: str, entity_type: str) -> None:
        self._audits.append(
            ResearchAuditRecord(self._id_source(), project_id, action, entity_type, self._clock())
        )
