"""Explicit local FastAPI composition and server runner."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import boto3
import uvicorn
from botocore.config import Config
from dramatiq.brokers.redis import RedisBroker
from fastapi import FastAPI

from sci_search.api.app import ApiSettings, create_app
from sci_search.api.dependencies import ApiServices
from sci_search.api.routes.authentication import create_authentication_router
from sci_search.api.routes.operations import production_operational_checks
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
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.observability import configure_json_logging
from sci_search.infrastructure.oidc import OidcConfiguration, OidcProvider
from sci_search.infrastructure.production_services import (
    DatabaseProjectService,
    DatabaseResearchApiService,
    DatabaseSessionService,
)
from sci_search.infrastructure.queue import RedisJobQueue
from sci_search.infrastructure.s3_blobs import S3BlobStore
from sci_search.infrastructure.settings import ProductionSettings

_DEVELOPMENT_USER = "development-researcher"


def build_api_application(
    corpus: Path, *, unsafe_development: bool = False, local_research_root: Path | None = None
) -> FastAPI:
    """Build either the explicit workspace preview or the configured production application."""

    environment = os.environ.get("SCI_SEARCH_ENVIRONMENT", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise ValueError("SCI_SEARCH_ENVIRONMENT must be development, test, or production")
    if environment == "production":
        if unsafe_development or local_research_root is not None:
            raise ValueError("development authentication is forbidden in production")
        return _build_production_application(ProductionSettings.from_environment())
    if not unsafe_development:
        raise ValueError(
            "Local workspace preview requires --unsafe-development; "
            "live research requires SCI_SEARCH_ENVIRONMENT=production with configured services."
        )
    origins = tuple(
        value.strip()
        for value in os.environ.get("SCI_SEARCH_ALLOWED_ORIGINS", "http://127.0.0.1:8000").split(
            ","
        )
        if value.strip()
    )
    secret = os.environ.get("SCI_SEARCH_SESSION_SECRET", "").strip()
    if not secret:
        secret = secrets.token_urlsafe(48)
    callback = os.environ.get(
        "SCI_SEARCH_OIDC_CALLBACK_URL",
        "http://127.0.0.1:8000/auth/callback",
    )
    now = datetime.now(UTC)
    if local_research_root is not None:
        from sci_search.infrastructure.local_workspace import LocalProjectRepository

        projects = LocalProjectRepository(local_research_root)
    else:
        projects = InMemoryProjectRepository()
    if projects.personal_workspace_for(_DEVELOPMENT_USER) is None:
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
    if local_research_root is not None:
        from sci_search.infrastructure.local_research import LocalResearchService

        research_service = LocalResearchService(
            projects,
            root=local_research_root,
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
        workspace_preview=local_research_root is None,
        local_research_enabled=local_research_root is not None,
    )

    app = create_app(
        settings,
        ApiServices(sessions=sessions, projects=project_service, research=research_service),
        shutdown=getattr(research_service, "close", None),
    )
    return app


def _build_production_application(settings: ProductionSettings) -> FastAPI:
    database = Database(settings.database_url)
    object_client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    blobs = S3BlobStore(object_client, settings.s3_bucket)
    broker = RedisBroker(url=settings.redis_url)
    queue = RedisJobQueue(broker)

    def clock() -> datetime:
        return datetime.now(UTC)

    sessions = DatabaseSessionService(database, clock=clock)
    projects = DatabaseProjectService(database, clock=clock)
    research = DatabaseResearchApiService(database, blobs, queue, clock=clock)
    api_settings = ApiSettings(
        environment="production",
        allowed_origins=settings.allowed_origins,
        oidc_callback_url=settings.oidc_callback_url,
        session_secret=settings.session_secret,
        development_auth_enabled=False,
    )
    provider = OidcProvider(
        OidcConfiguration(
            discovery_url=(settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"),
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            redirect_uri=settings.oidc_callback_url,
            post_logout_redirect_uri=settings.public_base_url,
            production=True,
        )
    )

    def dispose_resources() -> None:
        database.dispose()
        broker.close()

    app = create_app(
        api_settings,
        ApiServices(
            sessions=sessions,
            projects=projects,
            research=research,
        ),
        production_operational_checks(settings),
        create_authentication_router(provider, database, clock=clock),
        dispose_resources,
    )
    app.state.production_settings = settings
    app.state.database = database
    app.state.queue_broker = broker

    return app


def run_api_server(app: FastAPI, host: str, port: int) -> None:
    if app.state.api_settings.environment == "production":
        configure_json_logging()
    uvicorn.run(app, host=host, port=port, access_log=False)
