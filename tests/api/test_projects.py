from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

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


class TokenSource:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self, byte_count: int) -> str:
        assert byte_count == 32
        self.index += 1
        return f"browser-token-{self.index}"


@pytest.fixture
def project_api() -> tuple[
    ApiSettings,
    SessionService,
    InMemoryProjectRepository,
    InMemoryProjectAuditRepository,
    object,
]:
    repository = InMemoryProjectRepository()
    repository.add_workspace(Workspace("shared", "Shared", "owner", False, NOW))
    repository.add_membership(
        Membership("workspace-owner", "owner", ProjectRole.OWNER, True, NOW, workspace_id="shared")
    )
    for role in ProjectRole:
        project = Project(f"project-{role.value}", "shared", role.value, "owner", False, NOW)
        repository.add_project(project)
        repository.add_membership(
            Membership(
                f"membership-{role.value}",
                role.value,
                role,
                True,
                NOW,
                project_id=project.id,
            )
        )
    repository.add_project(Project("owner-project", "shared", "Owner project", "owner", True, NOW))
    repository.add_membership(
        Membership(
            "owner-project-membership",
            "owner",
            ProjectRole.OWNER,
            True,
            NOW,
            project_id="owner-project",
        )
    )
    audits = InMemoryProjectAuditRepository()
    identifiers = iter(f"generated-{index}" for index in range(20))
    service = ProjectService(
        repository, audits, clock=lambda: NOW, id_source=lambda: next(identifiers)
    )
    sessions = SessionService(
        InMemorySessionRepository(),
        clock=lambda: NOW,
        token_source=TokenSource(),
    )
    settings = ApiSettings(
        environment="test",
        allowed_origins=(ORIGIN,),
        oidc_callback_url=f"{ORIGIN}/auth/callback",
        session_secret="test-only-secret-that-is-at-least-32-characters",
    )
    app = create_app(settings, ApiServices(sessions=sessions, projects=service))
    return settings, sessions, repository, audits, app


def _client_as(
    project_api: tuple[ApiSettings, SessionService, object, object, object],
    user_id: str,
) -> tuple[TestClient, str]:
    settings, sessions, _, _, app = project_api
    issued = sessions.create(user_id)
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set(settings.session_cookie_name, issued.token)
    csrf = client.get("/api/v1/session").json()["csrf_token"]
    return client, csrf


def test_list_returns_only_projects_visible_to_the_user(project_api: tuple) -> None:
    client, _ = _client_as(project_api, "viewer")

    response = client.get("/api/v1/projects")

    assert response.status_code == 200
    assert [project["id"] for project in response.json()["items"]] == ["project-viewer"]


def test_owner_can_create_read_update_and_delete_project(project_api: tuple) -> None:
    _, _, _, audits, _ = project_api
    client, csrf = _client_as(project_api, "owner")
    headers = {"X-CSRF-Token": csrf}

    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": "shared", "name": "New research", "is_private": True},
        headers=headers,
    )
    project_id = created.json()["id"]
    read = client.get(f"/api/v1/projects/{project_id}")
    updated = client.patch(
        f"/api/v1/projects/{project_id}", json={"name": "Renamed"}, headers=headers
    )
    deleted = client.delete(f"/api/v1/projects/{project_id}", headers=headers)
    hidden = client.get(f"/api/v1/projects/{project_id}")

    assert created.status_code == 201
    assert read.json()["name"] == "New research"
    assert updated.json()["name"] == "Renamed"
    assert deleted.status_code == 204
    assert hidden.status_code == 404
    assert {event.action for event in audits.events} >= {"project.created", "project.deleted"}


def test_unknown_create_fields_are_rejected(project_api: tuple) -> None:
    client, csrf = _client_as(project_api, "owner")

    response = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": "shared",
            "name": "New research",
            "is_private": True,
            "owner_user_id": "attacker",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("role", [ProjectRole.EDITOR, ProjectRole.REVIEWER, ProjectRole.VIEWER])
def test_only_owner_can_change_memberships(project_api: tuple, role: ProjectRole) -> None:
    client, csrf = _client_as(project_api, role.value)

    response = client.post(
        f"/api/v1/projects/project-{role.value}/members",
        json={"user_id": "new-user", "role": "viewer"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "resource not found"}


@pytest.mark.parametrize("role", [ProjectRole.EDITOR, ProjectRole.REVIEWER, ProjectRole.VIEWER])
def test_only_owner_can_update_or_delete_project(project_api: tuple, role: ProjectRole) -> None:
    client, csrf = _client_as(project_api, role.value)
    headers = {"X-CSRF-Token": csrf}

    updated = client.patch(
        f"/api/v1/projects/project-{role.value}", json={"name": "Not allowed"}, headers=headers
    )
    deleted = client.delete(f"/api/v1/projects/project-{role.value}", headers=headers)

    assert updated.status_code == deleted.status_code == 404
    assert updated.content == deleted.content


def test_owner_membership_operations_are_audited(project_api: tuple) -> None:
    _, _, _, audits, _ = project_api
    client, csrf = _client_as(project_api, "owner")
    headers = {"X-CSRF-Token": csrf}

    added = client.post(
        "/api/v1/projects/owner-project/members",
        json={"user_id": "colleague", "role": "viewer"},
        headers=headers,
    )
    changed = client.patch(
        "/api/v1/projects/owner-project/members/colleague",
        json={"role": "reviewer"},
        headers=headers,
    )
    listed = client.get("/api/v1/projects/owner-project/members")
    removed = client.delete("/api/v1/projects/owner-project/members/colleague", headers=headers)

    assert added.status_code == 201
    assert changed.json()["role"] == "reviewer"
    assert [member["user_id"] for member in listed.json()["items"]] == ["owner", "colleague"]
    assert removed.status_code == 204
    assert {event.action for event in audits.events} >= {
        "project_membership.added",
        "project_membership.role_changed",
        "project_membership.removed",
    }


def test_guessed_and_unauthorized_project_ids_are_indistinguishable(project_api: tuple) -> None:
    client, _ = _client_as(project_api, "unrelated")

    existing = client.get("/api/v1/projects/owner-project")
    missing = client.get("/api/v1/projects/not-a-project")

    assert existing.status_code == missing.status_code == 404
    assert existing.content == missing.content
