"""Evidence, optimistic review, and validation routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

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
    ValidationListResponse,
    ValidationResponse,
)
from sci_search.application.research_api import EvidenceRecord, ResearchApiService

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
