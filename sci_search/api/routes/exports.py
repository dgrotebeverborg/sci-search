"""Streaming project export routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from sci_search.api.dependencies import (
    AuthenticatedPrincipal,
    require_principal,
    research_service,
)
from sci_search.api.routes.documents import _disposition
from sci_search.api.schemas import ExportListResponse, ExportResponse
from sci_search.application.research_api import ResearchApiService

router = APIRouter(prefix="/api/v1/projects/{project_id}/exports", tags=["exports"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
ResearchService = Annotated[ResearchApiService, Depends(research_service)]


@router.get("", response_model=ExportListResponse)
def list_exports(
    project_id: str,
    principal: Principal,
    service: ResearchService,
) -> ExportListResponse:
    return ExportListResponse(
        items=[
            ExportResponse(id=item.id, filename=item.filename, content_type=item.content_type)
            for item in service.list_exports(principal.user_id, project_id)
        ]
    )


@router.get("/{export_id}")
def download_export(
    project_id: str,
    export_id: str,
    principal: Principal,
    service: ResearchService,
) -> StreamingResponse:
    download = service.open_export(principal.user_id, project_id, export_id)
    return StreamingResponse(
        download.iter_chunks(),
        media_type=download.content_type,
        headers={"Content-Disposition": _disposition(download.filename)},
    )
