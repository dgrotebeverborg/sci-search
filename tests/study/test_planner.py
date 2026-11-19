import json

import pytest

from sci_search.study.planner import edit_plan, revise_plan, write_plan
from sci_search.study.schema import PlanError
from tests.study.conftest import SCAN, make_plan


class FakeAnalyzer:
    model = "fake-model"
    api_key = "key"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete_json(self, body, headers):
        self.prompts.append(body["messages"][-1]["content"])
        reply = self.replies.pop(0)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return {"choices": [{"message": {"content": content}}]}


def test_write_plan_returns_a_validated_plan():
    analyzer = FakeAnalyzer(make_plan())
    plan, notes = write_plan("Q?", SCAN, analyzer)
    assert plan == make_plan() and notes == []
    assert "P1" in analyzer.prompts[0] and "II3050 scenarios" in analyzer.prompts[0]


def test_write_plan_retries_once_with_the_error():
    analyzer = FakeAnalyzer("not json", make_plan())
    plan, _ = write_plan("Q?", SCAN, analyzer)
    assert plan == make_plan()
    assert len(analyzer.prompts) == 2 and "Previous attempt failed" in analyzer.prompts[1]


def test_write_plan_gives_up_after_two_failures():
    bad = make_plan(chapters=[])
    with pytest.raises(PlanError):
        write_plan("Q?", SCAN, FakeAnalyzer(bad, bad))


def test_failed_scan_steps_appear_in_limits():
    scan = {**SCAN, "steps": [{"name": "datasets", "status": "failed", "detail": "no web search"}]}
    plan, _ = write_plan("Q?", scan, FakeAnalyzer(make_plan()))
    assert "Scan step datasets failed: no web search" in plan["limits"]


def test_revise_keeps_unrelated_sections():
    current = make_plan()
    reply = make_plan(
        question="Rewritten without cause",
        definitions=[{"term": "Storage", "definition": "Energy and power capacity."}],
    )
    plan, changed = revise_plan(
        current, "definitions", "Separate energy and power", SCAN, FakeAnalyzer(reply)
    )
    assert plan["question"] == current["question"]
    assert plan["definitions"][0]["definition"] == "Energy and power capacity."
    assert changed == ["definitions"]


def test_revise_may_update_chapters_for_new_subquestion():
    reply = make_plan(
        subquestions=[{"id": "Q1", "text": "How much?"}, {"id": "Q2", "text": "With imports?"}],
        chapters=[
            {"title": "Model", "goal": "g", "method": "model", "answers": ["Q1"], "output": "o"},
            {
                "title": "Imports",
                "goal": "g",
                "method": "literature",
                "answers": ["Q2"],
                "output": "o",
            },
        ],
    )
    plan, changed = revise_plan(
        make_plan(), "subquestions", "Add imports", SCAN, FakeAnalyzer(reply)
    )
    assert changed == ["subquestions", "chapters"] and len(plan["chapters"]) == 2


def test_revise_unknown_section_raises():
    with pytest.raises(PlanError):
        revise_plan(make_plan(), "nonsense", "x", SCAN, FakeAnalyzer())


def test_edit_plan_validates_without_model_call():
    with pytest.raises(PlanError):
        edit_plan(
            make_plan(),
            "chapters",
            [{"title": "", "goal": "g", "method": "model", "answers": ["Q1"], "output": "o"}],
            SCAN,
        )
    edited = edit_plan(make_plan(), "scope", ["Netherlands", "No imports"], SCAN)
    assert edited["scope"] == ["Netherlands", "No imports"]
