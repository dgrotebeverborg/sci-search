"""Shared API schemas with strict input handling."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sci_search.application.projects import ProjectRole
from sci_search.domain.risk_of_bias import RiskJudgment
from sci_search.question_interpretation import QuestionBrief


class ApiSchema(BaseModel):
    """Base schema that rejects unrecognised client fields."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiSchema):
    status: str


class SessionResponse(ApiSchema):
    user_id: str
    csrf_token: str


class ErrorResponse(ApiSchema):
    detail: str


class ProjectCreate(ApiSchema):
    workspace_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    is_private: bool = True


class ProjectUpdate(ApiSchema):
    name: str = Field(min_length=1, max_length=300)


class ProjectResponse(ApiSchema):
    id: str
    workspace_id: str
    name: str
    owner_user_id: str
    is_private: bool
    created_at: datetime
    role: ProjectRole


class ProjectListResponse(ApiSchema):
    items: list[ProjectResponse]


class WorkspaceResponse(ApiSchema):
    id: str
    name: str
    is_personal: bool


class WorkspaceListResponse(ApiSchema):
    items: list[WorkspaceResponse]


class MembershipCreate(ApiSchema):
    user_id: str = Field(min_length=1, max_length=100)
    role: ProjectRole


class MembershipUpdate(ApiSchema):
    role: ProjectRole


class MembershipResponse(ApiSchema):
    id: str
    user_id: str
    role: ProjectRole
    active: bool
    created_at: datetime


class MembershipListResponse(ApiSchema):
    items: list[MembershipResponse]


class AnalysisSelection(ApiSchema):
    provider: Literal["mistral", "openai"]
    model: str = Field(min_length=1, max_length=200)


class QuestionInterpretationCreate(ApiSchema):
    analysis_selection: AnalysisSelection | None = None
    question: str = Field(min_length=3, max_length=5000)


class RunCreate(ApiSchema):
    analysis_selection: AnalysisSelection | None = None
    question_brief: QuestionBrief | None = None
    question: str = Field(min_length=3, max_length=5000)
    review_depth: Literal["focused", "deep"] = "focused"
    idempotency_key: str = Field(min_length=1, max_length=200)


class RunResponse(ApiSchema):
    analysis_selection: AnalysisSelection | None = None
    id: str
    project_id: str
    question: str
    review_depth: str
    status: str
    created_at: datetime
    updated_at: datetime
    version: int


class DocumentUpload(ApiSchema):
    run_id: str = Field(min_length=1, max_length=100)
    candidate_id: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=40_000_000)
    authorization_confirmed: bool


class DocumentResponse(ApiSchema):
    id: str
    filename: str
    content_type: str
    created_at: datetime


class EvidenceResponse(ApiSchema):
    id: str
    statement: str
    source_passage: str
    section: str | None
    page: int | None
    version: int
    created_at: datetime
    review_decision: str | None
    review_note: str | None


class EvidenceListResponse(ApiSchema):
    items: list[EvidenceResponse]
    total: int
    offset: int
    limit: int


class EvidenceReview(ApiSchema):
    decision: Literal["accepted", "rejected", "needs_revision"]
    note: str | None = Field(default=None, max_length=10_000)
    expected_version: int = Field(ge=1)


class ValidationResponse(ApiSchema):
    id: str
    check_name: str
    status: str
    created_at: datetime


class ValidationListResponse(ApiSchema):
    items: list[ValidationResponse]


class RiskOfBiasCreate(ApiSchema):
    study_id: str = Field(min_length=1, max_length=200)
    tool: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=200)
    judgment: RiskJudgment
    rationale: str | None = Field(default=None, max_length=10_000)
    source_evidence_ids: list[str] = Field(default_factory=list, max_length=200)


class RiskOfBiasRevision(RiskOfBiasCreate):
    expected_revision: int = Field(ge=1)


class RiskOfBiasResponse(ApiSchema):
    id: str
    revision_id: str
    study_id: str
    tool: str
    domain: str
    judgment: RiskJudgment
    rationale: str | None
    source_evidence_ids: list[str]
    reviewer_user_id: str
    created_at: datetime
    revision: int
    previous_revision_id: str | None


class RiskOfBiasListResponse(ApiSchema):
    items: list[RiskOfBiasResponse]


class AuditResponse(ApiSchema):
    id: str
    action: str
    entity_type: str
    occurred_at: datetime


class AuditListResponse(ApiSchema):
    items: list[AuditResponse]


class ExportResponse(ApiSchema):
    id: str
    filename: str
    content_type: str


class ExportListResponse(ApiSchema):
    items: list[ExportResponse]
