import json

import pytest

from sci_search.study.planner import edit_plan, revise_plan, write_plan
from sci_search.study.schema import PlanError
from tests.study.conftest import CRITIQUE, SCAN, is_critique_call, make_plan


class FakeAnalyzer:
    model = "fake-model"
    api_key = "key"

    def __init__(self, *replies, critique=CRITIQUE):
        self.replies = list(replies)
        self.prompts = []
        self.critique = critique
        self.critique_prompts = []

    def complete_json(self, body, headers):
        if is_critique_call(body):
            self.critique_prompts.append(body["messages"][-1]["content"])
            reply = self.critique
            if isinstance(reply, Exception):
                raise reply
            return {"choices": [{"message": {"content": json.dumps(reply)}}]}
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


def test_write_plan_runs_a_critical_pass_first():
    analyzer = FakeAnalyzer(make_plan())
    write_plan("How much storage at 0, 50 and 100%?", SCAN, analyzer)
    assert len(analyzer.critique_prompts) == 1
    assert "0, 50 and 100%" in analyzer.critique_prompts[0] and "P1" in analyzer.critique_prompts[0]
    assert "The shares 0, 50 and 100% are arbitrary." in analyzer.prompts[0]


def test_options_overview_chapter_is_added_when_needed():
    critique = {
        **CRITIQUE,
        "options_overview": {
            "needed": True,
            "topic": "storage methods",
            "goal": "Map batteries, pumped hydro, hydrogen and heat storage by time scale.",
        },
    }
    plan, _ = write_plan("Q?", SCAN, FakeAnalyzer(make_plan(), critique=critique))
    first = plan["chapters"][0]
    assert first["title"] == "Overview of options: storage methods"
    assert first["method"] == "literature" and first["answers"] == []
    assert first["goal"].startswith("Map batteries")
    assert len(plan["chapters"]) == 2


def test_options_overview_is_not_duplicated():
    critique = {
        **CRITIQUE,
        "options_overview": {"needed": True, "topic": "storage methods", "goal": "g"},
    }
    overview = {
        "title": "Overview of options: storage",
        "goal": "g",
        "method": "literature",
        "answers": ["Q1"],
        "output": "o",
    }
    plan, _ = write_plan(
        "Q?", SCAN, FakeAnalyzer(make_plan(chapters=[overview]), critique=critique)
    )
    assert [c["title"] for c in plan["chapters"]] == ["Overview of options: storage"]


def test_failed_critical_pass_still_writes_the_plan():
    plan, _ = write_plan("Q?", SCAN, FakeAnalyzer(make_plan(), critique={"nonsense": True}))
    assert any("critical review" in line for line in plan["limits"])


def test_critique_revision_may_change_question_and_chapters():
    reply = make_plan(
        question="How does storage need change between 0 and 100% in steps of 10%?",
        critique=[{**make_plan()["critique"][0], "status": "adopted"}],
        definitions=[],
    )
    plan, changed = revise_plan(make_plan(), "critique", "Adopt point 1", SCAN, FakeAnalyzer(reply))
    assert changed == ["question", "critique"]
    assert plan["definitions"] == make_plan()["definitions"]
