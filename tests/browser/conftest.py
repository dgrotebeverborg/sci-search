from __future__ import annotations

import socket
import threading
import time
from datetime import UTC, datetime

import pytest
import uvicorn
from playwright.sync_api import Browser, Playwright, sync_playwright

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

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
DEVELOPMENT_USER = "development-researcher"


@pytest.fixture(scope="session")
def live_browser_url() -> str:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"

    projects = InMemoryProjectRepository()
    projects.add_workspace(
        Workspace("development-personal", "Personal workspace", DEVELOPMENT_USER, True, NOW)
    )
    projects.add_membership(
        Membership(
            "development-workspace-owner",
            DEVELOPMENT_USER,
            ProjectRole.OWNER,
            True,
            NOW,
            workspace_id="development-personal",
        )
    )
    projects.add_project(
        Project(
            "development-project",
            "development-personal",
            "Iron-air pilot",
            DEVELOPMENT_USER,
            True,
            NOW,
        )
    )
    projects.add_membership(
        Membership(
            "development-project-owner",
            DEVELOPMENT_USER,
            ProjectRole.OWNER,
            True,
            NOW,
            project_id="development-project",
        )
    )
    identifiers = (f"browser-generated-{index}" for index in range(200))
    project_service = ProjectService(
        projects,
        InMemoryProjectAuditRepository(),
        clock=lambda: NOW,
        id_source=identifiers.__next__,
    )
    research_service = InMemoryResearchApiService(
        projects,
        clock=lambda: NOW,
        id_source=identifiers.__next__,
    )
    sessions = SessionService(InMemorySessionRepository(), clock=lambda: NOW)
    app = create_app(
        ApiSettings(
            environment="development",
            allowed_origins=(origin,),
            oidc_callback_url=f"{origin}/auth/callback",
            session_secret="browser-test-secret-that-is-at-least-32-characters",
            development_auth_enabled=True,
            development_user_id=DEVELOPMENT_USER,
        ),
        ApiServices(sessions=sessions, projects=project_service, research=research_service),
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("browser test server did not start")
    try:
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


@pytest.fixture(scope="session")
def playwright_runtime() -> Playwright:
    runtime = sync_playwright().start()
    try:
        yield runtime
    finally:
        runtime.stop()


@pytest.fixture(scope="session")
def chromium_browser(playwright_runtime: Playwright) -> Browser:
    browser = playwright_runtime.chromium.launch(headless=True)
    try:
        yield browser
    finally:
        browser.close()
