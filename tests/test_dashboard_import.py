import pytest

from tests.api.test_saved_local_dashboards import RetainedManager, application


def test_import_retained_run_is_idempotent_and_never_searches(monkeypatch, tmp_path):
    from sci_search.infrastructure.dashboard_import import import_local_run

    source = tmp_path / "old"
    manager = RetainedManager(source)
    manager.run_sync("Old scientific question", limits=None)
    RetainedManager.calls = []
    app = application(monkeypatch, tmp_path / "workspace")
    service = app.state.api_services.research
    project = app.state.api_services.projects.list_for_user("development-researcher")[0].id
    try:
        preview = import_local_run(
            service, "development-researcher", project, source / "retained", dry_run=True
        )
        assert preview["status"] == "ready"
        assert service.list_runs("development-researcher", project)["items"] == []
        receipt = import_local_run(service, "development-researcher", project, source / "retained")
        repeated = import_local_run(service, "development-researcher", project, source / "retained")
        assert receipt["run_id"] == repeated["run_id"]
        dashboard = service.get_dashboard("development-researcher", project, receipt["run_id"])
        assert dashboard["question"] == "Old scientific question"
        assert len(dashboard["blocks"]) >= 13
        assert (source / "retained" / "run.json").exists()
        assert RetainedManager.calls == []
    finally:
        service.close()


def test_import_rejects_unsafe_source_identifiers(monkeypatch, tmp_path):
    import json

    from sci_search.infrastructure.dashboard_import import import_local_run

    source = tmp_path / "old"
    source.mkdir()
    (source / "run.json").write_text(json.dumps({"run_id": "../../escape", "question": "Unsafe"}))
    app = application(monkeypatch, tmp_path / "workspace")
    service = app.state.api_services.research
    project = app.state.api_services.projects.list_for_user("development-researcher")[0].id
    try:
        with pytest.raises(ValueError, match="identifier"):
            import_local_run(service, "development-researcher", project, source)
    finally:
        service.close()


def test_failed_import_can_resume_without_rerunning_research(monkeypatch, tmp_path):
    from sci_search.infrastructure.dashboard_import import import_local_run

    source = tmp_path / "old"
    RetainedManager(source).run_sync("Recover this question", limits=None)
    app = application(monkeypatch, tmp_path / "workspace")
    service = app.state.api_services.research
    user = "development-researcher"
    project = app.state.api_services.projects.list_for_user(user)[0].id
    prepare = service._prepare_revision
    try:

        def fail(*args, **kwargs):
            raise RuntimeError("temporary render failure")

        monkeypatch.setattr(service, "_prepare_revision", fail)
        with pytest.raises(RuntimeError):
            import_local_run(service, user, project, source / "retained")
        existing = service.list_runs(user, project)["items"][0]["id"]
        monkeypatch.setattr(service, "_prepare_revision", prepare)
        result = import_local_run(service, user, project, source / "retained")
        assert result["status"] == "imported"
        assert result["run_id"] == existing
        assert service.get_dashboard(user, project, existing)["revision"] == 1
        assert (source / "retained" / "run.json").is_file()
    finally:
        service.close()
