"""Authorized saved dashboards and contextual article feedback."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from sci_search.api.routes.runs import CsrfPrincipal, Principal, ResearchService
from sci_search.result_summary import summarize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects/{project_id}/runs", tags=["dashboards"])


class ArticleFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["include", "background", "exclude", "reset"]
    reason: str = Field(default="", max_length=1000)
    expected_sequence: int = Field(ge=0)
    reviewed_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


@router.get("")
def list_runs(
    project_id: str,
    principal: Principal,
    service: ResearchService,
    query: str = Query(default="", max_length=5000),
    cursor: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    try:
        return service.list_runs(
            principal.user_id, project_id, query=query, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{run_id}/dashboard")
def dashboard(
    project_id: str,
    run_id: str,
    principal: Principal,
    service: ResearchService,
    revision: int | None = Query(default=None, ge=1),
) -> dict:
    snapshot = service.get_dashboard(principal.user_id, project_id, run_id, revision=revision)
    # Recomputed on every read, so saved runs get the current wording without a rebuild.
    try:
        snapshot["summary"] = summarize(snapshot)
    except Exception:  # a summary must never block opening a saved result
        logger.exception("Result summary failed for run %s", run_id)
        snapshot["summary"] = None
    return snapshot


@router.get("/{run_id}/revisions")
def revisions(project_id: str, run_id: str, principal: Principal, service: ResearchService) -> dict:
    return service.list_revisions(principal.user_id, project_id, run_id)


@router.post("/{run_id}/articles/{publication_id}/feedback", status_code=202)
def article_feedback(
    project_id: str,
    run_id: str,
    publication_id: str,
    body: ArticleFeedbackCreate,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> dict:
    try:
        return service.record_article_feedback(
            principal.user_id, project_id, run_id, publication_id, **body.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{run_id}/rebuild/retry", status_code=202)
def retry_rebuild(
    project_id: str, run_id: str, principal: CsrfPrincipal, service: ResearchService
) -> dict:
    try:
        return service.retry_rebuild(principal.user_id, project_id, run_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
