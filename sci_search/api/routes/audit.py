"""Owner-only project audit routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from sci_search.api.dependencies import (
    AuthenticatedPrincipal,
    require_principal,
    research_service,
)
from sci_search.api.schemas import AuditListResponse, AuditResponse
from sci_search.application.research_api import ResearchApiService

router = APIRouter(prefix="/api/v1/projects/{project_id}/audit", tags=["audit"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
ResearchService = Annotated[ResearchApiService, Depends(research_service)]


@router.get("", response_model=AuditListResponse)
def list_audit(
    project_id: str,
    principal: Principal,
    service: ResearchService,
) -> AuditListResponse:
    return AuditListResponse(
        items=[
            AuditResponse(
                id=record.id,
                action=record.action,
                entity_type=record.entity_type,
                occurred_at=record.occurred_at,
            )
            for record in service.list_audit(principal.user_id, project_id)
        ]
    )
