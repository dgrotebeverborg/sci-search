import time
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from sci_search.api.bootstrap import build_api_application
from sci_search.research_runs import DownloadPayload


def test_local_research_completes_and_exports_real_pipeline_output(monkeypatch, tmp_path):
    from sci_search.infrastructure import local_research

    calls = []
    release = Event()

    class Manager:
        def set_progress_callback(self, callback):
            self.progress_callback = callback

        def run_sync(self, question, *, limits):
            self.progress_callback({
                "stage": "acquiring", "message": "Inspecting the downloaded workbook",
                "started_at": "2026-10-09T10:00:00Z", "updated_at": "2026-10-09T10:00:01Z",
                "counters": {}, "events": [{"at": "2026-10-09T10:00:01Z", "message": "Inspecting the downloaded workbook"}],
            })
            calls.append(question)
            assert release.wait(5)
            return {
                "status": "complete",
                "run_id": "result",
                "result": {
                    "evidence": [
                        {
                            "statement": "An actual finding",
                            "passage": "An exact source passage",
                            "publication_title": "Source study",
                        }
                    ]
                },
            }

        def download_literature_review(self, run_id, output_format="html"):
            return DownloadPayload("review.html", "text/html", b"<h1>Actual report</h1>")

        def download_research_package(self, run_id):
            return DownloadPayload("research.zip", "application/zip", b"package")

    monkeypatch.setattr(local_research, "_manager", lambda root: Manager())
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "development")
    monkeypatch.setenv("SCI_SEARCH_ALLOWED_ORIGINS", "http://127.0.0.1:8000")
    app = build_api_application(
        Path("my_research"), unsafe_development=True, local_research_root=tmp_path
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post("/auth/development")
        assert "local-research-notice" in response.text
        assert "workspace-preview-notice" not in response.text
        headers = {"X-CSRF-Token": client.get("/api/v1/session").json()["csrf_token"]}
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        url = f"/api/v1/projects/{project}"
        body = {"question": "Does this work?", "review_depth": "focused", "idempotency_key": "one"}
        first = client.post(url + "/runs", json=body, headers=headers)
        assert first.status_code == 201
        run_id = first.json()["id"]
        assert client.post(url + "/runs", json=body, headers=headers).json()["id"] == run_id
        for _ in range(100):
            running = client.get(url + "/runs/" + run_id).json()
            if running.get("progress"):
                break
            time.sleep(0.02)
        assert running["progress"]["message"] == "Inspecting the downloaded workbook"
        assert client.get(f"/api/v1/projects/missing/runs/{run_id}").status_code == 404
        release.set()
        for _ in range(100):
            run = client.get(url + "/runs/" + run_id).json()
            if run["status"] == "completed":
                break
            time.sleep(0.02)
        assert run["status"] == "completed"
        assert calls == ["Does this work?"]
        evidence = client.get(url + "/evidence").json()["items"]
        assert evidence[0]["source_passage"] == "An exact source passage"
        exports = client.get(url + "/exports").json()["items"]
        assert len(exports) == 2
        assert any(
            client.get(url + "/exports/" + e["id"]).content == b"<h1>Actual report</h1>"
            for e in exports
        )

        body["question"] = "A different research question"
        body["idempotency_key"] = "two"
        second = client.post(url + "/runs", json=body, headers=headers).json()
        for _ in range(100):
            if client.get(url + "/runs/" + second["id"]).json()["status"] == "completed":
                break
            time.sleep(0.02)
        assert client.get(url + "/runs/" + second["id"]).json()["status"] == "completed"
        assert len(client.get(url + "/evidence").json()["items"]) == 1
        assert len(client.get(url + "/exports").json()["items"]) == 2


def test_local_research_failure_can_retry_and_cancel_without_publishing(monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from uuid import uuid4

    from sci_search.application.projects import (
        InMemoryProjectRepository,
        Membership,
        Project,
        ProjectRole,
        Workspace,
    )
    from sci_search.infrastructure import local_research

    now = datetime.now(UTC)
    projects = InMemoryProjectRepository()
    projects.add_workspace(Workspace("w", "Workspace", "user", True, now))
    projects.add_project(Project("p", "w", "Project", "user", True, now))
    projects.add_membership(Membership("m", "user", ProjectRole.OWNER, True, now, project_id="p"))
    started, release = Event(), Event()
    calls = 0

    class Manager:
        def run_sync(self, question, *, limits):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Provider unavailable")
            started.set()
            assert release.wait(5)
            return {"status": "complete", "run_id": "result", "result": {}}

    monkeypatch.setattr(local_research, "_manager", lambda root: Manager())
    service = local_research.LocalResearchService(
        projects, root=tmp_path, clock=lambda: datetime.now(UTC), id_source=lambda: str(uuid4())
    )
    try:
        run = service.start_run(
            "user", "p", question="Question", review_depth="focused", idempotency_key="1"
        )
        for _ in range(100):
            if service.get_run("user", "p", run.id).status == "failed":
                break
            time.sleep(0.02)
        assert service.get_run("user", "p", run.id).status == "failed"
        service.retry_run("user", "p", run.id)
        assert started.wait(5)
        service.cancel_run("user", "p", run.id)
        release.set()
    finally:
        release.set()
        service.close()
    assert service.get_run("user", "p", run.id).status == "cancelled"
    assert service.list_exports("user", "p") == []


def test_starting_another_question_hides_previous_results(monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from uuid import uuid4

    from sci_search.application.projects import (
        InMemoryProjectRepository,
        Membership,
        Project,
        ProjectRole,
        Workspace,
    )
    from sci_search.infrastructure.local_research import LocalResearchService

    now = datetime.now(UTC)
    projects = InMemoryProjectRepository()
    projects.add_workspace(Workspace("w", "Workspace", "user", True, now))
    projects.add_project(Project("p", "w", "Project", "user", True, now))
    projects.add_membership(Membership("m", "user", ProjectRole.OWNER, True, now, project_id="p"))
    service = LocalResearchService(
        projects, root=tmp_path, clock=lambda: now, id_source=lambda: str(uuid4())
    )
    monkeypatch.setattr(service, "_execute", lambda *args: None)
    try:
        service.seed_evidence("p", "old", statement="Green spaces", source_passage="Old passage")
        service.seed_export(
            "p", "old", filename="old.html", content_type="text/html", chunks=(b"old",)
        )
        service.start_run(
            "user", "p", question="Landslides", review_depth="focused", idempotency_key="new"
        )
        assert service.list_evidence("user", "p", offset=0, limit=25) == ([], 0)
        assert service.list_exports("user", "p") == []
    finally:
        service.close()


def test_cooperative_cancel_releases_worker_for_queued_run(monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from uuid import uuid4

    from sci_search.application.projects import (
        InMemoryProjectRepository,
        Membership,
        Project,
        ProjectRole,
        Workspace,
    )
    from sci_search.infrastructure import local_research
    from sci_search.research_runs import ResearchRunManager

    now = datetime.now(UTC)
    projects = InMemoryProjectRepository()
    projects.add_workspace(Workspace("w", "Workspace", "user", True, now))
    projects.add_project(Project("p", "w", "Project", "user", True, now))
    projects.add_membership(Membership("m", "user", ProjectRole.OWNER, True, now, project_id="p"))
    started = [Event(), Event()]
    release = [Event(), Event()]
    calls = [0, 0]
    managers = []

    class Provider:
        name = "test"

        def __init__(self, index):
            self.index = index

        def search(self, query, *, limit):
            calls[self.index] += 1
            started[self.index].set()
            assert release[self.index].wait(5)
            return ()

    def manager(root):
        result = ResearchRunManager(
            root, providers=(Provider(len(managers)),), openalex_api_key="test"
        )
        managers.append(result)
        return result

    monkeypatch.setattr(local_research, "_manager", manager)
    service = local_research.LocalResearchService(
        projects, root=tmp_path, clock=lambda: datetime.now(UTC), id_source=lambda: str(uuid4())
    )
    monkeypatch.setattr(service, "_attach_memory", lambda *args: None)
    question = "How does rainfall affect crop yield?"
    try:
        first = service.start_run(
            "user",
            "p",
            question=question,
            review_depth="focused",
            question_brief={"original_question": question},
            idempotency_key="first",
        )
        assert started[0].wait(5)
        second = service.start_run(
            "user",
            "p",
            question=question,
            review_depth="focused",
            question_brief={"original_question": question},
            idempotency_key="second",
        )
        service.cancel_run("user", "p", first.id)
        release[0].set()
        assert started[1].wait(5)
        assert service.get_run("user", "p", first.id).status == "cancelled"
        service.cancel_run("user", "p", second.id)
        release[1].set()
    finally:
        for event in release:
            event.set()
        service.close()
    assert calls == [1, 1]
    assert service.get_run("user", "p", second.id).status == "cancelled"
    assert service.list_exports("user", "p") == []
