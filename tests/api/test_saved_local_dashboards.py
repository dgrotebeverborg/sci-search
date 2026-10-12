"""The local web workspace must survive process recreation without rerunning research."""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from sci_search.api.bootstrap import build_api_application
from sci_search.research_runs import DownloadPayload


class RetainedManager:
    """Deterministic research boundary; storage, APIs and revision publication remain real."""

    calls = []

    def __init__(self, root):
        self.root = Path(root)

    def run_sync(self, question, *, limits, question_brief=None):
        self.calls.append(question)
        state = {
            "run_id": "retained",
            "question": question,
            "question_brief": question_brief,
            "status": "complete",
            "candidates": [{"id": "paper-a", "title": "Study A"}],
            "review_decisions": {},
            "acquisitions": [],
            "result": {
                "question": question,
                "question_brief": question_brief,
                "answer_summary": "Supported answer",
                "evidence": [
                    {
                        "id": "ev-a",
                        "publication_id": "paper-a",
                        "publication_title": "Study A",
                        "statement": "A finding",
                        "passage": "An exact retained passage",
                    }
                ],
                "research_run": {"candidates": [{"id": "paper-a", "title": "Study A"}]},
            },
        }
        directory = self.root / "retained"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "run.json").write_text(json.dumps(state))
        return state

    def get(self, run_id):
        return json.loads((self.root / run_id / "run.json").read_text())

    def _update(self, run_id, **changes):
        state = self.get(run_id)
        state.update(changes)
        (self.root / run_id / "run.json").write_text(json.dumps(state))

    def _rebuild_evidence(self, run_id):
        state = self.get(run_id)
        excluded = state["review_decisions"].get("paper-a", {}).get("decision") == "exclude"
        state["result"]["answer_summary"] = (
            "Insufficient evidence" if excluded else "Supported answer"
        )
        state["result"]["evidence"] = (
            []
            if excluded
            else [
                {
                    "id": "ev-a",
                    "publication_id": "paper-a",
                    "statement": "A finding",
                    "passage": "An exact retained passage",
                }
            ]
        )
        state["result"]["research_run"]["review_decisions"] = state["review_decisions"]
        state.pop("run_id", None)
        self._update(run_id, **state)

    def download_literature_review(self, run_id, output_format="html"):
        summary = self.get(run_id)["result"]["answer_summary"]
        return DownloadPayload("review.html", "text/html", f"<h1>{summary}</h1>".encode())

    def download_research_package(self, run_id):
        return DownloadPayload("research.zip", "application/zip", b"retained package")


def login(client):
    client.post("/auth/development")
    return {"X-CSRF-Token": client.get("/api/v1/session").json()["csrf_token"]}


def wait_completed(client, url):
    for _ in range(200):
        data = client.get(url).json()
        if data.get("status") in {"completed", "failed"}:
            assert data["status"] == "completed", data
            return data
        time.sleep(0.01)
    raise AssertionError("research did not finish")


def application(monkeypatch, tmp_path):
    from sci_search.infrastructure import local_research

    monkeypatch.setattr(local_research, "_manager", RetainedManager)
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "development")
    return build_api_application(
        Path("my_research"), unsafe_development=True, local_research_root=tmp_path
    )


