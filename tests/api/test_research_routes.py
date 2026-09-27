from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from sci_search.api.app import ApiSettings, create_app
from sci_search.api.dependencies import ApiServices
from sci_search.application.projects import (
    InMemoryProjectRepository,
    Membership,
    Project,
    ProjectRole,
    Workspace,
)
from sci_search.application.research_api import InMemoryResearchApiService
from sci_search.application.sessions import InMemorySessionRepository, SessionService

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ORIGIN = "https://app.example.test"


class TokenSource:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self, byte_count: int) -> str:
        assert byte_count == 32
        self.index += 1
        return f"research-session-{self.index}"


@pytest.fixture
def research_api() -> tuple[ApiSettings, SessionService, InMemoryResearchApiService, object]:
    projects = InMemoryProjectRepository()
    projects.add_workspace(Workspace("workspace", "Research", "owner", False, NOW))
    for role in ProjectRole:
        project_id = f"project-{role.value}"
        projects.add_project(Project(project_id, "workspace", role.value, "owner", False, NOW))
        projects.add_membership(
            Membership(
                f"member-{role.value}",
                role.value,
                role,
                True,
                NOW,
                project_id=project_id,
            )
        )
    research = InMemoryResearchApiService(
        projects,
        clock=lambda: NOW,
        id_source=(f"generated-{index}" for index in range(100)).__next__,
    )
    for role in ProjectRole:
        project_id = f"project-{role.value}"
        research.seed_run(project_id, "run-visible", "Existing question", status="queued")
        research.seed_run(project_id, "run-failed", "Failed question", status="failed")
        research.seed_document(
            project_id,
            "document-1",
            filename="source-paper.pdf",
            content_type="application/pdf",
            content=b"%PDF-original-source-bytes",
        )
        research.seed_evidence(
            project_id,
            "evidence-1",
            statement="Reported result",
            source_passage="Exact source passage.",
        )
        research.seed_validation(project_id, "validation-1", "provenance", "passed")
        research.seed_export(
            project_id,
            "export-1",
            filename="research-package.zip",
            content_type="application/zip",
            chunks=(b"first-", b"second"),
        )
        research.seed_audit(project_id, "project.created", "project")
    sessions = SessionService(
        InMemorySessionRepository(), clock=lambda: NOW, token_source=TokenSource()
    )
    settings = ApiSettings(
        environment="test",
        allowed_origins=(ORIGIN,),
        oidc_callback_url=f"{ORIGIN}/auth/callback",
        session_secret="test-only-secret-that-is-at-least-32-characters",
        max_request_body_bytes=2_000_000,
    )
    app = create_app(settings, ApiServices(sessions=sessions, research=research))
    return settings, sessions, research, app


def _client_as(research_api: tuple, user_id: str) -> tuple[TestClient, dict[str, str]]:
    settings, sessions, _, app = research_api
    issued = sessions.create(user_id)
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set(settings.session_cookie_name, issued.token)
    csrf = client.get("/api/v1/session").json()["csrf_token"]
    return client, {settings.csrf_header_name: csrf}


@pytest.mark.parametrize("role", list(ProjectRole))
def test_start_run_obeys_role_matrix(research_api: tuple, role: ProjectRole) -> None:
    client, headers = _client_as(research_api, role.value)

    response = client.post(
        f"/api/v1/projects/project-{role.value}/runs",
        json={
            "question": "What does the evidence show?",
            "review_depth": "focused",
            "idempotency_key": f"start-{role.value}",
        },
        headers=headers,
    )

    if role in {ProjectRole.OWNER, ProjectRole.EDITOR}:
        assert response.status_code == 201
        assert response.json()["status"] == "queued"
    else:
        assert response.status_code == 404


@pytest.mark.parametrize("role", list(ProjectRole))
def test_read_run_and_document_obey_project_scope(research_api: tuple, role: ProjectRole) -> None:
    client, _ = _client_as(research_api, role.value)
    project_id = f"project-{role.value}"

    run = client.get(f"/api/v1/projects/{project_id}/runs/run-visible")
    document = client.get(f"/api/v1/projects/{project_id}/documents/document-1/content")

    assert run.status_code == 200
    assert run.json()["question"] == "Existing question"
    assert document.status_code == 200
    assert document.content == b"%PDF-original-source-bytes"
    assert 'filename="source-paper.pdf"' in document.headers["content-disposition"]


def test_unrelated_user_cannot_enumerate_any_research_resource(research_api: tuple) -> None:
    client, _ = _client_as(research_api, "unrelated")
    paths = [
        "/api/v1/projects/project-owner/runs/run-visible",
        "/api/v1/projects/project-owner/documents/document-1/content",
        "/api/v1/projects/project-owner/evidence",
        "/api/v1/projects/project-owner/validation",
        "/api/v1/projects/project-owner/exports/export-1",
        "/api/v1/projects/project-owner/audit",
    ]

    responses = [client.get(path) for path in paths]

    assert {response.status_code for response in responses} == {404}
    assert {response.content for response in responses} == {b'{"detail":"resource not found"}'}


