"""Generic question-to-evidence investigation for domains without a specialist analyzer."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from sci_search.corpus import CorpusDocument
from sci_search.coverage import assess_answer_adequacy, decompose_question, evidence_context
from sci_search.evidence_lifecycle import validate_extractive_evidence
from sci_search.models import dataclass_to_dict
from sci_search.profiles import PROFILES, contains_term
from sci_search.question_planning import ResearchPlan, plan_question
from sci_search.retrieval import PassageIndex, RetrievedPassage


@dataclass(frozen=True, slots=True)
class GenericEvidenceRecord:
    id: str
    publication_id: str
    publication_title: str
    source_document: str
    statement: str
    passage: str
    section: str
    page: int | None
    passage_start: int
    passage_end: int
    evidence_type: str
    result_nature: str
    study_design: str
    matched_terms: tuple[str, ...]
    numerical_mentions: tuple[str, ...]
    retrieval_score: float
    locations: tuple[str, ...] = ()
    time_mentions: tuple[str, ...] = ()
    direction: str | None = None
    scope_dimension_ids: tuple[str, ...] = ()
    statement_dimension_ids: tuple[str, ...] = ()
    trend_evidence: bool = False
    statement_trend_signal: bool = False
    extraction_method: str = "extractive_scientific_evidence_v1"
    source_url: str | None = None
    doi: str | None = None
    validation_status: str = "unvalidated"
    review_state: str = "unreviewed"
    evidence_fingerprint: str = ""
    document_sha256: str = ""
    schema_version: str = "generic_evidence_v2"
    validator_version: str = "none"
    validation_checks: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class GenericFinding:
    id: str
    status: str
    statement: str
    qualification: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenericCoverage:
    publications_available: int
    publications_with_relevant_evidence: int
    full_texts_analyzed: int
    relevant_passages: int


@dataclass(frozen=True, slots=True)
class GenericInvestigation:
    mode: str
    session_id: str
    question: str
    plan: ResearchPlan
    answer_summary: str
    summary_evidence_ids: tuple[str, ...]
    coverage: GenericCoverage
    findings: tuple[GenericFinding, ...]
    evidence: tuple[GenericEvidenceRecord, ...]
    limitations: tuple[str, ...]
    follow_up_questions: tuple[str, ...]
    research_scope: dict[str, object]
    answer_adequacy: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return dataclass_to_dict(self)


class GenericResearchEngine:
    def __init__(
        self,
        documents: tuple[CorpusDocument, ...],
        *,
        lifecycle_lookup: Callable[[tuple[str, ...]], dict[str, dict[str, str]]] | None = None,
    ) -> None:
        self.documents = documents
        self.index = PassageIndex(documents)
        self.lifecycle_lookup = lifecycle_lookup

    def investigate(self, question: str, *, session_id: str | None = None) -> GenericInvestigation:
        plan = plan_question(question)
        research_scope = decompose_question(question, plan)
        # Trend evidence is often summarized in conclusion sections that rank
        # below dense method/figure passages in lexical retrieval. Inspect a
        # wider bounded pool before applying strict scope and diversity gates.
        retrieved = self.index.search(plan, limit=200 if plan.intent == "temporal_trend" else 80)
        evidence = _extract_evidence(retrieved, plan, self.documents, research_scope)
        required_scope_ids = {
            str(item["id"])
            for item in research_scope.get("dimensions", [])
            if item.get("required") and item.get("kind") in {"subject", "outcome"}
        }
        subject_ids = {item for item in required_scope_ids if item.startswith("subject:")}
        outcome_ids = {item for item in required_scope_ids if item.startswith("outcome:")}
        evidence = tuple(
            item
            for item in evidence
            if subject_ids <= set(item.scope_dimension_ids)
            and (not outcome_ids or bool(outcome_ids & set(item.scope_dimension_ids)))
        )
        if self.lifecycle_lookup is not None and evidence:
            states = self.lifecycle_lookup(tuple(item.id for item in evidence))
            evidence = tuple(
                replace(
                    item,
                    validation_status=states.get(item.id, {}).get(
                        "validation_status", item.validation_status
                    ),
                    review_state=states.get(item.id, {}).get("review_state", item.review_state),
                    schema_version=states.get(item.id, {}).get(
                        "schema_version", item.schema_version
                    ),
                    validator_version=states.get(item.id, {}).get(
                        "validator_version", item.validator_version
                    ),
                )
                for item in evidence
                if states.get(item.id, {}).get("review_state") != "rejected"
            )
        evidence = _apply_evidence_preferences(evidence, plan)
        evidence = _diverse_top(
            evidence,
            limit=24,
            per_publication=3,
            prefer_trends=research_scope.get("task") == "temporal_trend",
        )
        session = (
            session_id or "session:" + hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
        )
        adequacy = assess_answer_adequacy(dataclass_to_dict(evidence), research_scope)
        qualifying_ids = set(adequacy.get("qualifying_evidence_ids", []))
        answer_ids = set(adequacy.get("answer_evidence_ids", [])) or qualifying_ids
        evidence = tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.id not in qualifying_ids,
                    -item.retrieval_score,
                    item.publication_id,
                ),
            )
        )
        publications = {item.publication_id for item in evidence}
        findings = _findings(evidence, plan)
        coverage = GenericCoverage(
            len(self.documents), len(publications), len(self.documents), len(evidence)
        )
        answer_pool = tuple(item for item in evidence if item.id in answer_ids)
        summary_records = (
            _answer_records(answer_pool, plan, 3) if adequacy["can_answer_overall_question"] else ()
        )
        return GenericInvestigation(
            mode="generic_evidence",
            session_id=session,
            question=question.strip(),
            plan=plan,
            answer_summary=_summary(evidence, coverage, summary_records, adequacy, plan),
            summary_evidence_ids=tuple(item.id for item in summary_records),
            coverage=coverage,
            findings=findings,
            evidence=evidence,
            limitations=_limitations(evidence, coverage, adequacy),
            follow_up_questions=_follow_ups(plan),
            research_scope=research_scope,
            answer_adequacy=adequacy,
        )


def _extract_evidence(
    retrieved: tuple[RetrievedPassage, ...],
    plan: ResearchPlan,
    documents: tuple[CorpusDocument, ...],
    research_scope: dict[str, object],
) -> tuple[GenericEvidenceRecord, ...]:
    by_id = {item.publication.id: item for item in documents}
    records: list[GenericEvidenceRecord] = []
    for item in retrieved:
        if item.passage.section == "references":
            continue
        statement, statement_quality = _best_sentence(item.passage.text, plan)
        if not statement:
            continue
        document = by_id[item.publication_id]
        record_id = (
            "generic-evidence:"
            + hashlib.sha256(
                f"{item.publication_id}\x1f{item.passage.start}\x1f{statement}".encode()
            ).hexdigest()[:20]
        )
        numerical_mentions = tuple(
            dict.fromkeys(
                re.findall(
                    r"(?<!\w)[<>~≈]?\d+(?:\.\d+)?\s*(?:%|°C|km|m|h|days?|years?|kg|g)?",
                    statement,
                    re.IGNORECASE,
                )
            )
        )
        validation = validate_extractive_evidence(
            publication_id=item.publication_id,
            source_document=item.source_document,
            document_text=document.text,
            passage=item.passage.text,
            statement=statement,
            passage_start=item.passage.start,
            passage_end=item.passage.end,
            numerical_mentions=numerical_mentions,
            page=item.passage.page,
            extraction_method="extractive_scientific_evidence_v1",
        )
        context = evidence_context(f"{statement} {item.passage.text}", research_scope)
        statement_context = evidence_context(statement, research_scope)
        records.append(
            GenericEvidenceRecord(
                id=record_id,
                publication_id=item.publication_id,
                publication_title=item.publication_title,
                source_document=item.source_document,
                statement=statement,
                passage=item.passage.text,
                section=item.passage.section,
                page=item.passage.page,
                passage_start=item.passage.start,
                passage_end=item.passage.end,
                evidence_type=document.evidence_type.value,
                result_nature=document.result_nature.value,
                study_design=_study_design(item.passage.text, document.evidence_type.value),
                matched_terms=item.matched_terms,
                numerical_mentions=numerical_mentions,
                retrieval_score=round(item.score + statement_quality, 4),
                locations=context["locations"],
                time_mentions=context["time_mentions"],
                direction=statement_context["direction"],
                scope_dimension_ids=context["scope_dimension_ids"],
                statement_dimension_ids=statement_context["scope_dimension_ids"],
                trend_evidence=bool(context["trend_evidence"]),
                statement_trend_signal=bool(statement_context["trend_signal"]),
                source_url=document.publication.source_url or document.publication.access_url,
                doi=document.publication.doi,
                validation_status=validation.status,
                review_state=validation.review_state,
                evidence_fingerprint=validation.evidence_fingerprint,
                document_sha256=validation.document_sha256,
                schema_version=validation.schema_version,
                validator_version=validation.validator_version,
                validation_checks=tuple(
                    {
                        "name": check.name,
                        "passed": check.passed,
                        "detail": check.detail,
                        "severity": check.severity,
                    }
                    for check in validation.checks
                ),
            )
        )
    return tuple(records)


def _best_sentence(passage: str, plan: ResearchPlan) -> tuple[str, float]:
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", passage)
        if 35 <= len(item.strip()) <= 700
    ]
    if not sentences:
        return passage[:700].strip(), 0.0
    query_tokens = {
        token
        for term in plan.expanded_terms
        for token in re.findall(r"[a-z][a-z0-9-]+", term.lower())
    }

    def score(sentence: str) -> tuple[int, int]:
        lowered = sentence.lower()
        matches = sum(token in lowered for token in query_tokens)
        phrase_matches = sum(term in lowered for term in plan.expanded_terms if " " in term)
        concept_matches = _sentence_concept_matches(sentence, plan)
        result_cues = sum(
            cue in lowered
            for cue in (
                "found",
                "show",
                "observe",
                "associated",
                "increase",
                "decrease",
                "higher",
                "lower",
                "significant",
                "suggest",
                "prefer",
                "preference",
                "consumed",
                "selected",
                "avoided",
                "spent",
                "sensitivity",
                "specificity",
                "accuracy",
                "predictive value",
            )
        )
        relationship_cues = sum(
            cue in lowered
            for cue in (
                "in response to",
                "depended",
                "affected",
                "due to",
                "compared with",
                "in contrast",
                "whereas",
                "correlated",
            )
        )
        method_cues = sum(
            cue in lowered
            for cue in (
                "method",
                "observed",
                "measured",
                "sampling",
                "experiment",
                "gps",
                "sensor",
                "questionnaire",
            )
        )
        limitation_cues = sum(
            cue in lowered
            for cue in (
                "limitation",
                "however",
                "difficult",
                "uncertain",
                "bias",
                "confound",
                "lack of",
                "few studies",
            )
        )
        numerical_cues = min(3, len(re.findall(r"(?<!\w)[<>~≈]?\d+(?:\.\d+)?", sentence)))
        method_penalty = (
            0
            if plan.intent == "method"
            else sum(
                cue in lowered
                for cue in (
                    "database",
                    "searching",
                    "was assessed",
                    "was conducted",
                    "study was undertaken",
                    "were selected to",
                    "the purpose",
                    "the objective",
                    "to examine",
                    "to assess",
                    "was estimated",
                    "are presented in",
                    "were presented in",
                    "method",
                )
            )
        )
        caption_penalty = 45 if re.match(r"^(?:figure|fig\.?|table)\s*\d", lowered) else 0
        artifact_penalty = (
            60
            if any(
                cue in lowered
                for cue in (
                    "manuscript under review",
                    "discussion started:",
                    "author(s)",
                )
            )
            else 0
        )
        temporal_bonus = 0
        if plan.intent == "temporal_trend":
            direction = any(
                cue in lowered
                for cue in (
                    "increase",
                    "decrease",
                    "decline",
                    "rise",
                    "fall",
                    "remain",
                    "trend",
                    "change",
                )
            )
            period = bool(
                re.search(
                    r"\b(?:19|20)\d{2}\b|21st.century|end of the century|per degree|k\s*[−-]?1",
                    lowered,
                )
            )
            temporal_bonus = 20 * direction + 12 * period
        citation_penalty = max(0, len(re.findall(r"\[[^]]+\]", sentence)) - 2)
        malformed_penalty = 2 if not sentence[:1].isupper() else 0
        keyword_penalty = 4 if "keywords:" in lowered else 0
        relationship_bonus = relationship_cues * 8 if matches >= 2 else 0
        intent_bonus = (
            method_cues * 7
            if plan.intent == "method"
            else limitation_cues * 7
            if plan.intent == "limitation"
            else 0
        )
        diagnostic_bonus = 0
        if plan.intent == "comparison" and re.search(
            r"\b(?:accur|diagnos|detect)", plan.question.casefold()
        ):
            diagnostic_bonus = (
                140
                if (
                    re.search(
                        r"\b(?:sensitivity|specificity|predictive value|accuracy|area under (?:the )?curve|auc)\b",
                        lowered,
                    )
                    and re.search(r"\d+(?:\.\d+)?\s*%|0\.\d+", lowered)
                )
                else 0
            )
        value = (
            concept_matches * 25
            + matches * 2
            + phrase_matches * 6
            + result_cues * 5
            + numerical_cues * 8
            + relationship_bonus
            + intent_bonus
            + diagnostic_bonus
            + temporal_bonus
            - method_penalty * 10
            - caption_penalty
            - artifact_penalty
            - citation_penalty * 2
            - malformed_penalty * 4
            - keyword_penalty * 5
        )
        return value, -len(sentence)

    selected = max(sentences, key=score)
    return selected, float(score(selected)[0])


def _sentence_concept_matches(sentence: str, plan: ResearchPlan) -> int:
    profile = PROFILES[plan.profile_id]
    source_tokens = re.findall(r"[a-z][a-z0-9-]+", sentence.lower())
    hits = 0
    for concept in plan.concepts:
        if any(
            contains_term(sentence, alias)
            or all(
                any(
                    query_token == source_token
                    or (
                        min(len(query_token), len(source_token)) >= 4
                        and (
                            query_token.startswith(source_token)
                            or source_token.startswith(query_token)
                        )
                    )
                    for source_token in source_tokens
                )
                for query_token in re.findall(r"[a-z][a-z0-9-]+", alias.lower())
            )
            for alias in profile.expand(concept)
        ):
            hits += 1
    return hits


def _study_design(text: str, fallback: str) -> str:
    lowered = text.lower()
    cues = (
        ("field_experiment", ("field experiment", "field study", "grazing trial")),
        ("controlled_experiment", ("experiment", "treatment", "control group")),
        ("observational_study", ("observed", "observation", "survey")),
        ("simulation_or_model", ("simulation", "modelled", "modeled", "modeling")),
        ("review", ("review", "literature")),
    )
    return next(
        (label for label, terms in cues if any(term in lowered for term in terms)), fallback
    )


def _diverse_top(
    records: tuple[GenericEvidenceRecord, ...],
    *,
    limit: int,
    per_publication: int,
    prefer_trends: bool = False,
) -> tuple[GenericEvidenceRecord, ...]:
    selected: list[GenericEvidenceRecord] = []
    counts: dict[str, int] = {}
    seen_statements: set[tuple[str, str]] = set()
    for record in sorted(
        records,
        key=lambda item: (
            -len(item.scope_dimension_ids),
            -int(prefer_trends and item.trend_evidence),
            -(_section_signal(item.section) if prefer_trends else 0),
            -item.retrieval_score,
            item.publication_id,
            item.passage_start,
        ),
    ):
        normalized = re.sub(r"\W+", " ", record.statement.lower()).strip()
        statement_key = (record.publication_id, normalized)
        if (
            statement_key in seen_statements
            or counts.get(record.publication_id, 0) >= per_publication
        ):
            continue
        selected.append(record)
        seen_statements.add(statement_key)
        counts[record.publication_id] = counts.get(record.publication_id, 0) + 1
        if len(selected) == limit:
            break
    return tuple(selected)


def _apply_evidence_preferences(
    evidence: tuple[GenericEvidenceRecord, ...], plan: ResearchPlan
) -> tuple[GenericEvidenceRecord, ...]:
    if "empirical" in plan.evidence_preferences:
        empirical_types = {
            "laboratory_experiment",
            "field_experiment",
            "observational_study",
            "pilot_demonstration",
        }
        return tuple(
            item
            for item in evidence
            if item.evidence_type in empirical_types
            or "experiment" in item.study_design
            or "observational" in item.study_design
        )
    if "review" in plan.evidence_preferences:
        return tuple(
            item
            for item in evidence
            if item.evidence_type == "review" or item.study_design == "review"
        )
    if "model_or_assumption" in plan.evidence_preferences:
        return tuple(
            item
            for item in evidence
            if item.result_nature in {"modeled", "assumed"}
            or item.study_design == "simulation_or_model"
        )
    return evidence


def _findings(
    evidence: tuple[GenericEvidenceRecord, ...], plan: ResearchPlan
) -> tuple[GenericFinding, ...]:
    if not evidence:
        return (
            GenericFinding(
                "generic-finding:none",
                "insufficient_evidence",
                "No passage in the local corpus directly addressed the planned concepts.",
                "Broaden the corpus or revise the question; no answer has been inferred.",
                (),
            ),
        )
    findings: list[GenericFinding] = []
    for index, record in enumerate(_answer_records(evidence, plan, 5), start=1):
        findings.append(
            GenericFinding(
                id=f"generic-finding:{index}",
                status="source_reported",
                statement=record.statement,
                qualification=f"Extractive finding from a {record.study_design.replace('_', ' ')}; inspect the passage before treating it as a cross-study conclusion.",
                evidence_ids=(record.id,),
            )
        )
    return tuple(findings)


def _summary(
    evidence: tuple[GenericEvidenceRecord, ...],
    coverage: GenericCoverage,
    summary_records: tuple[GenericEvidenceRecord, ...],
    adequacy: dict[str, object],
    plan: ResearchPlan,
) -> str:
    if not evidence:
        return "The available full texts do not contain enough directly relevant evidence to answer this question. Sci-Search has not generated an unsupported answer."
    if not adequacy.get("can_answer_overall_question"):
        missing = (
            ", ".join(str(item) for item in adequacy.get("missing_requirements", []))
            or "adequate coverage of the complete question"
        )
        return (
            f"The acquired corpus contains {len(evidence)} topic-matched candidate passages across "
            f"{coverage.publications_with_relevant_evidence} publications, but it does not adequately answer the complete question. "
            f"Missing or insufficient coverage: {missing}. Sci-Search has withheld an overall conclusion rather than generalizing from narrower evidence."
        )
    empirical = sum(
        item.evidence_type in {"laboratory_experiment", "pilot_demonstration"}
        or "experiment" in item.study_design
        or "observational" in item.study_design
        for item in evidence
    )
    if plan.intent == "temporal_trend":
        observed = next(
            (item for item in summary_records if _temporal_nature(item) == "observed"), None
        )
        projected = next(
            (item for item in summary_records if _temporal_nature(item) == "projected"), None
        )
        parts = []
        if observed:
            parts.append("Observed-to-date evidence: " + _display_statement(observed.statement))
        if projected:
            parts.append("Future model evidence: " + _display_statement(projected.statement))
        used_ids = {item.id for item in (observed, projected) if item is not None}
        remaining = next((item for item in summary_records if item.id not in used_ids), None)
        if remaining:
            parts.append("Additional regional context: " + _display_statement(remaining.statement))
        return (
            f"Sci-Search found {len(evidence)} relevant evidence passages across {coverage.publications_with_relevant_evidence} of "
            f"{coverage.publications_available} available full texts. " + " ".join(parts) + " "
            "Observed and projected changes are reported separately because they are not directly comparable. "
            "These are source-grounded, retrieval-ranked findings rather than a causal meta-analysis."
        )
    patterns = "; ".join(_display_statement(record.statement) for record in summary_records)
    return (
        f"Sci-Search found {len(evidence)} relevant evidence passages across {coverage.publications_with_relevant_evidence} of "
        f"{coverage.publications_available} available full texts. {empirical} selected passages appear empirical. "
        f"The strongest source-reported patterns are: {patterns} "
        "These are retrieval-ranked findings, not yet a causal meta-analysis."
    )


def _limitations(
    evidence: tuple[GenericEvidenceRecord, ...],
    coverage: GenericCoverage,
    adequacy: dict[str, object],
) -> tuple[str, ...]:
    items = [
        "Generic-mode findings are extractive and retrieval-ranked; they are not an LLM-generated literature synthesis or meta-analysis."
    ]
    if coverage.publications_with_relevant_evidence < 3:
        items.append(
            "Fewer than three publications contributed relevant passages, so cross-study conclusions would be premature."
        )
    if evidence and all(item.study_design in {"review", "reported"} for item in evidence):
        items.append(
            "The selected evidence is secondary or insufficiently classified; inspect original studies before drawing conclusions."
        )
    if not adequacy.get("can_answer_overall_question"):
        items.append(
            "An overall answer was withheld because required question dimensions were not adequately covered: "
            + ", ".join(str(item) for item in adequacy.get("missing_requirements", []))
            + "."
        )
    items.append(
        "Absence from this local corpus is not evidence that a finding is absent from the wider literature."
    )
    return tuple(items)


def _follow_ups(plan: ResearchPlan) -> tuple[str, ...]:
    concepts = " and ".join(plan.concepts[:2]) or "this topic"
    return (
        f"Show only empirical evidence about {concepts}.",
        f"Compare the study methods used to investigate {concepts}.",
        f"What limitations and uncertainties are reported for {concepts}?",
        f"Which conditions could explain differences in findings about {concepts}?",
    )


def _distinct_publications(
    evidence: tuple[GenericEvidenceRecord, ...], limit: int
) -> tuple[GenericEvidenceRecord, ...]:
    selected: list[GenericEvidenceRecord] = []
    seen: set[str] = set()
    for item in evidence:
        if item.publication_id in seen:
            continue
        selected.append(item)
        seen.add(item.publication_id)
        if len(selected) == limit:
            break
    return tuple(selected)


def _answer_records(
    evidence: tuple[GenericEvidenceRecord, ...], plan: ResearchPlan, limit: int
) -> tuple[GenericEvidenceRecord, ...]:
    explanatory_only = False
    if plan.intent == "method":
        method_markers = re.compile(
            r"\b(?:method|measur|sampling|observ(?:e|ed|ation)|gps|sensor|questionnaire|metabarcod|microhistolog|tracking)\b",
            re.IGNORECASE,
        )
        limitation_markers = re.compile(
            r"\b(?:limitation|bias|uncertain|constraint|drawback|underestimat|overestimat|resolution|accuracy|cannot|however)\b",
            re.IGNORECASE,
        )
        preferred = tuple(item for item in evidence if method_markers.search(item.statement))
        if "limitation" in plan.question.casefold():
            limitations = tuple(
                item for item in preferred if limitation_markers.search(item.statement)
            )
            if limitations:
                preferred = limitations
        return _distinct_publications(preferred or evidence, limit)
    method_markers = (
        "this study aims",
        "the aim of",
        "the objective",
        "was conducted to",
        "were conducted to",
        "was evaluated",
        "were evaluated",
        "was undertaken",
        "we investigated",
        "to evaluate the effects",
    )
    preferred = tuple(
        item
        for item in evidence
        if not any(marker in item.statement.lower() for marker in method_markers)
    )
    if re.search(r"^\s*why\b|\bwhat explains?\b", plan.question.casefold()):
        explanatory = tuple(
            item
            for item in preferred
            if re.search(
                r"\b(?:because|due to|driven by|explained by|attribut(?:e|ed|able) to|depend(?:s|ed|ing)? on|heterogen|var(?:y|ies|ied) (?:with|by|across|among))\b",
                item.statement.casefold(),
            )
        )
        if explanatory:
            preferred = explanatory
            robust = tuple(
                item for item in explanatory if _explanatory_signal(item.statement, plan) >= 3
            )
            if len({item.publication_id for item in robust}) >= 2:
                preferred = robust
                explanatory_only = True
    # Passage retrieval may find every concept across a surrounding paragraph while
    # the selected sentence itself discusses only a side topic.  Lead with sentences
    # that directly name the largest share of the planned concepts; retrieval score
    # remains the tie-breaker.  The passage is still retained for full context.
    preferred = tuple(
        sorted(
            preferred,
            key=lambda item: (
                _explanatory_signal(item.statement, plan),
                _quantitative_signal(item.statement, plan),
                int(plan.intent == "temporal_trend" and bool(item.direction)),
                int(plan.intent == "temporal_trend" and item.statement_trend_signal),
                _temporal_specificity(item) if plan.intent == "temporal_trend" else 0,
                _section_signal(item.section),
                _statement_concept_coverage(item.statement, plan),
                item.retrieval_score,
            ),
            reverse=True,
        )
    )
    quantitative = tuple(
        item for item in preferred if _quantitative_signal(item.statement, plan) > 0
    )
    if len({item.publication_id for item in quantitative}) >= 2:
        preferred = quantitative
    if plan.intent == "temporal_trend":
        selected: list[GenericEvidenceRecord] = []
        seen: set[str] = set()
        for nature in ("observed", "projected"):
            match = next(
                (
                    item
                    for item in preferred
                    if item.publication_id not in seen and _temporal_nature(item) == nature
                ),
                None,
            )
            if match is not None:
                selected.append(match)
                seen.add(match.publication_id)
        for item in preferred:
            if item.publication_id in seen:
                continue
            selected.append(item)
            seen.add(item.publication_id)
            if len(selected) == limit:
                break
        return tuple(selected[:limit])
    direct_only = False
    if plan.intent == "relationship" and preferred:
        # If at least one sentence explicitly contains every side of the asked
        # relationship, do not dilute the answer with sentences whose relevance
        # exists only in their surrounding passage.
        direct = tuple(
            item
            for item in preferred
            if _statement_concept_coverage(item.statement, plan) == len(plan.concepts)
        )
        if direct:
            preferred = direct
            direct_only = True
    selected = list(_distinct_publications(preferred, limit))
    seen = {item.publication_id for item in selected}
    if len(selected) < limit and not direct_only and not explanatory_only:
        for item in evidence:
            if item.publication_id in seen:
                continue
            selected.append(item)
            seen.add(item.publication_id)
            if len(selected) == limit:
                break
    return tuple(selected)


def _statement_concept_coverage(statement: str, plan: ResearchPlan) -> int:
    profile = PROFILES[plan.profile_id]
    return sum(
        any(contains_term(statement, alias) for alias in profile.expand(concept))
        for concept in plan.concepts
    )


def _quantitative_signal(statement: str, plan: ResearchPlan) -> int:
    """Prefer result values over citation numbers for quantitative questions."""
    quantitative_question = any(
        marker in plan.question.lower()
        for marker in (
            "efficien",
            "cost",
            "density",
            "cycle life",
            "temperature",
            "current density",
            "range",
            "value",
        )
    )
    if not quantitative_question:
        return 0
    return 4 * len(re.findall(r"\d+(?:\.\d+)?\s*%", statement)) + 2 * len(
        re.findall(r"\d+(?:\.\d+)?\s*(?:°C|K|Wh|kWh|MW|GW|A\s*cm)", statement, re.IGNORECASE)
    )


def _explanatory_signal(statement: str, plan: ResearchPlan) -> int:
    if not re.search(r"^\s*why\b|\bwhat explains?\b", plan.question.casefold()):
        return 0
    lowered = statement.casefold()
    moderators = (
        "soil",
        "climate",
        "crop",
        "feedstock",
        "pyrolysis",
        "application rate",
        "application method",
        "fertilizer",
        "biochar properties",
        "duration",
        "time",
    )
    cross_study = (
        3
        if re.search(
            r"\b(?:studies|heterogen|inconsistent|vary|varies|varied|differences)\b", lowered
        )
        else 0
    )
    artifact_penalty = 4 if re.search(r"\b(?:conclusion|keywords|abstract)\b", lowered) else 0
    return cross_study + sum(term in lowered for term in moderators) - artifact_penalty


def _section_signal(section: str) -> int:
    """Prefer author synthesis over captions and method-dense passages."""
    normalized = section.casefold().replace(" ", "_")
    if "conclusion" in normalized:
        return 4
    if "result" in normalized:
        return 3
    if "discussion" in normalized:
        return 2
    if "abstract" in normalized:
        return 1
    return 0


def _temporal_nature(record: GenericEvidenceRecord) -> str:
    text = _normalized_statement(record.statement)
    if re.search(
        r"\bfuture\b|\bproject(?:ed|ion|ions)?\b|\bssp\d|\brcp\d|\b20(?:7\d|8\d|9\d)\b|end of (?:the )?century",
        text,
    ) or (record.study_design == "simulation_or_model" and "21st century" in text):
        return "projected"
    years = _noncitation_years(text)
    if re.search(r"\bobserv(?:e|ed|ation|ations)\b|\brecent\b|\bhistorical\b|\bsince\b", text) or (
        len(years) >= 2 and years[-1] - years[0] >= 5
    ):
        return "observed"
    return "other"


def _temporal_specificity(record: GenericEvidenceRecord) -> int:
    text = _normalized_statement(record.statement)
    years = _noncitation_years(text)
    if len(years) >= 2 and years[-1] - years[0] >= 5:
        return 3
    if re.search(
        r"\b21st[- ‐‑‒–—]century\b|\b(?:future|projected|observed|recent|historical|since)\b", text
    ):
        return 2
    return 0


def _normalized_statement(statement: str) -> str:
    return " ".join(re.sub(r"(?<=\w)-\s+(?=\w)", "", statement.casefold()).split())


def _noncitation_years(text: str) -> list[int]:
    without_parentheses = re.sub(r"\([^)]*\)", " ", text)
    return sorted({int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", without_parentheses)})


def _display_statement(statement: str) -> str:
    """Make PDF line wrapping readable without changing the stored quotation."""
    rendered = re.sub(r"(?<=\w)-\s+(?=\w)", "", statement)
    rendered = " ".join(rendered.split()).rstrip(" ;")
    line_numbers = [int(value) for value in re.findall(r"(?<=\s)(\d{3})(?=\s+[A-Za-z])", rendered)]
    clustered = {
        value
        for value in line_numbers
        if any(other != value and abs(other - value) <= 10 for other in line_numbers)
    }
    if len(clustered) >= 2:
        rendered = re.sub(
            r"(?<=\s)(\d{3})(?=\s+[A-Za-z])",
            lambda match: "" if int(match.group(1)) in clustered else match.group(1),
            rendered,
        )
        rendered = " ".join(rendered.split())
    if rendered.endswith("-"):
        rendered = rendered[:-1].rstrip() + " …"
    return rendered