def test_saved_searches_projects_and_exports_survive_restart(monkeypatch, tmp_path):
    RetainedManager.calls = []
    with TestClient(application(monkeypatch, tmp_path)) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        ids = []
        for question in ["Question A", "Question B"]:
            response = client.post(
                base,
                headers=headers,
                json={"question": question, "review_depth": "focused", "idempotency_key": question},
            )
            ids.append(response.json()["id"])
            wait_completed(client, base + "/" + ids[-1])
        first = client.get(base + "/" + ids[0] + "/dashboard")
        assert first.status_code == 200
        before = first.json()
        assert before["question"] == "Question A"
        assert len(before["blocks"]) >= 13
        export_url = before["artifacts"][0]["url"]
        export_bytes = client.get(export_url).content
        workspace = client.get("/api/v1/workspaces").json()["items"][0]["id"]
        created = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"workspace_id": workspace, "name": "Another project", "is_private": True},
        )
        assert created.status_code == 201

    with TestClient(application(monkeypatch, tmp_path)) as client:
        login(client)
        projects = client.get("/api/v1/projects").json()["items"]
        assert {p["id"] for p in projects} == {project, created.json()["id"]}
        history = client.get(base).json()
        assert {item["id"] for item in history["items"]} == set(ids)
        assert client.get(base + "/" + ids[0] + "/dashboard").json() == before
        assert client.get(export_url).content == export_bytes
        filtered = client.get(base, params={"query": "Question A"}).json()
        assert [item["id"] for item in filtered["items"]] == [ids[0]]
        page = client.get(base, params={"limit": 1}).json()
        next_page = client.get(base, params={"limit": 1, "cursor": page["next_cursor"]}).json()
        assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert RetainedManager.calls == ["Question A", "Question B"]


def test_feedback_creates_revision_and_preserves_previous_download(monkeypatch, tmp_path):
    with TestClient(application(monkeypatch, tmp_path)) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={"question": "Question A", "review_depth": "focused", "idempotency_key": "a"},
        ).json()
        url = base + "/" + run["id"]
        wait_completed(client, url)
        old = client.get(url + "/dashboard").json()
        old_export = old["artifacts"][0]["url"]
        body = {
            "decision": "exclude",
            "reason": "Wrong population",
            "expected_sequence": 0,
            "idempotency_key": "exclude-1",
        }
        response = client.post(url + "/articles/paper-a/feedback", headers=headers, json=body)
        assert response.status_code == 202, response.text
        assert (
            client.post(url + "/articles/paper-a/feedback", headers=headers, json=body).json()
            == response.json()
        )
        for _ in range(200):
            new = client.get(url + "/dashboard").json()
            if new["revision"] == 2:
                break
            time.sleep(0.01)
        assert new["revision"] == 2, new
        assert "Insufficient evidence" in json.dumps(new["blocks"])
        assert b"Supported answer" in client.get(old_export).content
        assert client.get(url + "/dashboard?revision=1").json()["blocks"] == old["blocks"]
        stale = {**body, "idempotency_key": "stale", "decision": "include"}
        assert (
            client.post(url + "/articles/paper-a/feedback", headers=headers, json=stale).status_code
            == 409
        )
        unknown = {**body, "expected_sequence": 1, "idempotency_key": "unknown"}
        assert (
            client.post(
                url + "/articles/unknown/feedback", headers=headers, json=unknown
            ).status_code
            == 404
        )
        assert len(client.get(url + "/revisions").json()["items"]) == 2


def test_rebuild_failure_retry_and_reset_survive_restart(monkeypatch, tmp_path):
    app = application(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={"question": "Question A", "review_depth": "focused", "idempotency_key": "a"},
        ).json()
        url = base + "/" + run["id"]
        wait_completed(client, url)
        original = RetainedManager._rebuild_evidence

        def unavailable(self, run_id):
            raise RuntimeError("synthetic synthesis failure")

        monkeypatch.setattr(RetainedManager, "_rebuild_evidence", unavailable)
        body = {
            "decision": "exclude",
            "reason": "Wrong population",
            "expected_sequence": 0,
            "idempotency_key": "failure",
        }
        assert (
            client.post(url + "/articles/paper-a/feedback", headers=headers, json=body).status_code
            == 202
        )
        for _ in range(200):
            snapshot = client.get(url + "/dashboard").json()
            if snapshot["rebuild_status"] == "failed":
                break
            time.sleep(0.01)
        assert snapshot["revision"] == 1
        assert snapshot["rebuild_status"] == "failed"
        monkeypatch.setattr(RetainedManager, "_rebuild_evidence", original)
    with TestClient(application(monkeypatch, tmp_path)) as client:
        headers = login(client)
        assert client.get(url + "/dashboard").json()["rebuild_status"] == "failed"
        assert client.post(url + "/rebuild/retry", headers=headers).status_code == 202
        for _ in range(200):
            if client.get(url + "/dashboard").json()["revision"] == 2:
                break
            time.sleep(0.01)
        assert client.get(url + "/dashboard").json()["revision"] == 2
        body = {
            "decision": "reset",
            "reason": "",
            "expected_sequence": 1,
            "idempotency_key": "reset",
        }
        assert (
            client.post(url + "/articles/paper-a/feedback", headers=headers, json=body).status_code
            == 202
        )
        for _ in range(200):
            snapshot = client.get(url + "/dashboard").json()
            if snapshot["revision"] == 3:
                break
            time.sleep(0.01)
        assert snapshot["revision"] == 3
        assert snapshot["effective_decisions"] == {}
        assert "Supported answer" in json.dumps(snapshot["blocks"])


