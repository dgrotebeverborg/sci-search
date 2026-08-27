"""Explicit local FastAPI composition and server runner."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI

from sci_search.api.app import ApiSettings, create_app
from sci_search.api.dependencies import ApiServices
from sci_search.application.projects import (
    InMemoryProjectAuditRepository,
    InMemoryProjectRepository,
    Membership,
    Project,
    ProjectRole,
    ProjectService,
    Workspace,
)
from sci_search.application.research_api import InMemoryResearchApiService
from sci_search.application.sessions import InMemorySessionRepository, SessionService

_DEVELOPMENT_USER = "development-researcher"


def build_api_application(corpus: Path, *, unsafe_development: bool = False) -> FastAPI:
    """Build the loopback development API; production composition follows in Program 7."""

    environment = os.environ.get("SCI_SEARCH_ENVIRONMENT", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise ValueError("SCI_SEARCH_ENVIRONMENT must be development, test, or production")
    origins = tuple(
        value.strip()
        for value in os.environ.get("SCI_SEARCH_ALLOWED_ORIGINS", "http://127.0.0.1:8000").split(
            ","
        )
        if value.strip()
    )
    secret = os.environ.get("SCI_SEARCH_SESSION_SECRET", "").strip()
    if not secret and environment != "production":
        secret = secrets.token_urlsafe(48)
    callback = os.environ.get(
        "SCI_SEARCH_OIDC_CALLBACK_URL",
        "http://127.0.0.1:8000/auth/callback",
    )
    now = datetime.now(UTC)
    projects = InMemoryProjectRepository()
    workspace = Workspace(str(uuid4()), "Personal workspace", _DEVELOPMENT_USER, True, now)
    project = Project(
        str(uuid4()),
        workspace.id,
        corpus.name.replace("_", " ").title(),
        _DEVELOPMENT_USER,
        True,
        now,
    )
    projects.add_workspace(workspace)
    projects.add_membership(
        Membership(
            str(uuid4()),
            _DEVELOPMENT_USER,
            ProjectRole.OWNER,
            True,
            now,
            workspace_id=workspace.id,
        )
    )
    projects.add_project(project)
    projects.add_membership(
        Membership(
            str(uuid4()),
            _DEVELOPMENT_USER,
            ProjectRole.OWNER,
            True,
            now,
            project_id=project.id,
        )
    )

    def identifiers() -> str:
        return str(uuid4())

    project_service = ProjectService(
        projects,
        InMemoryProjectAuditRepository(),
        clock=lambda: datetime.now(UTC),
        id_source=identifiers,
    )
    research_service = InMemoryResearchApiService(
        projects,
        clock=lambda: datetime.now(UTC),
        id_source=identifiers,
    )
    sessions = SessionService(
        InMemorySessionRepository(),
        clock=lambda: datetime.now(UTC),
    )
    settings = ApiSettings(
        environment=environment,  # type: ignore[arg-type]
        allowed_origins=origins,
        oidc_callback_url=callback,
        session_secret=secret,
        development_auth_enabled=unsafe_development,
        development_user_id=_DEVELOPMENT_USER,
    )
    return create_app(
        settings,
        ApiServices(sessions=sessions, projects=project_service, research=research_service),
    )


def run_api_server(app: FastAPI, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, access_log=False)
