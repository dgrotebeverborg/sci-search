"""Structured, inspectable interpretation of a research question before search."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from sci_search.data_research.strategy import PROMPT as STRATEGY_PROMPT
from sci_search.data_research.strategy import SCHEMA as STRATEGY_SCHEMA
from sci_search.data_research.strategy import validate_strategy
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.model_provider import configured_analyzer
from sci_search.question_choices import option_briefs, option_schema
from sci_search.question_planning import (
    EVIDENCE_PREFERENCES,
    RESEARCH_INTENTS,
    ResearchPlan,
    plan_from_brief,
    plan_question,
)


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
    research_plan: dict[str, Any] | None = None
    data_research: dict[str, Any] | None = None
    # The model's raw options and clarification answers; validated by interpret_question.
    proposals: dict[str, Any] | None = None

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
        "research_plan",
    ],
    "properties": {
        "research_strategy": STRATEGY_SCHEMA,
        "research_plan": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "intent",
                "subject_terms",
                "driver_terms",
                "geography_terms",
                "evidence_preferences",
                "exclusion_terms",
                "relationship_type",
                "population_terms",
                "time_terms",
                "outcome_measure_terms",
            ],
            "properties": {
                "intent": {"type": "string", "enum": list(RESEARCH_INTENTS)},
                "relationship_type": {
                    "type": "string",
                    "enum": ["association", "influence", "unspecified"],
                },
                **{
                    key: {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1, "maxLength": 150},
                    }
                    for key in (
                        "subject_terms",
                        "driver_terms",
                        "geography_terms",
                        "exclusion_terms",
                        "population_terms",
                        "time_terms",
                        "outcome_measure_terms",
                    )
                },
                "evidence_preferences": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {"type": "string", "enum": list(EVIDENCE_PREFERENCES)},
                },
            },
        },
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
        "clarification_options": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
        },
    },
}
QUESTION_BRIEF_SCHEMA["properties"]["options"] = {
    "type": "array",
    "maxItems": 4,
    "items": option_schema(QUESTION_BRIEF_SCHEMA["properties"]["research_plan"]),
}


def interpret_question(
    question: str,
    analyzer: MistralAnalyzer | None = None,
    *,
    steer: dict[str, Any] | None = None,
    clarification: str | None = None,
) -> dict[str, Any]:
    """The brief with clickable ``options`` and ``clarification_options`` for the researcher."""
    brief = _interpretation(question, analyzer, steer=steer, clarification=clarification)
    raw = brief.pop("proposals", None) or {}
    raw_options, answers = raw.get("options"), raw.get("clarification_options")
    return {
        **brief,
        "options": option_briefs(question, brief, raw_options),
        "clarification_options": [
            " ".join(str(a).split())[:120] for a in answers or [] if str(a).strip()
        ][:4],
    }


def _interpretation(question, analyzer, *, steer, clarification) -> dict[str, Any]:
    plan = plan_question(question)
    from sci_search.data_research.wildfire import propose

    selected = analyzer if analyzer is not None else configured_analyzer()
    data_scope = propose(question)
    if data_scope and selected is None:
        base = _deterministic_brief(question, plan)
        return replace(
            base,
            interpreted_question="How have reported forest-fire counts and burned area changed in the selected European countries?",
            objective="Analyse official annual data, show counts and km² separately, and disclose coverage gaps.",
            ambiguity="clear",
            clarification_question=None,
            assumptions=(
                f"Requested interval: {data_scope['start_year']}–{data_scope['end_year']}. The current calendar year is incomplete.",
                "Country-reported forest-fire statistics; not satellite fire detections.",
                "The source edition currently ends in 2024; missing countries or years are not zero.",
            ),
            evidence_scope=(
                "Official EFFIS country totals; fixed-country descriptive comparison. Literature explanations are not part of this data run.",
            ),
            method="curated_data_research_plan_v1",
            data_research=data_scope,
        ).to_dict()
    if selected is not None:
        try:
            try:
                result = _model_interpretation(
                    question, plan, selected, steer=steer, clarification=clarification
                )
            except ValueError as error:
                if selected.provider.name != "codex":
                    raise
                result = _model_interpretation(
                    question,
                    plan,
                    selected,
                    validation_feedback=str(error)[:500],
                    steer=steer,
                    clarification=clarification,
                )
            return result.to_dict()
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            from sci_search.codex_provider import CodexRequestError

            # A failed model response is not approval of a different, inferred plan.
            return replace(
                _deterministic_brief(question, plan),
                ambiguity="material",
                clarification_question=str(exc)
                if isinstance(exc, CodexRequestError)
                else (
                    "The question interpretation could not be validated. "
                    "Please review the question and try again before starting the search."
                ),
            ).to_dict()
    return _deterministic_brief(question, plan).to_dict()


def _model_interpretation(
    question: str,
    plan: ResearchPlan,
    analyzer: MistralAnalyzer,
    *,
    validation_feedback: str | None = None,
    steer: dict[str, Any] | None = None,
    clarification: str | None = None,
) -> QuestionBrief:
    body = {
        "model": analyzer.model,
        "temperature": 0,
        "max_tokens": 2000,
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
                    "You translate a researcher's question into a faithful research brief before research. "
                    "Do not answer the scientific question. Do not add facts. Preserve the user's subject and outcome. "
                    "Do not narrow the population, setting, study type, or outcome unless the user explicitly did so; "
                    "default to no exclusions. Surface only unavoidable assumptions or explicit exclusions that materially affect retrieval. Mark ambiguity material only "
                    "when different reasonable interpretations would produce substantially different corpora. Ask at most "
                    "one specific clarification question. Return the requested JSON only."
                    " Also return options: 2 to 4 distinct versions of the question the researcher may "
                    "mean, each with a short title, a one-sentence summary, its own interpreted_question, "
                    "objective, research_plan and research_strategy. Mark exactly the version closest "
                    "to the literal question with closest true. When published datasets, including "
                    "model projections, could answer part of the question, include a data or both "
                    "version with concrete measurements. For each version give alternatives the "
                    "researcher can click: routes, measurement sets, geographies (with ISO alpha-3 "
                    "countries only when certain) and periods. When steer is given, propose new "
                    "versions moved in that direction from steer.option. When clarification_answer "
                    "is given, it answers your earlier clarification question; use it. When ambiguity "
                    "is material, give clarification_options: 2 to 4 short answers to your "
                    "clarification question."
                    " The research_plan is executable: identify compact noun phrases for the subject/outcome being explained, "
                    "separate possible drivers, and list ONLY explicitly requested geography and exclusions. "
                    "A question about drivers of evolution is relationship, not automatically temporal_trend. "
                    "When numerical trends AND associated factors are requested, use intent relationship. "
                    "If relationship_type is association or influence, intent MUST be relationship "
                    "and subject_terms and driver_terms must be distinct and nonempty. "
                    "The supplied deterministic plan is a fallible suggestion; correct it when necessary. "
                    "For comparisons keep the compared entities as subjects. Do not split compound subjects into isolated words. "
                    "Use exclusion_terms only for explicit excluded subject phrases (not prose instructions). "
                    "Use evidence_preferences only for study types explicitly requested by the user. "
                    "For an unrestricted question return an empty array []; do not enumerate all categories "
                    "because that would exclude unclassified studies. Do not invent restrictions."
                    " Evidence preferences support only empirical, review, and model_or_assumption, "
                    "combined as alternatives. If an explicit narrower restriction cannot be represented "
                    "(for example randomized trials only), mark ambiguity material and ask for clarification "
                    "rather than silently broadening it."
                    " For relationship questions, subject_terms contains ONLY the outcome or response being studied; "
                    "driver_terms contains ONLY the exposure, intervention or possible explanatory factors. "
                    "Never put both the exposure and outcome under subject_terms. Relationship questions must "
                    "have both roles; if their roles cannot be determined, mark ambiguity material and ask. "
                    "Set relationship_type to association for associations/correlations, influence for explicit "
                    "effects or explanatory drivers, and unspecified for non-relationship tasks. Association "
                    "does not imply causation. Use neutral outcome terms: a proposed lower risk is a hypothesis, "
                    "not a filter excluding null or opposite findings. For example, in 'Is neighborhood green "
                    "space associated with lower risk of type 2 diabetes?', driver_terms is ['neighborhood green space'], "
                    "subject_terms is ['type 2 diabetes'], and relationship_type is association. "
                    "Preserve the requested measurement separately in outcome_measure_terms, for example ['risk'] "
                    "for this diabetes question, ['cost'] for costs, or [] when no separate measurement is specified. "
                    "Distinguish background motivation or asserted benefits from the uncertainty the user wants investigated. "
                    "Only requested research outcomes belong in outcome_measure_terms; do not turn a contextual "
                    "benefit into an additional mandatory outcome or invent a question about measuring it. "
                    "Do not infer a measurement from the topic alone: a diabetes question without risk, incidence, "
                    "or another named measure must use []. "
                    "Do not encode a hypothesized direction (lower/higher) as an outcome_measure_terms filter. "
                    "population_terms names ONLY explicitly requested people or study units; time_terms names ONLY "
                    "explicitly requested study periods. Leave both arrays empty when unspecified. "
                    "Places belong only in geography_terms: write subject_terms without them, for "
                    "example ['insect biomass'] rather than ['insect biomass in Germany']. "
                    "evidence_scope must describe studies that measure or compare the factor and outcome, "
                    "not repeat the topic keywords, and must allow supportive, null and opposing results."
                    + STRATEGY_PROMPT
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        **({"steer": steer} if steer else {}),
                        **({"clarification_answer": clarification} if clarification else {}),
                        **(
                            {
                                "previous_validation_error": validation_feedback,
                                "repair_instruction": "Correct the invalid plan while preserving the original question's scope. Do not weaken evidence requirements.",
                            }
                            if validation_feedback
                            else {}
                        ),
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
    structure = payload.get("research_plan")
    if ambiguity != "material":
        if not isinstance(structure, dict):
            raise ValueError("Question interpretation omitted its executable plan")
        plan = plan_from_brief(
            question, {"original_question": question, "research_plan": structure}
        )
        if plan.intent == "relationship" and not plan.driver_terms:
            raise ValueError("Relationship interpretation omitted the factor")
    return QuestionBrief(
        original_question=question.strip(),
        interpreted_question=interpreted,
        objective=objective,
        profile_id=plan.profile_id,
        intent=plan.intent,
        concepts=plan.concepts,
        evidence_scope=_evidence_to_seek(plan)
        if structure and ambiguity != "material"
        else _strings(payload.get("evidence_scope")),
        comparison_dimensions=plan.comparison_dimensions,
        assumptions=_strings(payload.get("assumptions")),
        exclusions=_strings(payload.get("exclusions")),
        ambiguity=ambiguity,
        clarification_question=clarification,
        method=f"{analyzer.provider.name}_structured_question_interpretation_v1",
        provider=analyzer.provider.name,
        model=analyzer.model,
        research_plan=structure,
        data_research=validate_strategy(payload["research_strategy"], infer_route=True)
        if payload.get("research_strategy")
        else None,
        proposals={
            "options": payload.get("options"),
            "clarification_options": payload.get("clarification_options"),
        },
    )


def _deterministic_brief(question: str, plan: ResearchPlan) -> QuestionBrief:
    vague = {"it", "this", "these", "they", "something", "things"}
    concepts = tuple(plan.concepts)
    acronym = plan.profile_id == "generic" and bool(re.search(r"\b[A-Z]{2,5}\b", question))
    definitional = bool(re.search(r"\bwhat (?:does|is)\b.+\bmean\b", question, re.IGNORECASE))
    unresolved_reference = bool(
        re.match(
            r"^(?:(?:does|do|can|could|will|would)\s+(?:it|this|that|these|they)\s+"
            r"(?:help|work|affect|improve|reduce|increase|cause|matter)\b|"
            r"(?:is|are)\s+(?:it|this|that|these|they)\s+(?:effective|useful|beneficial)\b)",
            question.strip(),
            re.I,
        )
    )
    material = (
        unresolved_reference
        or not concepts
        or (len(concepts) == 1 and concepts[0] in vague)
        or (len(concepts) <= 1 and (acronym or definitional))
    )
    unresolved_association = bool(re.search(r"\b(?:associated with|correlat\w*)\b", question, re.I))
    material = material or unresolved_association
    broad = plan.intent == "evidence_search" and not plan.evidence_preferences
    ambiguity = "material" if material else "minor" if broad else "clear"
    focus = ", ".join(concepts) or "the unspecified research subject"
    objective = f"Identify and synthesize scientific evidence about {focus}, with emphasis on {plan.intent.replace('_', ' ')}."
    clarification = (
        "Which factor and outcome should be studied? Their roles could not be identified reliably."
        if unresolved_association
        else "Which scientific subject, outcome, or relationship should the search investigate?"
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


def _evidence_to_seek(plan: ResearchPlan) -> tuple[str, ...]:
    outcome = ", ".join(plan.subject_terms)
    if plan.outcome_measure_terms:
        outcome += " (" + ", ".join(plan.outcome_measure_terms) + ")"
    if plan.intent == "relationship" and plan.driver_terms:
        factors = ", ".join(plan.driver_terms)
        return (
            f"Studies examining {outcome} in relation to {factors}.",
            "Include findings of an association, no association, or an association in the opposite direction."
            if plan.relationship_type == "association"
            else "Include evidence supporting, challenging, or finding no effect of the proposed factors.",
        )
    return (f"Scientific studies addressing {outcome}.",)