def test_history_and_feedback_are_project_scoped(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from sci_search.application.projects import Membership, ProjectRole

    app = application(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = login(client)
        projects = app.state.api_services.projects.repository
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={
                "question": "Private question",
                "review_depth": "focused",
                "idempotency_key": "private",
            },
        ).json()
        url = base + "/" + run["id"]
        wait_completed(client, url)
        projects.add_membership(
            Membership(
                "viewer", "viewer", ProjectRole.VIEWER, True, datetime.now(UTC), project_id=project
            )
        )
        token = app.state.api_services.sessions.create("viewer").token
        client.cookies.set("sci_search_session", token)
        viewer_headers = {"X-CSRF-Token": client.get("/api/v1/session").json()["csrf_token"]}
        assert client.get(url + "/dashboard").status_code == 200
        assert (
            client.post(
                url + "/articles/paper-a/feedback",
                headers=viewer_headers,
                json={
                    "decision": "exclude",
                    "reason": "",
                    "expected_sequence": 0,
                    "idempotency_key": "bad",
                },
            ).status_code
            == 404
        )
        token = app.state.api_services.sessions.create("outsider").token
        client.cookies.set("sci_search_session", token)
        assert client.get(base).status_code == 404
        assert client.get(url + "/dashboard").status_code == 404
        assert client.get(url + "/revisions").status_code == 404


def test_new_feedback_is_not_lost_when_older_rebuild_fails(monkeypatch, tmp_path):
    from threading import Event

    started, release = Event(), Event()
    original = RetainedManager._rebuild_evidence
    attempts = 0

    def rebuild(self, run_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            assert release.wait(5)
            raise RuntimeError("old generation failed")
        original(self, run_id)

    app = application(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={
                "question": "Race question",
                "review_depth": "focused",
                "idempotency_key": "race",
            },
        ).json()
        url = base + "/" + run["id"]
        wait_completed(client, url)
        monkeypatch.setattr(RetainedManager, "_rebuild_evidence", rebuild)
        try:
            assert (
                client.post(
                    url + "/articles/paper-a/feedback",
                    headers=headers,
                    json={
                        "decision": "exclude",
                        "reason": "",
                        "expected_sequence": 0,
                        "idempotency_key": "first",
                    },
                ).status_code
                == 202
            )
            assert started.wait(5)
            assert (
                client.post(
                    url + "/articles/paper-a/feedback",
                    headers=headers,
                    json={
                        "decision": "include",
                        "reason": "",
                        "expected_sequence": 1,
                        "idempotency_key": "second",
                    },
                ).status_code
                == 202
            )
        finally:
            release.set()
        for _ in range(200):
            snapshot = client.get(url + "/dashboard").json()
            if snapshot["revision"] == 2:
                break
            time.sleep(0.01)
        assert snapshot["applied_feedback_sequence"] == 2
        assert snapshot["rebuild_status"] == "idle"


def test_finding_reviews_use_current_revision_ids(monkeypatch, tmp_path):
    with TestClient(application(monkeypatch, tmp_path)) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={"question": "Question A", "review_depth": "focused", "idempotency_key": "a"},
        ).json()
        url = base + "/" + run["id"]
        wait_completed(client, url)
        before = client.get(url + "/dashboard").json()
        evidence = before["evidence_reviews"]["ev-a"]
        review_url = f"/api/v1/projects/{project}/evidence/{evidence['id']}/review"
        review = client.patch(
            review_url,
            headers=headers,
            json={"decision": "rejected", "expected_version": evidence["version"]},
        )
        assert review.status_code == 200
        updated = client.get(url + "/dashboard").json()["evidence_reviews"]["ev-a"]
        assert updated["review_decision"] == "rejected"
        assert updated["version"] == evidence["version"] + 1
        client.post(
            url + "/articles/paper-a/feedback",
            headers=headers,
            json={
                "decision": "include",
                "reason": "",
                "expected_sequence": 0,
                "idempotency_key": "include",
            },
        )
        for _ in range(200):
            if client.get(url + "/dashboard").json()["revision"] == 2:
                break
            time.sleep(0.01)
        assert client.get(url + "/dashboard").json()["revision"] == 2
        assert (
            client.patch(
                review_url,
                headers=headers,
                json={"decision": "accepted", "expected_version": updated["version"]},
            ).status_code
            == 409
        )


def test_memory_recovery_does_not_skip_failed_earlier_revision(monkeypatch, tmp_path):
    app = application(monkeypatch, tmp_path)
    service = app.state.api_services.research
    with TestClient(app) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={"question": "Question A", "review_depth": "focused", "idempotency_key": "a"},
        ).json()
        wait_completed(client, base + "/" + run["id"])
        service._executor.shutdown(wait=True)
        key = (project, run["id"])
        service._metadata[key]["memory_revision"] = 0

        class Memory:
            def record_feedback(self, event):
                pass

            def publish_pending(self, *, revision, published_run_id):
                if revision == 1:
                    raise RuntimeError("first revision temporarily unavailable")

        service._publish_memory(Memory(), 1, key)
        service._publish_memory(Memory(), 2, key)
        assert service._metadata[key]["memory_status"] == "pending"
        assert service._metadata[key]["memory_revision"] == 0


