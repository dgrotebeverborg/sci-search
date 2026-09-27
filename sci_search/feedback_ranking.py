"""Conservative, explainable relevance suggestions; never researcher overrides.

Callers must supply authorized events from their authoritative feedback store.
Ranking remains opt-in pending a researcher-labelled held-out evaluation.
"""

from __future__ import annotations

import re
from typing import Any

from sci_search.application.memory import MemoryCandidate
from sci_search.question_planning import ResearchPlan, plan_question

SCORING_VERSION = "contextual_feedback_v1"


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _constraints(question: str) -> set[str]:
    """Recognize explicit populations/outcomes conservatively, with no inference."""
    groups = {
        "children": ("children", "child", "pediatric", "paediatric"),
        "adults": ("adults", "adult"),
        "older_adults": ("elderly", "geriatric"),
        "mice": ("mouse", "mice", "murine"),
        "rats": ("rat", "rats"),
        "humans": ("human", "humans"),
        "mortality": ("mortality", "survival", "death"),
        "blood_pressure": ("blood pressure", "hypertension"),
        "quality_of_life": ("quality of life",),
    }
    return {
        key
        for key, aliases in groups.items()
        if any(
            re.search(r"\b" + re.escape(alias) + r"\b", question.casefold()) for alias in aliases
        )
    }


def _event_order(event: dict[str, Any]) -> tuple[int, str, str]:
    suffix = str(event.get("id") or "").rsplit(":", 1)[-1]
    sequence = event.get("sequence", int(suffix) if suffix.isdigit() else 0)
    return (int(sequence or 0), str(event.get("created_at") or ""), str(event.get("id") or ""))


def score_feedback(plan: ResearchPlan, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        publication = str(event.get("publication_id") or "")
        actor = str(event.get("user_id") or event.get("reviewer") or "")
        context = str(event.get("run_id") or event.get("question") or "")
        # Imported decisions with unknown provenance must not become inferred votes.
        if not publication or not actor or not context or not event.get("question"):
            continue
        key = (actor, context, publication)
        order = _event_order(event)
        previous = latest.get(key)
        if previous is None or order > _event_order(previous):
            latest[key] = event
    votes: dict[str, list[tuple[float, str]]] = {}
    concepts = {x.casefold() for x in plan.concepts}
    for (_, _, publication), event in latest.items():
        decision = str(event.get("decision") or "").casefold()
        if decision not in {"include", "exclude", "background"}:
            continue
        related = plan_question(str(event["question"]))
        if related.profile_id != plan.profile_id:
            continue
        if _constraints(related.question) != _constraints(plan.question):
            continue
        if (
            plan.concepts
            and related.concepts
            and plan.concepts[0].casefold() != related.concepts[0].casefold()
        ):
            continue
        # Explicit subject/population/outcome restrictions are mandatory, never fuzzy.
        if any(
            value and not _tokens(str(value)).issubset(_tokens(plan.question))
            for value in (
                event.get("mandatory_subject"),
                event.get("population"),
                event.get("outcome"),
            )
        ):
            continue
        other = {x.casefold() for x in related.concepts}
        union = concepts | other
        similarity = len(concepts & other) / len(union) if union else 0.0
        if similarity < 0.5:
            continue
        value = {"include": 1, "exclude": -1, "background": 0}[decision] * similarity
        explanation = f"Previously {decision} for related question {event.get('run_id') or event['question']} (decision {event.get('id') or 'legacy'}; similarity {similarity:.2f})."
        votes.setdefault(publication, []).append((value, explanation))
    return {
        publication: {
            "adjustment": max(
                -0.25, min(0.25, 0.25 * sum(value for value, _ in items) / len(items))
            ),
            "explanations": [reason for _, reason in items],
            "conflicting": any(value > 0 for value, _ in items)
            and any(value < 0 for value, _ in items),
            "scoring_version": SCORING_VERSION,
        }
        for publication, items in sorted(votes.items())
    }


def rank_candidates(candidates: tuple[MemoryCandidate, ...]) -> tuple[MemoryCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -(item.base_score + item.feedback_score),
                (item.publication.doi or item.publication.id).casefold(),
            ),
        )
    )
