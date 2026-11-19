import pytest

from sci_search.study.schema import PLAN_SCHEMA, SECTIONS, PlanError, validate_plan
from tests.study.conftest import SCAN, make_plan


def test_valid_plan_passes_unchanged():
    cleaned, notes = validate_plan(make_plan(), SCAN)
    assert cleaned == make_plan() and notes == []


def test_unknown_scan_ids_are_dropped_and_noted():
    cleaned, notes = validate_plan(make_plan(existing_work=[{"scan_id": "P9", "why": "w"}]), SCAN)
    assert cleaned["existing_work"] == []
    assert "P9" in cleaned["limits"][-1] and notes


@pytest.mark.parametrize(
    "change",
    [
        {
            "chapters": [
                {"title": "", "goal": "g", "method": "model", "answers": ["Q1"], "output": "o"}
            ]
        },
        {
            "chapters": [
                {
                    "title": "T",
                    "goal": "g",
                    "method": "experiment",
                    "answers": ["Q1"],
                    "output": "o",
                }
            ]
        },
        {
            "chapters": [
                {"title": "T", "goal": "g", "method": "data", "answers": ["Q7"], "output": "o"}
            ]
        },
        {"subquestions": [{"id": "Q1", "text": "a"}, {"id": "Q2", "text": "uncovered"}]},
    ],
)
def test_structural_errors_raise(change):
    with pytest.raises(PlanError):
        validate_plan(make_plan(**change), SCAN)


def test_missing_section_raises():
    broken = make_plan()
    del broken["limits"]
    with pytest.raises(PlanError):
        validate_plan(broken, SCAN)


def test_schema_is_strict_and_covers_every_section():
    assert SECTIONS == (
        "question",
        "critique",
        "definitions",
        "subquestions",
        "scope",
        "out_of_reach",
        "existing_work",
        "data",
        "chapters",
        "limits",
    )
    assert PLAN_SCHEMA["required"] == list(SECTIONS)
    assert PLAN_SCHEMA["additionalProperties"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"definitions": [{"term": "x"}]},
        {"definitions": [{"term": "x", "definition": ""}]},
        {"limits": "abc"},
        {"question": ["a"]},
        {"question": "   "},
        {"scope": [{"a": 1}]},
        {"subquestions": [{"id": "Q1", "text": ""}]},
        {"chapters": [{"title": "T", "method": "model", "answers": ["Q1"], "output": "o"}]},
        {"existing_work": [{"scan_id": "P1"}]},
    ],
)
def test_malformed_items_raise(change):
    with pytest.raises(PlanError):
        validate_plan(make_plan(**change), SCAN)


def test_duplicate_subquestion_ids_raise():
    plan = make_plan(subquestions=[{"id": "Q1", "text": "a"}, {"id": "Q1", "text": "b"}])
    with pytest.raises(PlanError):
        validate_plan(plan, SCAN)


def test_critique_is_a_section_with_a_status():
    assert SECTIONS[1] == "critique"
    bad = make_plan(critique=[{"issue": "i", "why": "w", "alternative": "a", "status": "maybe"}])
    with pytest.raises(PlanError):
        validate_plan(bad, SCAN)
