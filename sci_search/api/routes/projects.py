"""Project and project-membership HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from sci_search.api.dependencies import AuthenticatedPrincipal, require_csrf, require_principal
from sci_search.api.schemas import (
    MembershipCreate,
    MembershipListResponse,
    MembershipResponse,
    MembershipUpdate,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from sci_search.application.projects import Membership, Project, ProjectRole, ProjectService

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_principal)]
CsrfPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_csrf)]


def _service(request: Request) -> ProjectService:
    service = request.app.state.api_services.projects
    if service is None:
        raise RuntimeError("project service is not configured")
    return service


ProjectServiceDependency = Annotated[ProjectService, Depends(_service)]


def _project_response(project: Project, role: ProjectRole) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        owner_user_id=project.owner_user_id,
        is_private=project.is_private,
        created_at=project.created_at,
        role=role,
    )


def _membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        user_id=membership.user_id,
        role=membership.role,
        active=membership.active,
        created_at=membership.created_at,
    )


@router.get("", response_model=ProjectListResponse)
def list_projects(principal: Principal, service: ProjectServiceDependency) -> ProjectListResponse:
    return ProjectListResponse(
        items=[
            _project_response(item, service.role_for_user(principal.user_id, item.id))
            for item in service.list_for_user(principal.user_id)
        ]
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    principal: CsrfPrincipal,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return _project_response(
        service.create(principal.user_id, body.workspace_id, body.name, body.is_private),
        ProjectRole.OWNER,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def read_project(
    project_id: str,
    principal: Principal,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return _project_response(
        service.get(principal.user_id, project_id),
        service.role_for_user(principal.user_id, project_id),
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    principal: CsrfPrincipal,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return _project_response(
        service.rename(principal.user_id, project_id, body.name),
        ProjectRole.OWNER,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    principal: CsrfPrincipal,
    service: ProjectServiceDependency,
) -> Response:
    service.delete(principal.user_id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/members", response_model=MembershipListResponse)
def list_members(
    project_id: str,
    principal: Principal,
    service: ProjectServiceDependency,
) -> MembershipListResponse:
    return MembershipListResponse(
        items=[
            _membership_response(item)
            for item in service.list_members(principal.user_id, project_id)
        ]
    )


@router.post(
    "/{project_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    project_id: str,
    body: MembershipCreate,
    principal: CsrfPrincipal,
    service: ProjectServiceDependency,
) -> MembershipResponse:
    return _membership_response(
        service.add_member(principal.user_id, project_id, body.user_id, body.role)
    )


@router.patch("/{project_id}/members/{user_id}", response_model=MembershipResponse)
def change_member_role(
    project_id: str,
    user_id: str,
    body: MembershipUpdate,
    principal: CsrfPrincipal,
    service: ProjectServiceDependency,
) -> MembershipResponse:
    return _membership_response(
        service.change_member_role(principal.user_id, project_id, user_id, body.role)
    )


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    project_id: str,
    user_id: str,
    principal: CsrfPrincipal,
    service: ProjectServiceDependency,
) -> Response:
    service.remove_member(principal.user_id, project_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
