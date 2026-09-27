from pathlib import Path

import pytest

from sci_search.application.memory import MemoryContext
from sci_search.infrastructure.local_memory import LocalScientificMemory
from sci_search.question_planning import plan_question

pytestmark = pytest.mark.security


def test_project_isolation_and_durable_feedback(tmp_path: Path):
    alice = LocalScientificMemory(tmp_path, MemoryContext("alice", "project-a"))
    alice.record_feedback(
        {
            "id": "event-a",
            "run_id": "run-a",
            "publication_id": "paper-a",
            "question": "iron air battery efficiency",
            "decision": "include",
        }
    )
    reopened = LocalScientificMemory(tmp_path, MemoryContext("alice", "project-a"))
    assert reopened.feedback_events()[0]["user_id"] == "alice"
    bob = LocalScientificMemory(tmp_path, MemoryContext("bob", "project-b"))
    assert bob.feedback_events() == []
    assert bob.graph_snapshot()["nodes"] == []
    assert bob.candidates(plan_question("iron air battery efficiency")) == ()


def test_revoked_access_checked_on_every_read_and_write(tmp_path: Path):
    allowed = True

    def authorize(context):
        if not allowed:
            raise PermissionError("revoked")

    memory = LocalScientificMemory(tmp_path, MemoryContext("alice", "project"), authorize=authorize)
    allowed = False
    for operation in [
        memory.stats,
        memory.feedback_events,
        memory.graph_snapshot,
        lambda: memory.cached_analysis("cache"),
        lambda: memory.record_feedback({"id": "event"}),
    ]:
        with pytest.raises(PermissionError):
            operation()


def test_unsafe_scope_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        LocalScientificMemory(tmp_path, MemoryContext("alice", "../escape"))
