"""Authenticated workspace discovery routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from sci_search.api.dependencies import AuthenticatedPrincipal, require_principal
from sci_search.api.schemas import WorkspaceListResponse, WorkspaceResponse
from sci_search.application.projects import ProjectService

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]


def _service(request: Request) -> ProjectService:
    service = request.app.state.api_services.projects
    if service is None:
        raise RuntimeError("project service is not configured")
    return service


ProjectServiceDependency = Annotated[ProjectService, Depends(_service)]


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    principal: Principal,
    service: ProjectServiceDependency,
) -> WorkspaceListResponse:
    return WorkspaceListResponse(
        items=[
            WorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
                is_personal=workspace.is_personal,
            )
            for workspace in service.list_workspaces_for_user(principal.user_id)
        ]
    )
