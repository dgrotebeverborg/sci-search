"""Evidence, optimistic review, and validation routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from sci_search.api.dependencies import (
    AuthenticatedPrincipal,
    require_csrf,
    require_principal,
    research_service,
)
from sci_search.api.schemas import (
    EvidenceListResponse,
    EvidenceResponse,
    EvidenceReview,
    RiskOfBiasCreate,
    RiskOfBiasListResponse,
    RiskOfBiasResponse,
    RiskOfBiasRevision,
    ValidationListResponse,
    ValidationResponse,
)
from sci_search.application.research_api import EvidenceRecord, ResearchApiService
from sci_search.domain.risk_of_bias import RiskOfBiasRecord

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["evidence review"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
CsrfPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_csrf)]
ResearchService = Annotated[ResearchApiService, Depends(research_service)]


def _evidence(record: EvidenceRecord) -> EvidenceResponse:
    return EvidenceResponse(
        id=record.id,
        statement=record.statement,
        source_passage=record.source_passage,
        section=record.section,
        page=record.page,
        version=record.version,
        created_at=record.created_at,
        review_decision=record.review_decision,
        review_note=record.review_note,
    )


def _risk_of_bias(record: RiskOfBiasRecord) -> RiskOfBiasResponse:
    return RiskOfBiasResponse(
        id=record.id,
        revision_id=record.revision_id,
        study_id=record.study_id,
        tool=record.tool,
        domain=record.domain,
        judgment=record.judgment,
        rationale=record.rationale,
        source_evidence_ids=list(record.source_evidence_ids),
        reviewer_user_id=record.reviewer_user_id,
        created_at=record.created_at,
        revision=record.revision,
        previous_revision_id=record.previous_revision_id,
    )


@router.get("/evidence", response_model=EvidenceListResponse)
def list_evidence(
    project_id: str,
    principal: Principal,
    service: ResearchService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> EvidenceListResponse:
    records, total = service.list_evidence(
        principal.user_id, project_id, offset=offset, limit=limit
    )
    return EvidenceListResponse(
        items=[_evidence(record) for record in records],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/evidence/{evidence_id}/review", response_model=EvidenceResponse)
def review_evidence(
    project_id: str,
    evidence_id: str,
    body: EvidenceReview,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> EvidenceResponse:
    return _evidence(
        service.review_evidence(
            principal.user_id,
            project_id,
            evidence_id,
            expected_version=body.expected_version,
            decision=body.decision,
            note=body.note,
        )
    )


@router.get("/validation", response_model=ValidationListResponse)
def list_validation(
    project_id: str,
    principal: Principal,
    service: ResearchService,
) -> ValidationListResponse:
    return ValidationListResponse(
        items=[
            ValidationResponse(
                id=record.id,
                check_name=record.check_name,
                status=record.status,
                created_at=record.created_at,
            )
            for record in service.list_validation(principal.user_id, project_id)
        ]
    )


@router.get("/risk-of-bias", response_model=RiskOfBiasListResponse)
def list_risk_of_bias(
    project_id: str,
    principal: Principal,
    service: ResearchService,
    study_id: Annotated[str | None, Query(max_length=200)] = None,
) -> RiskOfBiasListResponse:
    return RiskOfBiasListResponse(
        items=[
            _risk_of_bias(record)
            for record in service.list_risk_of_bias(
                principal.user_id, project_id, study_id=study_id
            )
        ]
    )


@router.post(
    "/risk-of-bias",
    response_model=RiskOfBiasResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_risk_of_bias(
    project_id: str,
    body: RiskOfBiasCreate,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> RiskOfBiasResponse:
    return _risk_of_bias(
        service.create_risk_of_bias(
            principal.user_id,
            project_id,
            study_id=body.study_id,
            tool=body.tool,
            domain=body.domain,
            judgment=body.judgment,
            rationale=body.rationale,
            source_evidence_ids=tuple(dict.fromkeys(body.source_evidence_ids)),
        )
    )


@router.patch("/risk-of-bias/{record_id}", response_model=RiskOfBiasResponse)
def revise_risk_of_bias(
    project_id: str,
    record_id: str,
    body: RiskOfBiasRevision,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> RiskOfBiasResponse:
    return _risk_of_bias(
        service.revise_risk_of_bias(
            principal.user_id,
            project_id,
            record_id,
            expected_revision=body.expected_revision,
            study_id=body.study_id,
            tool=body.tool,
            domain=body.domain,
            judgment=body.judgment,
            rationale=body.rationale,
            source_evidence_ids=tuple(dict.fromkeys(body.source_evidence_ids)),
        )
    )