def test_invalid_confirmed_plan_is_rejected_before_scheduling(monkeypatch, tmp_path):
    with TestClient(application(monkeypatch, tmp_path)) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        question = "How do energy markets affect household prices in Europe?"
        brief = client.post(
            base + "/interpret", headers=headers, json={"question": question}
        ).json()
        brief["research_plan"] = {
            "intent": "relationship",
            "subject_terms": ["household prices"],
            "driver_terms": ["energy markets"],
            "geography_terms": ["Europe"],
            "evidence_preferences": ["unsupported study filter"],
            "exclusion_terms": [],
        }
        response = client.post(
            base,
            headers=headers,
            json={"question": question, "question_brief": brief, "idempotency_key": "invalid"},
        )
        assert response.status_code == 422
        assert "Unsupported evidence filter" in response.json()["detail"]
        assert client.get(base).json()["items"] == []


def test_approved_question_brief_survives_research_and_restart(monkeypatch, tmp_path):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with TestClient(application(monkeypatch, tmp_path)) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        question = "How do energy markets affect household prices in Europe?"
        brief = client.post(
            base + "/interpret", headers=headers, json={"question": question}
        ).json()
        assert client.get(base).json()["items"] == []
        response = client.post(
            base,
            headers=headers,
            json={
                "question": question,
                "question_brief": brief,
                "idempotency_key": "approved",
            },
        )
        assert response.status_code == 201, response.text
        run_id = response.json()["id"]
        wait_completed(client, base + "/" + run_id)
        dashboard = client.get(base + "/" + run_id + "/dashboard").json()
        assert brief["objective"] in json.dumps(dashboard)
    with TestClient(application(monkeypatch, tmp_path)) as client:
        login(client)
        assert client.get(base + "/" + run_id + "/dashboard").json() == dashboard


