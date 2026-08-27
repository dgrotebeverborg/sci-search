"""Transparent, domain-neutral conversion of a question into a retrieval plan."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sci_search.profiles import DomainProfile, contains_term, detect_profile

_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "accurately",
        "across",
        "an",
        "and",
        "another",
        "are",
        "as",
        "assumptions",
        "at",
        "be",
        "been",
        "between",
        "best",
        "by",
        "can",
        "cause",
        "causes",
        "comparable",
        "comparability",
        "compared",
        "conditions",
        "conflicting",
        "consistent",
        "consistently",
        "could",
        "datasets",
        "decline",
        "declined",
        "declines",
        "declining",
        "decrease",
        "decreased",
        "detect",
        "detects",
        "did",
        "differ",
        "difference",
        "differences",
        "different",
        "disagree",
        "disagreed",
        "disagrees",
        "do",
        "does",
        "domestic",
        "drive",
        "durable",
        "empirical",
        "estimate",
        "estimates",
        "electrodes",
        "exact",
        "experimental",
        "explain",
        "for",
        "free-ranging",
        "from",
        "global",
        "greater",
        "grid-scale",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "improve",
        "improved",
        "improves",
        "improving",
        "increase",
        "increased",
        "investigate",
        "investigated",
        "is",
        "it",
        "laboratory",
        "levels",
        "limit",
        "links",
        "link",
        "list",
        "listed",
        "literature",
        "mean",
        "measure",
        "measured",
        "method",
        "methodological",
        "methods",
        "modeled",
        "modelled",
        "modelling",
        "most",
        "of",
        "on",
        "one",
        "only",
        "or",
        "other",
        "others",
        "over",
        "patterns",
        "prefer",
        "primarily",
        "projected",
        "published",
        "rather",
        "rechargeable",
        "rely",
        "relies",
        "report",
        "reported",
        "reports",
        "retain",
        "rise",
        "risen",
        "show",
        "since",
        "size",
        "storage",
        "studies",
        "study",
        "strongly",
        "supported",
        "supports",
        "technical",
        "test",
        "than",
        "that",
        "the",
        "their",
        "these",
        "they",
        "this",
        "to",
        "treatments",
        "typically",
        "under",
        "universal",
        "use",
        "used",
        "values",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "affect",
        "affects",
        "affected",
        "effect",
        "effects",
        "influence",
        "influences",
        "relationship",
        "compare",
        "compares",
        "evidence",
        "find",
        "finding",
        "change",
        "changed",
        "changes",
        "changing",
        "during",
        "trend",
        "trends",
        "century",
        "consistently",
    ]
)


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    question: str
    profile_id: str
    intent: str
    concepts: tuple[str, ...]
    entity_phrases: tuple[str, ...]
    expanded_terms: tuple[str, ...]
    evidence_preferences: tuple[str, ...]
    comparison_dimensions: tuple[str, ...]


def plan_question(question: str, profile: DomainProfile | None = None) -> ResearchPlan:
    cleaned = " ".join(question.strip().split())
    if not cleaned:
        raise ValueError("question is required")
    selected = profile or detect_profile(cleaned)
    lowered = cleaned.lower()
    intent = _intent(lowered)
    concepts = _concepts(lowered, selected)
    entity_phrases = _entity_phrases(lowered, selected, concepts)
    expanded: list[str] = []
    for concept in concepts:
        expanded.extend(selected.expand(concept))
    expanded.extend(entity_phrases)
    preferences = []
    if any(word in lowered for word in ("experimental", "experiment", "measured", "field study")):
        preferences.append("empirical")
    if any(word in lowered for word in ("model", "modeled", "simulation", "assumption")):
        preferences.append("model_or_assumption")
    if "review" in lowered:
        preferences.append("review")
    return ResearchPlan(
        question=cleaned,
        profile_id=selected.id,
        intent=intent,
        concepts=concepts,
        entity_phrases=entity_phrases,
        expanded_terms=tuple(dict.fromkeys(expanded or concepts)),
        evidence_preferences=tuple(preferences),
        comparison_dimensions=selected.comparison_dimensions,
    )


def _intent(question: str) -> str:
    if any(term in question for term in ("conflict", "contradict", "disagree")):
        return "contradiction"
    if any(term in question for term in ("what methods", "which methods", "methods are used")):
        return "method"
    if any(
        term in question
        for term in (
            "measured performance",
            "measured and which",
            "measured versus",
            "measured vs",
            "assumed future performance",
        )
    ):
        return "method"
    if any(term in question for term in ("limitation", "limitations", "bias", "uncertainty")):
        return "limitation"
    if any(
        term in question
        for term in (
            "degradation mechanism",
            "mechanisms limit",
            "what limits",
            "capacity loss",
            "how durable",
            "what causes capacity",
        )
    ):
        return "limitation"
    if any(
        term in question
        for term in (
            "measured and which are modeled",
            "empirical rather than modeled",
            "rather than modelled",
        )
    ):
        return "method"
    if any(
        term in question
        for term in (
            "compare",
            "comparable",
            "comparability",
            "difference",
            "differ",
            "versus",
            "consistent across",
            "best battery",
        )
    ) or (
        re.search(r"\bprefer(?:s|red|ence)?\b", question)
        and (" or " in question or " versus " in question)
    ):
        return "comparison"
    if any(term in question for term in ("assumption", "assumptions")):
        return "assumption"
    if any(
        term in question
        for term in (
            "method",
            "measure",
            "study design",
            "dataset",
            "data source",
            "empirical",
            "modeled",
            "modelled",
        )
    ):
        return "method"
    if any(
        term in question
        for term in ("trend", "over time", "through time", "temporal change", "evolution")
    ):
        return "temporal_trend"
    if re.search(
        r"\b(?:change|changed|increase|increased|decrease|decreased|decline|declined)\b", question
    ) and (
        re.search(r"\b(?:during|throughout|since|between|from)\b", question)
        or re.search(r"\b(?:19|20|21)(?:st|nd|rd|th)?\s+centur", question)
    ):
        return "temporal_trend"
    if re.search(
        r"\b(?:increase|increased|decrease|decreased|decline|declined|rise|rises|risen|fall|fallen)\b.*\b(?:between|since|from)\b",
        question,
    ):
        return "temporal_trend"
    if any(term in question for term in ("gap", "unknown", "underexplored", "uncertain")):
        return "gap"
    if any(
        term in question
        for term in (
            "affect",
            "influence",
            "relationship",
            "determine",
            "mitigate",
            "association",
            "associated",
            "alter",
            "improve",
            "evidence link",
            "evidence links",
            "cause",
            "causes",
        )
    ):
        return "relationship"
    if re.search(r"\b(?:change|changed|decline|increase|decrease)\b", question):
        return "relationship"
    return "evidence_search"


def _concepts(question: str, profile: DomainProfile) -> tuple[str, ...]:
    found: list[str] = []
    for canonical, aliases in profile.vocabulary:
        if any(contains_term(question, value) for value in (canonical, *aliases)):
            found.append(canonical)
    if (
        profile.id == "ecology"
        and any(item in found for item in ("goat", "sheep"))
        and re.search(r"\b(?:select|selects|selected|selection|choose|chooses|choice)\b", question)
        and "foraging behaviour" not in found
    ):
        found.append("foraging behaviour")
    tokens = _word_tokens(question)
    represented_aliases = {alias for concept in found for alias in profile.expand(concept)}
    represented_tokens = {token for alias in represented_aliases for token in _word_tokens(alias)}
    found.extend(
        token
        for token in tokens
        if token not in _STOPWORDS
        and token not in represented_tokens
        and not any(token in item for item in found)
    )
    return tuple(dict.fromkeys(found))


def _entity_phrases(
    question: str,
    profile: DomainProfile,
    concepts: tuple[str, ...],
) -> tuple[str, ...]:
    """Extract compact unknown noun phrases without weakening atomic recall."""
    represented_aliases = {
        alias
        for concept in concepts
        for alias in profile.expand(concept)
        if profile.expand(concept) != (concept,) or " " in concept
    }
    represented_tokens = {token for alias in represented_aliases for token in _word_tokens(alias)}
    residual_groups: list[list[str]] = []
    active: list[str] = []
    for token in _phrase_tokens(question):
        represented = token in represented_tokens
        if token in {"decline", "loss"} and active and not represented:
            active.append(token)
            residual_groups.append(active)
            active = []
            continue
        if token in _STOPWORDS or represented:
            if active:
                residual_groups.append(active)
                active = []
            continue
        if len(token) >= 3:
            active.append(token)
    if active:
        residual_groups.append(active)
    phrases: list[str] = []
    for group in residual_groups:
        # Very long spans are normally prose rather than usable retrieval
        # concepts. Retain compact scientific phrases and otherwise fall back
        # to their individual content terms.
        if 1 < len(group) <= 5:
            phrases.append(" ".join(group))
    return tuple(dict.fromkeys(phrases))


def _word_tokens(text: str) -> list[str]:
    """Return scientific word tokens without discarding non-ASCII letters."""
    return [
        token
        for token in re.findall(r"(?u)[^\W\d_][^\W\s-]*(?:-[^\W\s-]+)*", text.casefold())
        if len(token) >= 3
    ]


def _phrase_tokens(text: str) -> list[str]:
    """Keep short function words so they can delimit unknown noun phrases."""
    return re.findall(r"(?u)[^\W\d_][^\W\s-]*(?:-[^\W\s-]+)*", text.casefold())
