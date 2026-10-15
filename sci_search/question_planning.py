"""Transparent, domain-neutral conversion of a question into a retrieval plan."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from sci_search.profiles import GENERIC_PROFILE, DomainProfile, contains_term, detect_profile

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
    subject_terms: tuple[str, ...] = ()
    driver_terms: tuple[str, ...] = ()
    geography_terms: tuple[str, ...] = ()
    exclusion_terms: tuple[str, ...] = ()
    interpretation_method: str = "deterministic"
    relationship_type: str = "unspecified"
    population_terms: tuple[str, ...] = ()
    time_terms: tuple[str, ...] | None = None
    outcome_measure_terms: tuple[str, ...] | None = None


RESEARCH_INTENTS = (
    "relationship",
    "comparison",
    "contradiction",
    "temporal_trend",
    "method",
    "limitation",
    "assumption",
    "gap",
    "evidence_search",
)


EVIDENCE_PREFERENCES = ("empirical", "review", "model_or_assumption")


def plan_from_brief(question: str, brief: dict[str, Any] | None) -> ResearchPlan:
    """Validate and execute the confirmed brief, with a legacy fallback.

    Explicit parameters keep concurrent requests and saved-run rebuilds isolated.
    """
    base = plan_question(question)
    if not brief:
        return base
    if brief.get("ambiguity") == "material":
        raise ValueError("Clarify the research question before starting the review")
    if " ".join(str(brief.get("original_question", "")).split()) != base.question:
        raise ValueError("The confirmed brief belongs to a different question")
    data_strategy = brief.get("data_research")
    if data_strategy:
        if data_strategy.get("adapter") == "discovered_data_v1":
            from sci_search.data_research.strategy import validate_strategy

            validate_strategy(data_strategy)
        elif data_strategy.get("adapter") == "effis_reported_fires_v1":
            from sci_search.data_research.wildfire import validate_scope

            validate_scope(data_strategy)
        else:
            raise ValueError("Unsupported data research strategy")
    structure = brief.get("research_plan")
    if structure is None:
        return base
    if not isinstance(structure, dict) or structure.get("intent") not in RESEARCH_INTENTS:
        raise ValueError("Invalid confirmed research intent")

    def terms(key: str, *, required: bool = False) -> tuple[str, ...]:
        values = structure.get(
            key, [] if key in {"population_terms", "time_terms", "outcome_measure_terms"} else None
        )
        if not isinstance(values, (list, tuple)) or len(values) > 12:
            raise ValueError(f"Invalid confirmed {key}")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in values):
            raise ValueError(f"Invalid confirmed {key}")
        result = tuple(dict.fromkeys(" ".join(v.casefold().split()) for v in values))
        if required and not result:
            raise ValueError(f"Confirmed {key} is required")
        return result

    geography = terms("geography_terms")
    subjects = _without_places(terms("subject_terms", required=True), geography)
    drivers = terms("driver_terms")
    relationship = structure.get("relationship_type", "unspecified")
    if relationship not in {"association", "influence", "unspecified"}:
        raise ValueError("Invalid relationship type")
    if relationship != "unspecified":
        if structure["intent"] != "relationship" or not drivers:
            raise ValueError("A relationship needs a separate factor and outcome")
        if set(subjects) & set(drivers):
            raise ValueError("The factor and outcome must be distinct")
    population = terms("population_terms")
    period = terms("time_terms")
    measures = terms("outcome_measure_terms")
    preferences = terms("evidence_preferences")
    if any(value not in EVIDENCE_PREFERENCES for value in preferences):
        raise ValueError("Unsupported evidence filter in the confirmed research plan")
    concepts = tuple(
        dict.fromkeys((*subjects, *geography, *drivers, *measures, *population, *period))
    )
    return replace(
        base,
        intent=structure["intent"],
        concepts=concepts,
        entity_phrases=tuple(term for term in concepts if " " in term),
        expanded_terms=tuple(
            dict.fromkeys(
                alias for term in concepts for alias in detect_profile(question).expand(term)
            )
        ),
        subject_terms=subjects,
        driver_terms=drivers,
        geography_terms=geography,
        exclusion_terms=terms("exclusion_terms"),
        evidence_preferences=preferences,
        interpretation_method=str(brief.get("method") or "confirmed_structured_brief"),
        relationship_type=relationship,
        population_terms=population,
        time_terms=period if "time_terms" in structure else None,
        outcome_measure_terms=measures if "outcome_measure_terms" in structure else None,
    )


def _without_places(subjects: tuple[str, ...], places: tuple[str, ...]) -> tuple[str, ...]:
    """Subjects without a requested place: "insect biomass in germany" becomes "insect biomass".

    The place remains a separate part of the plan, so a study of one place can be found and
    screened on the subject itself.
    """
    if not places:
        return subjects
    names = "|".join(re.escape(place) for place in sorted(places, key=len, reverse=True))
    suffix = re.compile(rf"\s+(?:in|across|for|from)\s+(?:the\s+)?(?:{names})$")
    return tuple(dict.fromkeys(suffix.sub("", subject) or subject for subject in subjects))


def plan_focus(plan: ResearchPlan) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    if plan.subject_terms:
        return " ".join(plan.subject_terms), plan.driver_terms, plan.geography_terms
    return explanatory_focus(plan.question) if plan.profile_id == "generic" else None


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
    if explanatory_focus(question):
        return "relationship"
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
    focus = explanatory_focus(question) if profile.id == "generic" else None
    if focus:
        subject, drivers, scope = focus
        return tuple(dict.fromkeys((subject, *scope, *drivers)))
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


def explanatory_focus(question: str) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """Keep outcome, drivers and scope distinct in explicit 'role of X in Y' questions.

    This deliberately recognizes an explicit grammatical construction, rather
    than guessing the subject from the first content word of arbitrary prose.
    """
    cleaned = " ".join(question.casefold().strip().rstrip("?").split())
    if re.search(r"\b(?:compar\w*|versus|vs|contradict\w*|disagree\w*)\b", cleaned):
        return None
    prefixes = (
        r"(?:what is |what's )?(?:the )?role of (?P<drivers>.+?) in ",
        r"what role (?:do|does) (?P<drivers>.+?) play in ",
        r"how (?:do|does) (?P<drivers>.+?) (?:influence|affect|shape) ",
    )
    target = r"(?:the )?(?:(?:evolution|development|formation|emergence) of )?(?P<target>.+)"
    match = next((m for prefix in prefixes if (m := re.fullmatch(prefix + target, cleaned))), None)
    if not match:
        return None
    target_subject = re.sub(r"^(?:changes?|variation|differences?) in ", "", match["target"])
    parts = re.split(r"\s+(?:in|across|within|during|since)\s+", target_subject, maxsplit=1)
    subject = parts[0].strip().removeprefix("the ")
    # An unknown target in "how does X affect Y" may combine an organism,
    # an outcome and qualifiers rather than name one indivisible subject.
    # Keep ordinary concept/alias extraction unless the target is recognized
    # or the question explicitly groups explanatory drivers. Confirmed briefs
    # supply their own focus independently of this conservative fallback.
    recognized_subject = any(
        subject in (canonical, *aliases) for canonical, aliases in GENERIC_PROFILE.vocabulary
    )
    if (
        cleaned.startswith("how ")
        and not recognized_subject
        and not re.search(r"\b(?:and|or|factors?)\b|,", match["drivers"])
    ):
        return None
    drivers = tuple(
        dict.fromkeys(
            phrase
            for group in re.split(r"\s+(?:and|or)\s+|,\s*", match["drivers"])
            if (
                phrase := " ".join(
                    token
                    for token in _phrase_tokens(group)
                    if token not in {"the", "factor", "factors"}
                )
            )
        )
    )
    if not subject or not drivers or subject in {"change", "changes", "variation", "differences"}:
        return None
    scope = (parts[1].strip().rstrip("?"),) if len(parts) == 2 else ()
    return subject, drivers, scope


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
