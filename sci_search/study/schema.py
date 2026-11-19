"""The study plan: its sections, the strict schema for the model, and validation."""

from __future__ import annotations

import copy
from typing import Any

SECTIONS = (
    "question",
    "definitions",
    "subquestions",
    "scope",
    "out_of_reach",
    "existing_work",
    "data",
    "chapters",
    "limits",
)
METHODS = ("literature", "data", "model", "synthesis")


class PlanError(ValueError):
    """A plan that cannot be shown or approved as it is."""


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _items(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": _object(properties)}


_TEXT = {"type": "string"}
PLAN_SCHEMA = _object(
    {
        "question": _TEXT,
        "definitions": _items({"term": _TEXT, "definition": _TEXT}),
        "subquestions": _items({"id": _TEXT, "text": _TEXT}),
        "scope": {"type": "array", "items": _TEXT},
        "out_of_reach": _items({"item": _TEXT, "reason": _TEXT}),
        "existing_work": _items({"scan_id": _TEXT, "why": _TEXT}),
        "data": _items({"scan_id": _TEXT, "provides": _TEXT}),
        "chapters": _items(
            {
                "title": _TEXT,
                "goal": _TEXT,
                "method": {"type": "string", "enum": list(METHODS)},
                "answers": {"type": "array", "items": _TEXT},
                "output": _TEXT,
            }
        ),
        "limits": {"type": "array", "items": _TEXT},
    }
)


def validate_plan(plan: dict[str, Any], scan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A cleaned copy and notes; unknown sources are dropped, structural faults raise."""
    missing = [s for s in SECTIONS if s not in plan]
    if missing:
        raise PlanError("The plan lacks: " + ", ".join(missing))
    cleaned = copy.deepcopy({s: plan[s] for s in SECTIONS})
    notes: list[str] = []
    for section, pool in (("existing_work", "publications"), ("data", "datasets")):
        known = {str(item.get("id")) for item in scan.get(pool) or []}
        kept = []
        for item in cleaned[section]:
            if str(item.get("scan_id")) in known:
                kept.append(item)
            else:
                notes.append(
                    f"Removed a reference to {item.get('scan_id')}: it is not among the scanned sources."
                )
        cleaned[section] = kept
    cleaned["limits"] = [*cleaned["limits"], *notes]

    questions = [str(q.get("id")) for q in cleaned["subquestions"]]
    answered: set[str] = set()
    for number, chapter in enumerate(cleaned["chapters"], 1):
        if not str(chapter.get("title") or "").strip():
            raise PlanError(f"Chapter {number} has no title.")
        if chapter.get("method") not in METHODS:
            raise PlanError(
                f"Chapter {number} has method {chapter.get('method')!r}; use one of {', '.join(METHODS)}."
            )
        unknown = [a for a in chapter.get("answers") or [] if a not in questions]
        if unknown:
            raise PlanError(
                f"Chapter {number} answers unknown sub-questions: {', '.join(unknown)}."
            )
        answered.update(chapter.get("answers") or [])
    uncovered = [q for q in questions if q not in answered]
    if uncovered:
        raise PlanError("No chapter answers sub-question(s): " + ", ".join(uncovered) + ".")
    return cleaned, notes
