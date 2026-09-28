"""Structured, inspectable interpretation of a research question before search."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.model_provider import configured_analyzer
from sci_search.question_planning import ResearchPlan, plan_question


@dataclass(frozen=True, slots=True)
class QuestionBrief:
    original_question: str
    interpreted_question: str
    objective: str
    profile_id: str
    intent: str
    concepts: tuple[str, ...]
    evidence_scope: tuple[str, ...]
    comparison_dimensions: tuple[str, ...]
    assumptions: tuple[str, ...]
    exclusions: tuple[str, ...]
    ambiguity: str
    clarification_question: str | None
    method: str
    provider: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


QUESTION_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "interpreted_question",
        "objective",
        "evidence_scope",
        "assumptions",
        "exclusions",
        "ambiguity",
        "clarification_question",
    ],
    "properties": {
        "interpreted_question": {"type": "string", "minLength": 8, "maxLength": 500},
        "objective": {"type": "string", "minLength": 8, "maxLength": 500},
        "evidence_scope": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 150},
        },
        "assumptions": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 200},
        },
        "exclusions": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 200},
        },
        "ambiguity": {"type": "string", "enum": ["clear", "minor", "material"]},
        "clarification_question": {"type": ["string", "null"], "maxLength": 300},
    },
}


def interpret_question(question: str, analyzer: MistralAnalyzer | None = None) -> dict[str, Any]:
    plan = plan_question(question)
    selected = analyzer
    if selected is None:
        selected = configured_analyzer()
    if selected is not None:
        try:
            result = _model_interpretation(question, plan, selected)
            return result.to_dict()
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return _deterministic_brief(question, plan).to_dict()


def _model_interpretation(
    question: str, plan: ResearchPlan, analyzer: MistralAnalyzer
) -> QuestionBrief:
    body = {
        "model": analyzer.model,
        "temperature": 0,
        "max_tokens": 1200,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "research_question_brief",
                "schema": QUESTION_BRIEF_SCHEMA,
                "strict": True,
            },
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate a researcher's question into a faithful research brief before literature search. "
                    "Do not answer the scientific question. Do not add facts. Preserve the user's subject and outcome. "
                    "Do not narrow the population, setting, study type, or outcome unless the user explicitly did so; "
                    "default to no exclusions. Surface only unavoidable assumptions or explicit exclusions that materially affect retrieval. Mark ambiguity material only "
                    "when different reasonable interpretations would produce substantially different corpora. Ask at most "
                    "one specific clarification question. Return the requested JSON only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "deterministic_plan": {
                            "profile": plan.profile_id,
                            "intent": plan.intent,
                            "concepts": plan.concepts,
                            "evidence_preferences": plan.evidence_preferences,
                            "comparison_dimensions": plan.comparison_dimensions,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    response = analyzer.complete_json(
        body,
        {
            "Authorization": f"Bearer {analyzer.api_key}",
            "Content-Type": "application/json",
        },
    )
    raw = response.get("choices", [{}])[0].get("message", {}).get("content")
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise ValueError("question interpretation was not an object")
    ambiguity = str(payload.get("ambiguity") or "")
    if ambiguity not in {"clear", "minor", "material"}:
        raise ValueError("invalid ambiguity classification")
    interpreted = " ".join(str(payload.get("interpreted_question") or "").split())
    objective = " ".join(str(payload.get("objective") or "").split())
    clarification = " ".join(str(payload.get("clarification_question") or "").split()) or None
    if not interpreted or not objective or (ambiguity == "material" and not clarification):
        raise ValueError("incomplete question interpretation")
    return QuestionBrief(
        original_question=question.strip(),
        interpreted_question=interpreted,
        objective=objective,
        profile_id=plan.profile_id,
        intent=plan.intent,
        concepts=plan.concepts,
        evidence_scope=_strings(payload.get("evidence_scope")),
        comparison_dimensions=plan.comparison_dimensions,
        assumptions=_strings(payload.get("assumptions")),
        exclusions=_strings(payload.get("exclusions")),
        ambiguity=ambiguity,
        clarification_question=clarification,
        method=f"{analyzer.provider.name}_structured_question_interpretation_v1",
        provider=analyzer.provider.name,
        model=analyzer.model,
    )


def _deterministic_brief(question: str, plan: ResearchPlan) -> QuestionBrief:
    vague = {"it", "this", "these", "they", "something", "things"}
    concepts = tuple(plan.concepts)
    acronym = plan.profile_id == "generic" and bool(re.search(r"\b[A-Z]{2,5}\b", question))
    definitional = bool(re.search(r"\bwhat (?:does|is)\b.+\bmean\b", question, re.IGNORECASE))
    material = (
        not concepts
        or (len(concepts) == 1 and concepts[0] in vague)
        or (len(concepts) <= 1 and (acronym or definitional))
    )
    broad = plan.intent == "evidence_search" and not plan.evidence_preferences
    ambiguity = "material" if material else "minor" if broad else "clear"
    focus = ", ".join(concepts) or "the unspecified research subject"
    objective = f"Identify and synthesize scientific evidence about {focus}, with emphasis on {plan.intent.replace('_', ' ')}."
    clarification = (
        "Which scientific subject, outcome, or relationship should the search investigate?"
        if material
        else ("Which outcome or aspect should receive priority?" if broad else None)
    )
    scope = tuple(plan.evidence_preferences) or ("all relevant scientific evidence types",)
    return QuestionBrief(
        original_question=question.strip(),
        interpreted_question=question.strip(),
        objective=objective,
        profile_id=plan.profile_id,
        intent=plan.intent,
        concepts=concepts,
        evidence_scope=scope,
        comparison_dimensions=plan.comparison_dimensions,
        assumptions=(),
        exclusions=(),
        ambiguity=ambiguity,
        clarification_question=clarification,
        method="deterministic_question_interpretation_v1",
    )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := " ".join(str(item).split())))
