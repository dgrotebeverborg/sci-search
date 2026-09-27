from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Browser, expect

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
from sci_search.application.sessions import InMemorySessionRepository, SessionService

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ORIGIN = "https://app.example.test"


@pytest.fixture
def browser_app() -> tuple[ApiSettings, SessionService, object]:
    projects = InMemoryProjectRepository()
    projects.add_workspace(Workspace("personal", "Personal workspace", "researcher", True, NOW))
    projects.add_membership(
        Membership(
            "personal-owner",
            "researcher",
            ProjectRole.OWNER,
            True,
            NOW,
            workspace_id="personal",
        )
    )
    projects.add_project(Project("first-project", "personal", "Iron-air", "researcher", True, NOW))
    projects.add_membership(
        Membership(
            "first-owner",
            "researcher",
            ProjectRole.OWNER,
            True,
            NOW,
            project_id="first-project",
        )
    )
    project_service = ProjectService(
        projects,
        InMemoryProjectAuditRepository(),
        clock=lambda: NOW,
        id_source=(f"generated-{index}" for index in range(20)).__next__,
    )
    sessions = SessionService(
        InMemorySessionRepository(),
        clock=lambda: NOW,
        token_source=lambda _: "browser-ui-session",
    )
    settings = ApiSettings(
        environment="test",
        allowed_origins=(ORIGIN,),
        oidc_callback_url=f"{ORIGIN}/auth/callback",
        session_secret="test-only-secret-that-is-at-least-32-characters",
    )
    app = create_app(settings, ApiServices(sessions=sessions, projects=project_service))
    return settings, sessions, app


def test_unauthenticated_browser_is_redirected_to_login(browser_app: tuple) -> None:
    _, _, app = browser_app
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)

    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_authenticated_researcher_gets_accessible_project_shell(browser_app: tuple) -> None:
    settings, sessions, app = browser_app
    issued = sessions.create("researcher")
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    client.cookies.set(settings.session_cookie_name, issued.token)

    root = client.get("/")
    response = client.get("/app")

    assert root.status_code == 303
    assert root.headers["location"] == "/app"
    assert response.status_code == 200
    assert 'lang="en"' in response.text
    assert '<main id="main-content"' in response.text
    assert 'aria-label="Project navigation"' in response.text
    assert '<label for="project-select">Project</label>' in response.text
    assert 'id="new-project-name"' in response.text
    assert 'id="research-question"' in response.text
    assert 'aria-live="polite"' in response.text
    assert "<style" not in response.text
    assert "<script>" not in response.text


def test_frontend_assets_are_separate_modules_with_uu_palette(browser_app: tuple) -> None:
    _, _, app = browser_app
    client = TestClient(app, base_url=ORIGIN)

    css = client.get("/static/app.css")
    api_module = client.get("/static/api.js")
    project_module = client.get("/static/projects.js")

    assert css.status_code == api_module.status_code == project_module.status_code == 200
    assert "--uu-yellow: #ffcd00" in css.text.casefold()
    assert "--uu-red: #c00a35" in css.text.casefold()
    assert "export" in api_module.text
    assert "createProject" in project_module.text


def test_workspace_and_project_bootstrap_contract(browser_app: tuple) -> None:
    settings, sessions, app = browser_app
    issued = sessions.create("researcher")
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set(settings.session_cookie_name, issued.token)

    workspaces = client.get("/api/v1/workspaces")
    projects = client.get("/api/v1/projects")

    assert workspaces.json()["items"] == [
        {"id": "personal", "name": "Personal workspace", "is_personal": True}
    ]
    assert projects.json()["items"][0]["name"] == "Iron-air"


def test_login_project_creation_switching_and_logout_in_chromium(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    page = chromium_browser.new_page()
    errors: list[str] = []
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.goto(live_browser_url)

    expect(page).to_have_url(f"{live_browser_url}/auth/login")
    page.get_by_role("button", name="Continue with development account").click()
    expect(page).to_have_url(f"{live_browser_url}/app")
    expect(page.get_by_role("heading", name="Personal workspace")).to_be_visible()
    expect(page.locator("#project-select")).to_have_value("development-project")

    page.get_by_text("New project", exact=True).click()
    page.get_by_label("Project name").fill("Goat foraging review")
    page.get_by_role("button", name="Create project").click()
    expect(page.locator("#project-select option")).to_have_count(2)
    expect(page.locator("#project-select")).to_have_value("browser-generated-0")
    page.locator("#project-select").select_option("development-project")
    expect(page.locator("#project-select")).to_have_value("development-project")

    page.get_by_role("button", name="Sign out").click()
    expect(page).to_have_url(f"{live_browser_url}/auth/login")
    assert errors == []
    page.close()


@pytest.mark.parametrize("live_browser_url", ["workspace-preview"], indirect=True)
def test_local_workspace_preview_keeps_research_disabled_after_project_creation(
    live_browser_url: str, chromium_browser: Browser
) -> None:
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        expect(page.locator("#workspace-preview-notice")).to_be_visible()
        expect(page.get_by_role("button", name="Review question")).to_be_disabled()
        page.get_by_text("New project", exact=True).click()
        page.get_by_label("Project name").fill("Preview project")
        page.get_by_role("button", name="Create project").click()
        expect(page.locator("#project-select option")).to_have_count(2)
        expect(page.get_by_role("button", name="Review question")).to_be_disabled()
        expect(page.locator("#research-question")).to_be_disabled()
        page.get_by_role("button", name="Sign out").click()
        expect(page).to_have_url(f"{live_browser_url}/auth/login")
    finally:
        page.close()