def test_unrelated_user_cannot_mutate_upload_review_or_control_jobs(
    research_api: tuple,
) -> None:
    client, headers = _client_as(research_api, "unrelated")
    requests = [
        client.post(
            "/api/v1/projects/project-owner/runs",
            json={
                "question": "Attempted cross-project write",
                "review_depth": "focused",
                "idempotency_key": "cross-project-job",
            },
            headers=headers,
        ),
        client.post(
            "/api/v1/projects/project-owner/documents/upload",
            json={
                "run_id": "run-visible",
                "candidate_id": "candidate-1",
                "filename": "paper.pdf",
                "content_base64": base64.b64encode(_parseable_pdf()).decode("ascii"),
                "authorization_confirmed": True,
            },
            headers=headers,
        ),
        client.patch(
            "/api/v1/projects/project-owner/evidence/evidence-1/review",
            json={"decision": "accepted", "expected_version": 1},
            headers=headers,
        ),
        client.post("/api/v1/projects/project-owner/runs/run-visible/cancel", headers=headers),
        client.post("/api/v1/projects/project-owner/runs/run-failed/retry", headers=headers),
    ]
    assert {response.status_code for response in requests} == {404}
    assert {response.content for response in requests} == {b'{"detail":"resource not found"}'}


def test_editor_can_cancel_and_retry_runs(research_api: tuple) -> None:
    client, headers = _client_as(research_api, "editor")

    cancelled = client.post(
        "/api/v1/projects/project-editor/runs/run-visible/cancel", headers=headers
    )
    retried = client.post("/api/v1/projects/project-editor/runs/run-failed/retry", headers=headers)

    assert cancelled.json()["status"] == "cancel_requested"
    assert retried.json()["status"] == "queued"


def test_evidence_is_paginated_stably_and_review_is_version_checked(research_api: tuple) -> None:
    _, _, research, _ = research_api
    research.seed_evidence(
        "project-reviewer", "evidence-2", statement="Second", source_passage="Second passage"
    )
    client, headers = _client_as(research_api, "reviewer")

    page = client.get("/api/v1/projects/project-reviewer/evidence?offset=1&limit=1")
    accepted = client.patch(
        "/api/v1/projects/project-reviewer/evidence/evidence-1/review",
        json={"decision": "accepted", "note": "Checked source", "expected_version": 1},
        headers=headers,
    )
    conflict = client.patch(
        "/api/v1/projects/project-reviewer/evidence/evidence-1/review",
        json={"decision": "rejected", "expected_version": 1},
        headers=headers,
    )

    assert page.json()["items"][0]["id"] == "evidence-2"
    assert page.json()["total"] == 2
    assert accepted.status_code == 200
    assert accepted.json()["version"] == 2
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "resource version conflict"}


@pytest.mark.parametrize("role", [ProjectRole.EDITOR, ProjectRole.VIEWER])
def test_non_review_roles_cannot_mutate_evidence(research_api: tuple, role: ProjectRole) -> None:
    client, headers = _client_as(research_api, role.value)

    response = client.patch(
        f"/api/v1/projects/project-{role.value}/evidence/evidence-1/review",
        json={"decision": "accepted", "expected_version": 1},
        headers=headers,
    )

    assert response.status_code == 404


def test_validation_export_and_owner_only_audit(research_api: tuple) -> None:
    owner, _ = _client_as(research_api, "owner")
    viewer, _ = _client_as(research_api, "viewer")

    validation = viewer.get("/api/v1/projects/project-viewer/validation")
    exported = viewer.get("/api/v1/projects/project-viewer/exports/export-1")
    owner_audit = owner.get("/api/v1/projects/project-owner/audit")
    hidden_audit = viewer.get("/api/v1/projects/project-viewer/audit")

    assert validation.json()["items"][0]["check_name"] == "provenance"
    assert exported.content == b"first-second"
    assert exported.headers["content-type"] == "application/zip"
    assert owner_audit.json()["items"][0]["action"] == "project.created"
    assert hidden_audit.status_code == 404


def _parseable_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "content", "confirmed"),
    [
        ("../paper.pdf", _parseable_pdf(), True),
        ("paper.pdf", b"not a pdf", True),
        ("paper.pdf", _parseable_pdf(), False),
    ],
)
def test_authorized_upload_rejects_unsafe_or_invalid_inputs(
    research_api: tuple,
    filename: str,
    content: bytes,
    confirmed: bool,
) -> None:
    client, headers = _client_as(research_api, "editor")

    response = client.post(
        "/api/v1/projects/project-editor/documents/upload",
        json={
            "run_id": "run-visible",
            "candidate_id": "candidate-1",
            "filename": filename,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "authorization_confirmed": confirmed,
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_editor_can_upload_parseable_authorized_pdf(research_api: tuple) -> None:
    client, headers = _client_as(research_api, "editor")

    response = client.post(
        "/api/v1/projects/project-editor/documents/upload",
        json={
            "run_id": "run-visible",
            "candidate_id": "candidate-1",
            "filename": "paper.pdf",
            "content_base64": base64.b64encode(_parseable_pdf()).decode("ascii"),
            "authorization_confirmed": True,
        },
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "paper.pdf"
    assert response.json()["content_type"] == "application/pdf"


@pytest.mark.parametrize("role", list(ProjectRole))
def test_interpretation_requires_run_permission_without_creating_run(
    research_api, role, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "sci_search.question_interpretation.interpret_question",
        lambda question: calls.append(question) or {"interpreted_question": question},
    )
    client, headers = _client_as(research_api, role.value)
    base = f"/api/v1/projects/project-{role.value}/runs"
    before = client.get(base).json()
    response = client.post(
        base + "/interpret", headers=headers, json={"question": "Energy prices?"}
    )
    allowed = role in {ProjectRole.OWNER, ProjectRole.EDITOR}
    assert response.status_code == (200 if allowed else 404)
    assert calls == (["Energy prices?"] if allowed else [])
    assert client.get(base).json() == before
    assert client.post(base + "/interpret", json={"question": "Energy prices?"}).status_code == 403
