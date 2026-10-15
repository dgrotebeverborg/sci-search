"""Project-scoped durable research-run routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sci_search.api.dependencies import (
    AuthenticatedPrincipal,
    require_csrf,
    require_principal,
    research_service,
)
from sci_search.api.schemas import (
    QuestionBriefAdjust,
    QuestionInterpretationCreate,
    RunCreate,
    RunResponse,
)
from sci_search.application.research_api import ResearchApiService, ResearchRunRecord
from sci_search.question_planning import plan_from_brief

router = APIRouter(prefix="/api/v1/projects/{project_id}/runs", tags=["research runs"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
CsrfPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_csrf)]
ResearchService = Annotated[ResearchApiService, Depends(research_service)]


def _response(run: ResearchRunRecord, progress: dict | None = None) -> RunResponse:
    return RunResponse(
        id=run.id,
        project_id=run.project_id,
        question=run.question,
        review_depth=run.review_depth,
        status=run.status,
        created_at=run.created_at,
        updated_at=run.updated_at,
        version=run.version,
        analysis_selection=run.analysis_selection,
        progress=progress,
    )


@router.get("/models")
def analysis_models(project_id: str, principal: Principal, service: ResearchService) -> dict:
    return service.analysis_models(principal.user_id, project_id)


@router.post("/interpret")
def interpret_question(
    request: Request,
    project_id: str,
    body: QuestionInterpretationCreate,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> dict:
    if request.app.state.api_settings.workspace_preview:
        raise HTTPException(status_code=503, detail="Research is disabled in workspace preview.")
    return service.interpret_question(
        principal.user_id,
        project_id,
        body.question,
        analysis_selection=body.analysis_selection.model_dump()
        if body.analysis_selection
        else None,
        steer=body.steer.model_dump() if body.steer else None,
        clarification=body.clarification,
    )


@router.post("/interpret/adjust")
def adjust_question_brief(
    project_id: str,
    body: QuestionBriefAdjust,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> dict:
    """Apply one clicked or typed change to a brief; no model call."""
    try:
        return service.adjust_brief(principal.user_id, project_id, body.brief, body.change)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def start_run(
    request: Request,
    project_id: str,
    body: RunCreate,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> RunResponse:
    if request.app.state.api_settings.workspace_preview:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research execution is disabled in the temporary workspace preview. "
            "Use the configured database and worker service for live reviews.",
        )
    brief = asdict(body.question_brief) if body.question_brief else None
    try:
        plan_from_brief(body.question, brief)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(
        service.start_run(
            principal.user_id,
            project_id,
            question=body.question,
            analysis_selection=body.analysis_selection.model_dump()
            if body.analysis_selection
            else None,
            question_brief=brief,
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
    run = service.get_run(principal.user_id, project_id, run_id)
    get_progress = getattr(service, "get_run_progress", None)
    progress = (
        get_progress(principal.user_id, project_id, run_id) if callable(get_progress) else None
    )
    return _response(run, progress)


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
