import pytest

from sci_search.study.store import StudyStore
from tests.study.conftest import SCAN, make_plan


def test_versions_are_immutable_and_numbered(tmp_path):
    store = StudyStore(tmp_path)
    sid = store.create("How much storage?", "codex · m")
    store.write_scan(sid, SCAN)
    assert store.add_version(sid, make_plan(), "initial", None) == 1
    changed = make_plan(question="Changed")
    assert store.add_version(sid, changed, "instruction: shorter", "question") == 2
    assert store.version(sid, 1)["plan"]["question"] == make_plan()["question"]
    assert [v["origin"] for v in store.versions(sid)] == ["initial", "instruction: shorter"]
    assert store.get(sid)["version"] == 2
    assert store.read_scan(sid) == SCAN
    markdown = (tmp_path / sid / "plan.md").read_text()
    assert "II3050 scenarios" in markdown and "https://example.org/ii3050" in markdown
    assert "Changed" in markdown


def test_new_study_starts_scanning(tmp_path):
    store = StudyStore(tmp_path)
    study = store.get(store.create("Q", None))
    assert study["status"] == "scanning" and study["version"] == 0
    assert study["approved_version"] is None and study["progress"] == []


@pytest.mark.parametrize("bad", ["../etc", "ABCDEF123456", "abc", "0123456789ab/x"])
def test_unsafe_ids_are_rejected(tmp_path, bad):
    with pytest.raises(KeyError):
        StudyStore(tmp_path).get(bad)


def test_writes_are_atomic(tmp_path, monkeypatch):
    store = StudyStore(tmp_path)
    sid = store.create("Q", None)

    def fail(*args):
        raise OSError("disk")

    monkeypatch.setattr("sci_search.study.store.os.replace", fail)
    with pytest.raises(OSError):
        store.update(sid, status="draft")
    monkeypatch.undo()
    assert store.get(sid)["status"] == "scanning"


def test_progress_keeps_last_fifty(tmp_path):
    store = StudyStore(tmp_path)
    sid = store.create("Q", None)
    for i in range(60):
        store.add_progress(sid, f"m{i}")
    progress = store.get(sid)["progress"]
    assert len(progress) == 50 and progress[-1]["message"] == "m59"


def test_list_is_newest_first(tmp_path):
    store = StudyStore(tmp_path)
    first = store.create("First", None)
    second = store.create("Second", None)
    store.update(first, status="draft")
    store.update(second, status="draft")
    assert [s["question"] for s in store.list()][0] == "Second"
