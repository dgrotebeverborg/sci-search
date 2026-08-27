"""Validation for the locked, corpus-independent researcher benchmark."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sci_search.question_planning import plan_question

REQUIRED_CASE_FIELDS = frozenset(
    {
        "id",
        "tier",
        "domain",
        "question",
        "expected_intent",
        "required_concepts",
        "answer_policy",
        "must_distinguish",
    }
)


def validate_researcher_benchmark(path: Path) -> dict[str, Any]:
    specification = json.loads(path.read_text(encoding="utf-8"))
    cases = specification.get("cases")
    if specification.get("schema_version") != "sci_search_researcher_benchmark_v1":
        raise ValueError("unsupported researcher benchmark schema")
    if not isinstance(cases, list) or not cases:
        raise ValueError("researcher benchmark cases must be a non-empty list")
    failures: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    planned: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        missing = sorted(REQUIRED_CASE_FIELDS - set(case))
        case_failures = [f"missing field: {item}" for item in missing]
        identifier = str(case.get("id") or f"case-{index + 1}")
        if identifier in identifiers:
            case_failures.append("duplicate id")
        identifiers.add(identifier)
        question = " ".join(str(case.get("question") or "").split())
        if not question.endswith("?"):
            case_failures.append("question must end with a question mark")
        if question:
            plan = plan_question(question)
            if plan.intent != case.get("expected_intent"):
                case_failures.append(f"intent {plan.intent!r} != {case.get('expected_intent')!r}")
            planned_concepts = {*plan.concepts, *plan.entity_phrases}
            for concept in case.get("required_concepts") or []:
                if concept not in planned_concepts:
                    case_failures.append(f"missing planned concept: {concept}")
            planned.append(
                {
                    "id": identifier,
                    "profile": plan.profile_id,
                    "intent": plan.intent,
                    "concepts": list(plan.concepts),
                    "entity_phrases": list(plan.entity_phrases),
                }
            )
        if not case.get("must_distinguish"):
            case_failures.append("must_distinguish cannot be empty")
        if case_failures:
            failures.append({"id": identifier, "failures": case_failures})
    digest_input = "\n".join(str(case.get("question") or "") for case in cases)
    return {
        "schema_version": specification["schema_version"],
        "name": specification.get("name"),
        "lock_version": specification.get("lock_version"),
        "case_count": len(cases),
        "question_sha256": hashlib.sha256(digest_input.encode("utf-8")).hexdigest(),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "plans": planned,
    }
