"""Authorized full-text upload and original-document streaming routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from sci_search.api.dependencies import (
    AuthenticatedPrincipal,
    require_csrf,
    require_principal,
    research_service,
)
from sci_search.api.schemas import DocumentResponse, DocumentUpload
from sci_search.application.research_api import ResearchApiService

router = APIRouter(prefix="/api/v1/projects/{project_id}/documents", tags=["documents"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
CsrfPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_csrf)]
ResearchService = Annotated[ResearchApiService, Depends(research_service)]


def _disposition(filename: str) -> str:
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return f'attachment; filename="{safe}"'


@router.get("/{document_id}/content")
def download_document(
    project_id: str,
    document_id: str,
    principal: Principal,
    service: ResearchService,
) -> StreamingResponse:
    download = service.open_document(principal.user_id, project_id, document_id)
    return StreamingResponse(
        download.iter_chunks(),
        media_type=download.content_type,
        headers={"Content-Disposition": _disposition(download.filename)},
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    project_id: str,
    body: DocumentUpload,
    principal: CsrfPrincipal,
    service: ResearchService,
) -> DocumentResponse:
    document = service.upload_document(
        principal.user_id,
        project_id,
        run_id=body.run_id,
        candidate_id=body.candidate_id,
        filename=body.filename,
        content_base64=body.content_base64,
        authorization_confirmed=body.authorization_confirmed,
    )
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        created_at=document.created_at,
    )
