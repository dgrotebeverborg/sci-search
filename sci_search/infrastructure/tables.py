"""SQLAlchemy mappings for identity, tenancy, sessions, and audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(300))
    affiliation: Mapped[str | None] = mapped_column(String(500))
    institution: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ExternalIdentityRow(Base):
    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issuer: Mapped[str] = mapped_column(String(1000), nullable=False)
    subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    is_personal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class WorkspaceMembershipRow(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint("role IN ('owner', 'editor', 'reviewer', 'viewer')", name="valid_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ProjectMembershipRow(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id"),
        CheckConstraint("role IN ('owner', 'editor', 'reviewer', 'viewer')", name="valid_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_project_occurred", "project_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(1000), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PublicationRow(Base):
    __tablename__ = "publications"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(2000), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    blob_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicationDocumentRow(Base):
    __tablename__ = "publication_documents"
    __table_args__ = (UniqueConstraint("publication_id", "document_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectDocumentGrantRow(Base):
    __tablename__ = "project_document_grants"
    __table_args__ = (UniqueConstraint("project_id", "document_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ResearchRunRow(Base):
    __tablename__ = "research_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(5000), nullable=False)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class RunDocumentRow(Base):
    __tablename__ = "run_documents"
    __table_args__ = (UniqueConstraint("run_id", "document_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    relation: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceRow(Base):
    __tablename__ = "evidence_records"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="SET NULL"), index=True
    )
    statement: Mapped[str] = mapped_column(String(10000), nullable=False)
    source_passage: Mapped[str] = mapped_column(String(20000), nullable=False)
    section: Mapped[str | None] = mapped_column(String(1000))
    page: Mapped[int | None]
    extraction_method: Mapped[str] = mapped_column(String(500), nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ValidationCheckRow(Base):
    __tablename__ = "validation_checks"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewRevisionRow(Base):
    __tablename__ = "review_revisions"
    __table_args__ = (UniqueConstraint("evidence_id", "evidence_version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    note: Mapped[str | None] = mapped_column(String(10000))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskOfBiasRecordRow(Base):
    __tablename__ = "risk_of_bias_records"
    __table_args__ = (UniqueConstraint("project_id", "study_id", "tool", "domain"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    study_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(200), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class RiskOfBiasRevisionRow(Base):
    __tablename__ = "risk_of_bias_revisions"
    __table_args__ = (
        UniqueConstraint("risk_of_bias_id", "revision"),
        CheckConstraint(
            "judgment IN ('unknown', 'low', 'some_concerns', 'high')",
            name="valid_judgment",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    risk_of_bias_id: Mapped[UUID] = mapped_column(
        ForeignKey("risk_of_bias_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    judgment: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text())
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewer_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("risk_of_bias_revisions.id", ondelete="RESTRICT")
    )


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    blob_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LegacyImportRow(Base):
    __tablename__ = "legacy_imports"
    __table_args__ = (UniqueConstraint("project_id", "source_fingerprint"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_root: Mapped[str] = mapped_column(String(2000), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'cancelled', 'failed', 'completed')",
            name="valid_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class JobCheckpointRow(Base):
    __tablename__ = "job_checkpoints"
    __table_args__ = (
        UniqueConstraint("job_id", "stage_name", "input_fingerprint", "implementation_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    implementation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StageAttemptRow(Base):
    __tablename__ = "stage_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_number"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(50))
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
