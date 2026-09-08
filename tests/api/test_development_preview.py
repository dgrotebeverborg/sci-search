from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sci_search.api.bootstrap import build_api_application


@pytest.fixture
def development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "development")
    monkeypatch.setenv("SCI_SEARCH_ALLOWED_ORIGINS", "http://127.0.0.1:8000")


def test_local_start_requires_explicit_workspace_preview(
    development_environment: None, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="--unsafe-development"):
        build_api_application(tmp_path)


def test_workspace_preview_supports_projects_but_rejects_unexecutable_research(
    development_environment: None, tmp_path: Path
) -> None:
    app = build_api_application(tmp_path, unsafe_development=True)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login = client.get("/auth/login")
        assert "Continue with development account" in login.text
        response = client.post("/auth/development")
        assert response.status_code == 200
        assert 'id="workspace-preview-notice"' in response.text
        assert "not saved after the server stops" in response.text
        assert "Research execution is disabled" in response.text
        session = client.get("/api/v1/session").json()
        headers = {"X-CSRF-Token": session["csrf_token"]}
        workspace = client.get("/api/v1/workspaces").json()["items"][0]
        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"workspace_id": workspace["id"], "name": "Preview project", "is_private": True},
        )
        assert project.status_code == 201
        response = client.post(
            f"/api/v1/projects/{project.json()['id']}/runs",
            headers=headers,
            json={
                "question": "What does the evidence say?",
                "review_depth": "focused",
                "idempotency_key": "preview-run",
            },
        )
        assert response.status_code == 503
        assert "workspace preview" in response.json()["detail"]
