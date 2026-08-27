"""FastAPI dependencies for authentication and request authorization."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request, status

from sci_search.application.projects import Membership, Project, ProjectRole, Workspace
from sci_search.application.research_api import ResearchApiService
from sci_search.application.sessions import InvalidSession, IssuedSession, Session


class SessionServiceContract(Protocol):
    def create(self, user_id: str) -> IssuedSession: ...

    def authenticate(self, token: str) -> Session: ...

    def revoke(self, token: str) -> None: ...


class ProjectServiceContract(Protocol):
    def list_for_user(self, user_id: str) -> list[Project]: ...

    def list_workspaces_for_user(self, user_id: str) -> list[Workspace]: ...

    def get(self, user_id: str, project_id: str) -> Project: ...

    def role_for_user(self, user_id: str, project_id: str) -> ProjectRole: ...

    def create(self, user_id: str, workspace_id: str, name: str, is_private: bool) -> Project: ...

    def rename(self, user_id: str, project_id: str, name: str) -> Project: ...

    def delete(self, user_id: str, project_id: str) -> None: ...

    def list_members(self, user_id: str, project_id: str) -> list[Membership]: ...

    def add_member(
        self,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
    ) -> Membership: ...

    def change_member_role(
        self,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
    ) -> Membership: ...

    def remove_member(self, actor_user_id: str, project_id: str, subject_user_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ApiServices:
    """Explicit services available to thin API routes."""

    sessions: SessionServiceContract
    projects: ProjectServiceContract | None = None
    research: ResearchApiService | None = None


def research_service(request: Request) -> ResearchApiService:
    service: ResearchApiService | None = request.app.state.api_services.research
    if service is None:
        raise RuntimeError("research service is not configured")
    return service


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    session_id: str


def _session_token(request: Request) -> str:
    settings = request.app.state.api_settings
    token = request.cookies.get(settings.session_cookie_name, "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return token


def require_principal(request: Request) -> AuthenticatedPrincipal:
    """Authenticate an opaque browser session without exposing its token."""

    token = _session_token(request)
    services: ApiServices = request.app.state.api_services
    try:
        session = services.sessions.authenticate(token)
    except InvalidSession as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        ) from error
    return AuthenticatedPrincipal(user_id=session.user_id, session_id=session.id)


def csrf_token_for(request: Request) -> str:
    """Derive a session-bound CSRF value without persisting or exposing the session token."""

    settings = request.app.state.api_settings
    token = _session_token(request)
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def require_csrf(request: Request) -> AuthenticatedPrincipal:
    """Require authentication and a constant-time verified CSRF header."""

    principal = require_principal(request)
    settings = request.app.state.api_settings
    supplied = request.headers.get(settings.csrf_header_name, "")
    expected = csrf_token_for(request)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
    return principal
