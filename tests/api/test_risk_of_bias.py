from __future__ import annotations

import pytest

from sci_search.application.projects import ProjectRole
from tests.api.test_research_routes import _client_as
from tests.api.test_research_routes import research_api as _research_api_fixture


@pytest.fixture
def risk_api() -> tuple:
    return _research_api_fixture.__wrapped__()


def _judgment() -> dict[str, object]:
    return {
        "study_id": "publication-1",
        "tool": "ROBINS-I",
        "domain": "confounding",
        "judgment": "some_concerns",
        "rationale": "The study did not adjust for seasonal vegetation availability.",
        "source_evidence_ids": ["evidence-1"],
    }


def test_reviewer_creates_and_viewer_reads_grounded_judgment(risk_api: tuple) -> None:
    reviewer, headers = _client_as(risk_api, "reviewer")
    created = reviewer.post(
        "/api/v1/projects/project-reviewer/risk-of-bias", json=_judgment(), headers=headers
    )
    assert created.status_code == 201
    assert created.json()["reviewer_user_id"] == "reviewer"
    assert created.json()["revision"] == 1

    # Seed the same scoped record through the service for a viewer-readable project.
    _, _, service, _ = risk_api
    service.seed_risk_of_bias(
        "project-viewer",
        created.json()["id"],
        study_id="publication-1",
        tool="ROBINS-I",
        domain="confounding",
        judgment="unknown",
        reviewer_user_id="reviewer",
    )
    viewer, _ = _client_as(risk_api, "viewer")
    listed = viewer.get("/api/v1/projects/project-viewer/risk-of-bias")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["judgment"] == "unknown"


@pytest.mark.parametrize("role", [ProjectRole.EDITOR, ProjectRole.VIEWER])
def test_non_review_roles_cannot_create_judgment(risk_api: tuple, role: ProjectRole) -> None:
    client, headers = _client_as(risk_api, role.value)
    response = client.post(
        f"/api/v1/projects/project-{role.value}/risk-of-bias",
        json=_judgment(),
        headers=headers,
    )
    assert response.status_code == 404


def test_revision_is_optimistic_and_conflict_is_audited(risk_api: tuple) -> None:
    client, headers = _client_as(risk_api, "owner")
    created = client.post(
        "/api/v1/projects/project-owner/risk-of-bias", json=_judgment(), headers=headers
    ).json()
    path = f"/api/v1/projects/project-owner/risk-of-bias/{created['id']}"
    revision = {
        **_judgment(),
        "judgment": "high",
        "rationale": "The unadjusted seasonal confounding directly affects the outcome.",
        "expected_revision": 1,
    }
    accepted = client.patch(path, json=revision, headers=headers)
    conflict = client.patch(path, json=revision, headers=headers)

    assert accepted.status_code == 200
    assert accepted.json()["revision"] == 2
    assert accepted.json()["previous_revision_id"] == created["revision_id"]
    assert conflict.status_code == 409

    audit = client.get("/api/v1/projects/project-owner/audit").json()["items"]
    actions = {item["action"] for item in audit}
    assert "risk_of_bias.created" in actions
    assert "risk_of_bias.revision_conflict" in actions


def test_invalid_or_cross_project_source_reference_is_rejected(risk_api: tuple) -> None:
    client, headers = _client_as(risk_api, "reviewer")
    body = {**_judgment(), "source_evidence_ids": ["missing-evidence"]}
    response = client.post(
        "/api/v1/projects/project-reviewer/risk-of-bias", json=body, headers=headers
    )
    assert response.status_code == 422
