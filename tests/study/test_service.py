import json
import threading

import pytest

from sci_search.study.schema import PlanError
from sci_search.study.service import Busy, Locked, StudyService
from sci_search.study.store import StudyStore
from tests.study.conftest import SCAN, make_plan


class FakeAnalyzer:
    model = "fake-model"
    api_key = "key"

    class provider:
        name = "codex"

    def __init__(self, *replies):
        self.replies = list(replies) or [make_plan()]

    def complete_json(self, body, headers):
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": {"content": json.dumps(reply)}}]}


def fake_scan(question, progress):
    progress("Searching publications.")
    return dict(SCAN)


def service(tmp_path, analyzer=None, scan=None, background=False, extend=None):
    return StudyService(
        StudyStore(tmp_path),
        analyzer_factory=lambda: analyzer or FakeAnalyzer(),
        scan=scan or (lambda q, progress: fake_scan(q, progress)),
        extend=extend
        or (
            lambda s, terms, progress: {
                **s,
                "publications": [*s["publications"], {"id": "P2", "title": "H2"}],
            }
        ),
        background=background,
    )


def test_start_scans_writes_plan_and_records_progress(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("How much storage?")
    study = svc.store.get(sid)
    assert study["status"] == "draft" and study["version"] == 1
    assert study["model"] == "codex · fake-model"
    assert "Searching publications." in [p["message"] for p in study["progress"]]


def test_failure_marks_the_study_failed(tmp_path):
    svc = service(tmp_path, analyzer=FakeAnalyzer(OSError("model down")))
    sid = svc.start("Q")
    study = svc.store.get(sid)
    assert study["status"] == "failed" and "model down" in study["error"]


def test_question_is_validated(tmp_path):
    svc = service(tmp_path)
    for bad in ("   ", "x" * 2001):
        with pytest.raises(ValueError):
            svc.start(bad)
    assert svc.store.list() == []


def test_no_model_is_reported(tmp_path):
    svc = StudyService(StudyStore(tmp_path), analyzer_factory=lambda: None, background=False)
    with pytest.raises(ValueError, match="No AI model"):
        svc.start("Q")


def test_recover_marks_interrupted_scans_failed(tmp_path):
    store = StudyStore(tmp_path)
    sid = store.create("Q", None)
    StudyService(store, analyzer_factory=FakeAnalyzer).recover()
    assert store.get(sid)["status"] == "failed" and "Interrupted" in store.get(sid)["error"]


def test_progress_is_readable_while_scanning(tmp_path):
    release = threading.Event()
    reported = threading.Event()

    def slow_scan(question, progress):
        progress("Searching publications.")
        reported.set()
        release.wait(5)
        return dict(SCAN)

    svc = service(tmp_path, scan=slow_scan, background=True)
    sid = svc.start("Q")
    assert reported.wait(5)
    study = StudyStore(tmp_path).get(sid)
    assert study["status"] == "scanning"
    assert study["progress"][-1]["message"] == "Searching publications."
    with pytest.raises(Busy):
        svc.start("Another question")
    release.set()
    svc.join()
    assert svc.store.get(sid)["status"] == "draft"


def test_approved_plan_is_locked(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("Q")
    svc.approve(sid)
    assert svc.store.get(sid)["approved_version"] == 1
    for action in (
        lambda: svc.revise(sid, "scope", "shorter"),
        lambda: svc.edit(sid, "scope", ["x"]),
        lambda: svc.search_more(sid, ["hydrogen"]),
    ):
        with pytest.raises(Locked):
            action()
    svc.reopen(sid)
    assert svc.edit(sid, "scope", ["x"]) == 2


def test_invalid_edit_writes_no_version(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("Q")
    with pytest.raises(PlanError):
        svc.edit(
            sid,
            "chapters",
            [{"title": "", "goal": "g", "method": "model", "answers": ["Q1"], "output": "o"}],
        )
    assert svc.store.get(sid)["version"] == 1


def test_revise_records_the_instruction(tmp_path):
    reply = make_plan(scope=["Netherlands", "Imports as scenarios"])
    svc = service(tmp_path, analyzer=FakeAnalyzer(make_plan(), reply))
    sid = svc.start("Q")
    result = svc.revise(sid, "scope", "Add imports")
    assert result == {"version": 2, "changed": ["scope"]}
    assert svc.store.versions(sid)[-1]["origin"] == "instruction: Add imports"


def test_search_more_extends_the_scan_without_a_new_version(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("Q")
    svc.search_more(sid, ["hydrogen storage"])
    assert [p["id"] for p in svc.store.read_scan(sid)["publications"]] == ["P1", "P2"]
    assert svc.store.get(sid)["version"] == 1 and svc.store.get(sid)["status"] == "draft"


def test_restore_creates_a_new_version(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("Q")
    svc.edit(sid, "scope", ["Changed"])
    assert svc.restore(sid, 1) == 3
    assert svc.store.version(sid, 3)["plan"] == svc.store.version(sid, 1)["plan"]
    assert svc.store.versions(sid)[-1]["origin"] == "restore v1"


def test_search_more_reports_what_it_found(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("Q")
    svc.search_more(sid, ["hydrogen storage"])
    assert svc.store.get(sid)["notice"] == (
        "Extra search found 1 new publication and 0 new datasets. "
        "Ask for a change in a section to use them."
    )


class BlockingAnalyzer(FakeAnalyzer):
    """Writes the first plan, then blocks the next model call until released."""

    def __init__(self):
        super().__init__(make_plan(), make_plan(scope=["Revised"]))
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def complete_json(self, body, headers):
        self.calls += 1
        if self.calls > 1:
            self.entered.set()
            self.release.wait(5)
        return super().complete_json(body, headers)


def test_changes_wait_for_a_running_revision(tmp_path):
    analyzer = BlockingAnalyzer()
    svc = service(tmp_path, analyzer=analyzer)
    sid = svc.start("Q")
    worker = threading.Thread(target=lambda: svc.revise(sid, "scope", "Revise"))
    worker.start()
    assert analyzer.entered.wait(5)
    assert svc.store.get(sid)["working"] is True
    for action in (
        lambda: svc.edit(sid, "definitions", []),
        lambda: svc.approve(sid),
        lambda: svc.restore(sid, 1),
    ):
        with pytest.raises(Busy):
            action()
    analyzer.release.set()
    worker.join(5)
    assert svc.store.get(sid)["working"] is False
    assert svc.store.get(sid)["version"] == 2 and svc.store.get(sid)["status"] == "draft"


def test_interrupted_extra_search_keeps_the_plan_and_says_so(tmp_path):
    svc = service(tmp_path)
    sid = svc.start("Q")
    svc.store.update(sid, working=True)
    svc.recover()
    study = svc.store.get(sid)
    assert study["status"] == "draft" and study["working"] is False
    assert study["error"] == "The last search or revision was interrupted; the plan is unchanged."
    svc.edit(sid, "scope", ["x"])
    assert svc.store.get(sid)["error"] is None
