"""Project-scoped durable research-run routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from sci_search.api.dependencies import (
    AuthenticatedPrincipal,
    require_csrf,
    require_principal,
    research_service,
)
from sci_search.api.schemas import RunCreate, RunResponse
from sci_search.application.research_api import ResearchApiService, ResearchRunRecord

router = APIRouter(prefix="/api/v1/projects/{project_id}/runs", tags=["research runs"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
CsrfPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_csrf)]
ResearchService = Annotated[ResearchApiService, Depends(research_service)]


def _response(run: ResearchRunRecord) -> RunResponse:
    return RunResponse(
        id=run.id,
        project_id=run.project_id,
        question=run.question,
        review_depth=run.review_depth,
        status=run.status,
        created_at=run.created_at,
        updated_at=run.updated_at,
        version=run.version,
    )


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def start_run(
    project_id: str,
    body: RunCreate,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> RunResponse:
    return _response(
        service.start_run(
            principal.user_id,
            project_id,
            question=body.question,
            review_depth=body.review_depth,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/{run_id}", response_model=RunResponse)
def get_run(
    project_id: str,
    run_id: str,
    principal: Principal,
    service: ResearchService,
) -> RunResponse:
    return _response(service.get_run(principal.user_id, project_id, run_id))


@router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(
    project_id: str,
    run_id: str,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> RunResponse:
    return _response(service.cancel_run(principal.user_id, project_id, run_id))


@router.post("/{run_id}/retry", response_model=RunResponse)
def retry_run(
    project_id: str,
    run_id: str,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> RunResponse:
    return _response(service.retry_run(principal.user_id, project_id, run_id))