class ContradictionManager(RetainedManager):
    def run_sync(self, question, *, limits, question_brief=None):
        state = super().run_sync(question, limits=limits, question_brief=question_brief)
        state["result"]["literature_review_report"] = {
            "executive_summary": {"text": "Contested answer", "evidence_ids": ["ev-a"]},
            "contradiction_groups": [
                {"id": "contradiction:api", "topic": "Direction of effect", "severity": "high"}
            ],
            "answer_contest": {"contested": True, "group_ids": ["contradiction:api"]},
        }
        (self.root / "retained" / "run.json").write_text(json.dumps(state))
        return state


def test_dashboard_route_returns_contradiction_groups(monkeypatch, tmp_path):
    from sci_search.infrastructure import local_research

    monkeypatch.setattr(local_research, "_manager", ContradictionManager)
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "development")
    app = build_api_application(
        Path("my_research"), unsafe_development=True, local_research_root=tmp_path
    )
    with TestClient(app) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run_id = client.post(
            base,
            headers=headers,
            json={
                "question": "Question contradiction",
                "review_depth": "focused",
                "idempotency_key": "contradiction",
            },
        ).json()["id"]
        wait_completed(client, f"{base}/{run_id}")
        blocks = {b["id"]: b for b in client.get(f"{base}/{run_id}/dashboard").json()["blocks"]}
    assert blocks["comparisons"]["data"]["contradiction_groups"][0]["id"] == "contradiction:api"
    assert blocks["answer"]["data"]["answer_contest"]["contested"] is True


def test_model_choice_survives_retry_restart_and_feedback(monkeypatch, tmp_path):
    from sci_search.infrastructure import local_research
    from sci_search.model_provider import configured_analyzer

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_MODELS", '{"openai":["chosen-model"]}')
    choice = {"provider": "openai", "model": "chosen-model"}
    calls = []

    class SelectedManager(RetainedManager):
        def run_sync(self, *args, **kwargs):
            analyzer = configured_analyzer()
            calls.append((analyzer.provider.name, analyzer.model))
            if len(calls) == 1:
                raise RuntimeError("test retry")
            return super().run_sync(*args, **kwargs)

        def _rebuild_evidence(self, run_id):
            analyzer = configured_analyzer()
            calls.append((analyzer.provider.name, analyzer.model))
            return super()._rebuild_evidence(run_id)

    app = application(monkeypatch, tmp_path)
    monkeypatch.setattr(local_research, "_manager", SelectedManager)
    with TestClient(app) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run = client.post(
            base,
            headers=headers,
            json={
                "question": "Question A",
                "idempotency_key": "chosen",
                "analysis_selection": choice,
            },
        ).json()
        url = base + "/" + run["id"]
        for _ in range(200):
            if client.get(url).json()["status"] == "failed":
                break
            time.sleep(0.01)
        assert client.get(url).json()["status"] == "failed"
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral")
    monkeypatch.setenv("OPENAI_MODEL", "changed-default")
    # Existing runs keep their choice even if the new-run menu changes.
    monkeypatch.delenv("SCI_SEARCH_ANALYSIS_MODELS")
    app = application(monkeypatch, tmp_path)
    monkeypatch.setattr(local_research, "_manager", SelectedManager)
    with TestClient(app) as client:
        headers = login(client)
        assert client.get(url).json()["analysis_selection"] == choice
        assert client.post(url + "/retry", headers=headers).status_code == 200
        wait_completed(client, url)
        assert client.get(url + "/dashboard").json()["analysis"]["selection"] == choice
        response = client.post(
            url + "/articles/paper-a/feedback",
            headers=headers,
            json={
                "decision": "exclude",
                "reason": "Wrong population",
                "expected_sequence": 0,
                "idempotency_key": "exclude-chosen",
            },
        )
        assert response.status_code == 202
        for _ in range(200):
            snapshot = client.get(url + "/dashboard").json()
            if snapshot["revision"] == 2:
                break
            time.sleep(0.01)
        assert snapshot["revision"] == 2
        assert snapshot["analysis"]["selection"] == choice
    assert calls == [("openai", "chosen-model")] * 3
