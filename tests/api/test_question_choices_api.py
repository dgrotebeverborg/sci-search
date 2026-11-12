"""The interpretation routes accept steering and a clarification, and adjust a brief."""

from pathlib import Path

from fastapi.testclient import TestClient

from sci_search.api.bootstrap import build_api_application
from tests.test_question_choices import BASE, DATA_OPTION, QUESTION


def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "development")
    app = build_api_application(
        Path("my_research"), unsafe_development=True, local_research_root=tmp_path
    )
    return TestClient(app)


def login(test_client):
    test_client.post("/auth/development")
    return {"X-CSRF-Token": test_client.get("/api/v1/session").json()["csrf_token"]}


def test_adjust_returns_a_changed_brief_or_a_readable_reason(monkeypatch, tmp_path):
    from sci_search.question_choices import option_briefs

    brief = option_briefs(QUESTION, BASE, [DATA_OPTION])[0]["brief"]
    with client(monkeypatch, tmp_path) as test_client:
        headers = login(test_client)
        project = test_client.get("/api/v1/projects").json()["items"][0]["id"]
        url = f"/api/v1/projects/{project}/runs/interpret/adjust"
        changed = test_client.post(
            url,
            headers=headers,
            json={"brief": brief, "change": {"detail": "route", "value": "both"}},
        )
        assert changed.status_code == 200
        assert changed.json()["data_research"]["route"] == "both"
        refused = test_client.post(
            url,
            headers=headers,
            json={"brief": BASE, "change": {"detail": "route", "value": "data"}},
        )
        assert refused.status_code == 422
        assert "Choose or type at least one measurement" in refused.json()["detail"]
        assert (
            test_client.post(
                url, json={"brief": brief, "change": {"detail": "route", "value": "both"}}
            ).status_code
            == 403
        )


def test_interpret_passes_steering_and_clarification(monkeypatch, tmp_path):
    from sci_search import question_interpretation

    calls = []

    def fake(question, analyzer=None, *, steer=None, clarification=None):
        calls.append((question, steer, clarification))
        return {**BASE, "options": [], "clarification_options": []}

    monkeypatch.setattr(question_interpretation, "interpret_question", fake)
    with client(monkeypatch, tmp_path) as test_client:
        headers = login(test_client)
        project = test_client.get("/api/v1/projects").json()["items"][0]["id"]
        response = test_client.post(
            f"/api/v1/projects/{project}/runs/interpret",
            headers=headers,
            json={
                "question": QUESTION,
                "steer": {"direction": "narrower", "option": {"title": "A"}},
                "clarification": "Indus",
            },
        )
    assert response.status_code == 200
    assert calls == [(QUESTION, {"direction": "narrower", "option": {"title": "A"}}, "Indus")]
