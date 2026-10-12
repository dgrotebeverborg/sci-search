from sci_search.research_runs import ResearchLimits, ResearchRunManager


def test_progress_reports_actual_steps_and_keeps_only_public_fields(tmp_path):
    manager = ResearchRunManager(tmp_path, openalex_api_key="fixture")
    updates = []
    manager.set_progress_callback(updates.append)
    state = manager._new_state("test", "Population", ResearchLimits())
    state["result"] = {"private": "must not be in a progress response"}
    manager._set_state("test", state)
    manager._update(
        "test",
        status="running",
        stage="acquiring",
        message="Inspecting EFFIS workbook",
        progress={"full_texts_acquired": 2},
    )
    manager._update("test", message="Executing Python extraction")
    assert updates[-1]["message"] == "Executing Python extraction"
    assert updates[-1]["counters"] == {"full_texts_acquired": 2}
    assert updates[-1]["events"][-2]["message"] == "Inspecting EFFIS workbook"
    assert "result" not in updates[-1]
    assert updates[-1]["updated_at"]
    for index in range(40):
        manager._update("test", message=f"Step {index}")
    assert len(updates[-1]["events"]) == 30


def test_progress_storage_failure_does_not_abort_research(tmp_path):
    manager = ResearchRunManager(tmp_path, openalex_api_key="fixture")

    def broken(progress):
        raise OSError("status storage unavailable")

    manager.set_progress_callback(broken)
    manager._set_state("test", manager._new_state("test", "Population", ResearchLimits()))
    manager._update("test", message="Still calculating")
    assert manager.get("test")["message"] == "Still calculating"
