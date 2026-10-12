"""Question decomposition, study-evidence context, and answer-adequacy checks."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from sci_search.concept_matching import concept_present
from sci_search.discovery import SearchQuery
from sci_search.profiles import PROFILES
from sci_search.question_planning import ResearchPlan, plan_focus

_EUROPE = (
    "europe",
    "european",
    "albania",
    "austria",
    "belgium",
    "bosnia",
    "bulgaria",
    "croatia",
    "cyprus",
    "czech",
    "denmark",
    "estonia",
    "finland",
    "france",
    "germany",
    "greece",
    "hungary",
    "iceland",
    "ireland",
    "italy",
    "latvia",
    "lithuania",
    "luxembourg",
    "mediterranean",
    "moldova",
    "montenegro",
    "netherlands",
    "north macedonia",
    "norway",
    "poland",
    "portugal",
    "romania",
    "serbia",
    "slovakia",
    "slovenia",
    "spain",
    "sweden",
    "switzerland",
    "ukraine",
    "united kingdom",
    "britain",
)
_LOCATIONS: dict[str, tuple[str, ...]] = {
    "europe": _EUROPE,
    "africa": ("africa", "african"),
    "asia": ("asia", "asian"),
    "north america": ("north america", "canada", "united states", "usa", "mexico"),
    "south america": (
        "south america",
        "south american",
        "brazil",
        "argentina",
        "chile",
        "uruguay",
        "paraguay",
        "bolivia",
        "peru",
        "ecuador",
        "colombia",
        "venezuela",
        "guyana",
        "suriname",
        "french guiana",
        "amazonian",
        "amazonia",
    ),
    "australia": ("australia", "australian"),
    "global": ("global", "worldwide", "world"),
    "antarctica": ("antarctica", "antarctic"),
}
_OUTCOME_ALIASES: dict[str, tuple[str, ...]] = {
    "number": ("number", "frequency", "count", "occurrence", "incidence", "events", "fires"),
    "extent": (
        "extent",
        "burned area",
        "burnt area",
        "area burned",
        "area burnt",
        "hectare",
        "acreage",
        "fire size",
    ),
    "duration": ("duration", "length", "hours", "days"),
    "efficiency": ("efficiency", "round-trip efficiency", "round trip efficiency", "rte"),
    "cost": ("cost", "capex", "opex", "lcos", "capital expenditure"),
    "precipitation": ("precipitation", "rainfall", "snowfall", "rain", "snow accumulation"),
    "risk": ("risk", "incidence", "incident", "odds", "hazard"),
}
_DIRECTION_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("increasing", ("increas", "rising", "growth", "grew", "more frequent", "upward trend")),
    ("decreasing", ("decreas", "declin", "reduc", "fell", "less frequent", "downward trend")),
    (
        "mixed",
        (
            "mixed",
            "varied",
            "heterogeneous",
            "no consistent",
            "regional differences",
            "contrasting",
        ),
    ),
    ("stable", ("stable", "no trend", "no significant change", "unchanged")),
)
_TREND_CUES = (
    "trend",
    "time series",
    "long-term",
    "long term",
    "multi-decadal",
    "multidecadal",
    "decadal",
    "over time",
    "over the period",
    "during the period",
    "between",
    "from 19",
    "from 20",
    "annual change",
    "temporal change",
    "has increased",
    "have increased",
    "has decreased",
    "have decreased",
    "increasing",
    "decreasing",
    "declining",
)


def decompose_question(question: str, plan: ResearchPlan) -> dict[str, Any]:
    lowered = question.casefold()
    dimensions: list[dict[str, Any]] = []
    task = plan.intent

    locations = (
        list(plan.geography_terms)
        if plan.subject_terms
        else [
            name
            for name, terms in _LOCATIONS.items()
            if any(_contains(lowered, term) for term in terms)
        ]
    )
    location_groups = {name: _LOCATIONS.get(name, (name,)) for name in locations}
    for name in locations:
        broad_requested = (name == "europe" and bool(re.search(r"\beurope(?:an)?\b", lowered))) or (
            name == "global" and bool(re.search(r"\b(?:global|worldwide|world)\b", lowered))
        )
        terms = (
            ["europe", "european"]
            if name == "europe" and broad_requested
            else ["global", "worldwide", "world"]
            if name == "global" and broad_requested
            else list(location_groups[name])
        )
        dimensions.append(
            {
                "id": f"geography:{name.replace(' ', '_')}",
                "kind": "geography",
                "label": name,
                "terms": terms,
                "required": True,
                "broad_requested": broad_requested,
                "statement_required": broad_requested
                or task in {"relationship", "comparison", "contradiction", "temporal_trend"},
            }
        )

    for index, population in enumerate(plan.population_terms):
        dimensions.append(
            {
                "id": f"population:{index}",
                "kind": "population",
                "label": population,
                "terms": [population],
                "required": True,
                "statement_required": False,
            }
        )
    temporal = _temporal_scope(
        " ".join(plan.time_terms) if plan.time_terms is not None else lowered
    )
    if temporal is None and plan.time_terms:
        temporal = {"label": ", ".join(plan.time_terms), "terms": list(plan.time_terms)}
    if temporal:
        dimensions.append(
            {
                "id": "time:requested_period",
                "kind": "time",
                "label": temporal["label"],
                "terms": temporal["terms"],
                "required": True,
                "statement_required": task == "temporal_trend",
                "requires_temporal_comparison": task == "temporal_trend" or plan.time_terms is None,
                **temporal,
            }
        )

    requested_outcomes = (
        list(plan.outcome_measure_terms)
        if plan.outcome_measure_terms is not None
        else [name for name in _OUTCOME_ALIASES if name != "risk" and _term_present(lowered, name)]
    )
    for name in requested_outcomes:
        dimensions.append(
            {
                "id": f"outcome:{name}",
                "kind": "outcome",
                "label": name,
                "terms": list(_OUTCOME_ALIASES.get(name, (name,))),
                "required": True,
            }
        )

    location_terms = {term for name in locations for term in (name, *location_groups[name])}
    scope_words = (
        location_terms
        | set(requested_outcomes)
        | {
            "trend",
            "trends",
            "change",
            "changes",
            "century",
            "during",
            "period",
            "year",
            "years",
        }
    )
    outcome_terms = {
        term.casefold()
        for name in requested_outcomes
        for term in (name, *_OUTCOME_ALIASES.get(name, (name,)))
    }
    subjects = [
        concept
        for concept in plan.concepts
        if concept.casefold() not in scope_words
        and not any(_term_present(concept.casefold(), term) for term in outcome_terms)
    ]
    if not subjects:
        subjects = list(requested_outcomes[:1] or plan.concepts[:2])
    profile = PROFILES[plan.profile_id]
    # Generic planning retains atomic tokens for high-recall metadata search,
    # but scientific scope must operate on the compound entities in the
    # question. Otherwise a diagnostic question can require seven isolated
    # words (including "measurements") in every passage and miss an exact
    # result stated as "12-lead reference ECG".
    use_entity_subjects = bool(
        plan.profile_id == "generic"
        and len(plan.entity_phrases) >= 2
        and re.search(r"\b(?:accur|diagnos|detect|sensitivity|specificity)", lowered)
        and re.search(r"\b(?:ecg|electrocardiogram)\b", lowered)
    )
    if use_entity_subjects:
        subjects = list(plan.entity_phrases)
    anchors = [concept for concept in subjects if concept in profile.anchor_concepts]
    primary_subjects = anchors or subjects
    topic_concepts = (
        []
        if use_entity_subjects
        else (
            [concept for concept in subjects if concept not in anchors]
            if anchors
            else list(subjects)
        )
    )
    focus = plan_focus(plan)
    if focus:
        primary_subjects = list(plan.subject_terms) or [focus[0]]
        topic_concepts = list(focus[1])
    dimensions.insert(
        0,
        {
            "id": "subject:primary",
            "kind": "subject",
            "label": " and ".join(primary_subjects),
            "terms": primary_subjects,
            "term_groups": [
                list(_scope_aliases(concept, profile, lowered)) for concept in primary_subjects
            ],
            "minimum_group_matches": (
                len(primary_subjects)
                if anchors or task in {"relationship", "comparison", "contradiction", "limitation"}
                else min(2, len(primary_subjects))
            ),
            "mandatory_group_indexes": [
                index
                for index, concept in enumerate(primary_subjects)
                if concept in profile.anchor_concepts
            ],
            # A quantitative comparison commonly introduces the technology in one
            # sentence and reports the value and operating conditions in the next.
            # Requiring the anchor in the result sentence would discard valid,
            # passage-grounded measurements (for example an RTE sentence following
            # an explicit iron-air introduction). Relationship and contradiction
            # claims remain sentence-strict because cross-topic leakage is riskier.
            "statement_required": (bool(anchors) or bool(focus)) and task != "comparison",
            "required": True,
        },
    )
    for index, concept in enumerate(topic_concepts):
        dimensions.append(
            {
                "id": f"topic:{index}",
                "kind": "topic",
                "label": concept,
                "terms": list(profile.expand(concept)),
                "required": True,
                "statement_required": (
                    task in {"relationship", "comparison", "contradiction", "limitation"}
                    and index in {0, len(topic_concepts) - 1}
                ),
            }
        )
    if task == "temporal_trend":
        dimensions.append(
            {
                "id": "task:temporal_trend",
                "kind": "task",
                "label": "change across time",
                "terms": list(_TREND_CUES),
                "required": True,
            }
        )

    subject = " and ".join(subjects) or "the subject"
    geography = ", ".join(locations) or "the requested setting"
    period = temporal["label"] if temporal else "the requested period"
    subquestions = [
        {
            "id": "subquestion:overall",
            "text": question.strip(),
            "purpose": "answer the researcher's complete question",
            "required": True,
        }
    ]
    if task == "temporal_trend":
        subquestions.extend(
            (
                {
                    "id": "subquestion:direction",
                    "text": f"What direction and magnitude of change is reported for {subject} in {geography} during {period}?",
                    "purpose": "temporal direction and magnitude",
                    "required": True,
                },
                {
                    "id": "subquestion:methods",
                    "text": f"Which longitudinal datasets and measurement definitions support trends in {subject}?",
                    "purpose": "methods and comparability",
                    "required": True,
                },
                {
                    "id": "subquestion:heterogeneity",
                    "text": f"How do reported trends in {subject} differ by region, period, and outcome definition?",
                    "purpose": "heterogeneity and apparent disagreement",
                    "required": True,
                },
            )
        )
    elif task in {"comparison", "contradiction"}:
        subquestions.extend(
            (
                {
                    "id": "subquestion:values",
                    "text": f"Which source-reported results are available for {subject}?",
                    "purpose": "reported results and provenance",
                    "required": True,
                },
                {
                    "id": "subquestion:contexts",
                    "text": f"Which methods, scales, operating conditions, and assumptions produced the reported results for {subject}?",
                    "purpose": "comparison context",
                    "required": True,
                },
                {
                    "id": "subquestion:comparability",
                    "text": f"Which reported results for {subject} are directly comparable, and which differ in important context?",
                    "purpose": "comparability decision",
                    "required": True,
                },
            )
        )
    return {
        "schema_version": "question_decomposition_v1",
        "task": task,
        "dimensions": dimensions,
        "subquestions": subquestions,
        "requirements": {
            "alternative_driver_dimensions": [
                f"topic:{index}" for index in range(len(topic_concepts))
            ]
            if focus and task == "relationship"
            else [],
            "minimum_independent_publications": 3
            if task == "temporal_trend"
            else 2
            if task in {"comparison", "contradiction", "assumption", "relationship", "limitation"}
            else 1,
            "trend_requires_multi_period_evidence": task == "temporal_trend",
            "requested_outcomes_are_alternatives": " or " in lowered,
            "requires_exact_global_count": bool(
                re.search(r"\bexact\b", lowered)
                and "global" in locations
                and re.search(r"\b(?:population|number|count)\b", lowered)
            ),
            "target_years": re.findall(r"\b(?:19|20)\d{2}\b", lowered),
            "requires_broad_geographic_synthesis": bool(
                task == "temporal_trend"
                and any(
                    item.get("broad_requested")
                    for item in dimensions
                    if item.get("kind") == "geography"
                )
            ),
            "requires_method_evidence": task == "method",
            "requires_method_limitations": bool(
                task == "method"
                and re.search(
                    r"\b(?:limitation|limitations|bias|biases|drawback|drawbacks)\b", lowered
                )
            ),
            "requires_explanatory_evidence": bool(
                re.search(r"^\s*why\b|\bwhat explains?\b", lowered)
            ),
            "requires_diagnostic_metrics": bool(
                task == "comparison"
                and re.search(r"\b(?:accur|diagnos|detect|sensitivity|specificity)", lowered)
                and re.search(
                    r"\b(?:ecg|electrocardiogram|reference standard|gold standard)\b", lowered
                )
            ),
            "requested_temporal_nature": (
                "projected"
                if task == "temporal_trend" and re.search(r"\b(?:project|future|scenario)", lowered)
                else "observed"
                if task == "temporal_trend"
                else None
            ),
            "requires_directional_trend": task == "temporal_trend",
            "requires_clarification": bool(
                plan.profile_id == "generic"
                and len(plan.concepts) <= 1
                and (
                    re.search(r"\b[A-Z]{2,5}\b", question)
                    or re.search(r"\bwhat (?:does|is)\b.+\bmean\b", question, re.IGNORECASE)
                )
            ),
        },
    }


def _scope_aliases(concept: str, profile: Any, question: str) -> tuple[str, ...]:
    """Return conservative aliases used only to establish passage scope."""
    aliases = list(profile.expand(concept))
    lowered = concept.casefold()
    if profile.id == "generic":
        if "wearable" in lowered and any(term in lowered for term in ("device", "monitor")):
            aliases.extend(("wearable device", "consumer wearable", "smartwatch", "smart watch"))
        if lowered == "atrial fibrillation":
            aliases.extend(("atrial fibrillation", "AF detection", "AF diagnosis"))
        if "ecg" in lowered or "electrocardiogram" in lowered:
            aliases.extend(
                (
                    "clinical ECG",
                    "reference ECG",
                    "12-lead ECG",
                    "reference electrocardiogram",
                    "electrocardiogram gold standard",
                    "ECG as the gold standard",
                )
            )
        if "fine particulate matter" in lowered:
            aliases.extend(("PM2.5", "PM 2.5", "fine particles"))
    return tuple(dict.fromkeys(aliases))


def evidence_context(text: str, decomposition: dict[str, Any]) -> dict[str, Any]:
    # PDF text frequently wraps multi-word subjects across lines and inserts
    # discretionary line-end hyphens. Normalize only for matching; the stored
    # quotation and offsets remain byte-for-byte tied to the source text.
    lowered = re.sub(r"(?<=\w)-\s+(?=\w)", "", text.casefold())
    lowered = " ".join(lowered.split())
    years = tuple(dict.fromkeys(re.findall(r"\b(?:18|19|20)\d{2}\b", lowered)))
    periods = list(years)
    periods.extend(
        match.group(0)
        for match in re.finditer(
            r"\b(?:\d{1,2}|several|multiple)[- ]year(?:s)?\b|\b(?:long[- ]term|multi[- ]decadal|decadal|time series)\b",
            lowered,
        )
    )
    locations = tuple(
        dict.fromkeys(
            name
            for name, terms in _LOCATIONS.items()
            if any(_contains(lowered, term) for term in terms)
        )
    )
    direction = next(
        (label for label, cues in _DIRECTION_CUES if any(cue in lowered for cue in cues)), None
    )
    matched_dimensions = []
    for dimension in decomposition.get("dimensions", []):
        kind = dimension.get("kind")
        if kind == "time":
            if _time_dimension_present(lowered, years, dimension):
                matched_dimensions.append(dimension["id"])
        elif kind == "subject" and dimension.get("term_groups"):
            groups = list(dimension.get("term_groups", []))
            group_results = [_group_present(lowered, group) for group in groups]
            group_matches = sum(group_results)
            mandatory = [int(value) for value in dimension.get("mandatory_group_indexes", [])]
            if all(
                index < len(group_results) and group_results[index] for index in mandatory
            ) and group_matches >= int(dimension.get("minimum_group_matches") or len(groups)):
                matched_dimensions.append(dimension["id"])
        elif any(_term_present(lowered, str(term)) for term in dimension.get("terms", [])):
            matched_dimensions.append(dimension["id"])
    century_projection = bool(
        re.search(
            r"\b21st[- ]century\b|\bend of (?:the )?century\b|\bfuture\b|\bproject(?:ed|ion|ions)?\b",
            lowered,
        )
    )
    trend_evidence = (
        (bool(direction) and century_projection)
        or any(cue in lowered for cue in _TREND_CUES)
        and (
            (len(years) >= 2 and max(map(int, years)) - min(map(int, years)) >= 5)
            or any(
                term in lowered
                for term in (
                    "time series",
                    "long-term",
                    "long term",
                    "multi-decadal",
                    "multidecadal",
                    "decadal",
                    "over time",
                    "temporal trend",
                )
            )
        )
    )
    return {
        "locations": locations,
        "time_mentions": tuple(dict.fromkeys(periods)),
        "direction": direction,
        "scope_dimension_ids": tuple(matched_dimensions),
        "trend_evidence": trend_evidence,
        "trend_signal": bool(direction or any(cue in lowered for cue in _TREND_CUES)),
    }


def assess_answer_adequacy(
    evidence: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    decomposition: dict[str, Any],
) -> dict[str, Any]:
    records = [item for item in evidence if isinstance(item, dict)]
    publications = {
        str(item.get("publication_id")) for item in records if item.get("publication_id")
    }
    dimension_publications: dict[str, set[str]] = defaultdict(set)
    trend_publications: set[str] = set()
    qualifying_publications: set[str] = set()
    trend_years: set[int] = set()
    qualifying_evidence_ids: list[str] = []
    answer_evidence_ids: list[str] = []
    exact_count_publications: set[str] = set()
    broad_synthesis_publications: set[str] = set()
    method_publications: set[str] = set()
    method_limitation_publications: set[str] = set()
    explanatory_publications: set[str] = set()
    diagnostic_publications: set[str] = set()
    temporal_nature_publications: set[str] = set()
    directional_trend_publications: set[str] = set()
    driver_dimensions = set(
        decomposition.get("requirements", {}).get("alternative_driver_dimensions", [])
    )
    required_dimensions = [
        str(item.get("id"))
        for item in decomposition.get("dimensions", [])
        if item.get("required")
        and item.get("kind") in {"subject", "geography", "population", "time", "topic"}
        and item.get("id") not in driver_dimensions
    ]
    statement_required_dimensions = {
        str(item.get("id"))
        for item in decomposition.get("dimensions", [])
        if item.get("required")
        and item.get("statement_required")
        and item.get("id") not in driver_dimensions
    }
    outcome_dimensions = {
        str(item.get("id"))
        for item in decomposition.get("dimensions", [])
        if item.get("kind") == "outcome"
    }
    for item in records:
        publication_id = str(item.get("publication_id") or "")
        matched = {str(value) for value in item.get("scope_dimension_ids") or []}
        statement_matched = {str(value) for value in item.get("statement_dimension_ids") or []}
        for dimension_id in matched:
            if dimension_id not in driver_dimensions:
                dimension_publications[str(dimension_id)].add(publication_id)
        complete_scope = all(dimension_id in matched for dimension_id in required_dimensions)
        if driver_dimensions:
            complete_scope = complete_scope and bool(driver_dimensions & statement_matched)
        subject_dimensions = {
            str(dimension.get("id"))
            for dimension in decomposition.get("dimensions", [])
            if dimension.get("kind") == "subject" and dimension.get("statement_required")
        }
        subject_match = not subject_dimensions or subject_dimensions <= statement_matched
        statement_scope_match = statement_required_dimensions <= statement_matched
        outcome_match = not outcome_dimensions or bool(outcome_dimensions & statement_matched)
        statement = " ".join(str(item.get("statement") or "").casefold().split())
        requested_temporal_nature = decomposition.get("requirements", {}).get(
            "requested_temporal_nature"
        )
        projection_statement = bool(
            re.search(
                r"\b(?:future|project(?:ed|ion|ions)?|scenario|ssp\d|rcp\d|2080|2090|2100)\b",
                statement,
            )
        )
        temporal_nature_match = (
            not requested_temporal_nature
            or requested_temporal_nature == "projected"
            and projection_statement
            or requested_temporal_nature == "observed"
            and not projection_statement
        )
        directional_trend_match = not decomposition.get("requirements", {}).get(
            "requires_directional_trend"
        ) or bool(item.get("direction"))
        task_match = decomposition.get("task") != "temporal_trend" or (
            bool(item.get("trend_evidence"))
            and bool(item.get("statement_trend_signal"))
            and temporal_nature_match
            and directional_trend_match
        )
        if requested_temporal_nature and temporal_nature_match:
            temporal_nature_publications.add(publication_id)
        if (
            decomposition.get("requirements", {}).get("requires_directional_trend")
            and directional_trend_match
        ):
            directional_trend_publications.add(publication_id)
        target_years = {
            str(value) for value in decomposition.get("requirements", {}).get("target_years", [])
        }
        numerical_values = {
            match.group(0)
            for value in item.get("numerical_mentions") or []
            for match in [re.search(r"\d+(?:\.\d+)?", str(value))]
            if match
        }
        exact_count_match = not decomposition.get("requirements", {}).get(
            "requires_exact_global_count"
        ) or (
            bool(re.search(r"\b(?:global|worldwide|world)\b", statement))
            and bool(re.search(r"\b(?:population|census|count|individuals?)\b", statement))
            and (
                not target_years
                or bool(target_years & set(re.findall(r"\b(?:19|20)\d{2}\b", statement)))
            )
            and bool(numerical_values - target_years)
        )
        if exact_count_match and decomposition.get("requirements", {}).get(
            "requires_exact_global_count"
        ):
            exact_count_publications.add(publication_id)
        broad_synthesis_match = not decomposition.get("requirements", {}).get(
            "requires_broad_geographic_synthesis"
        ) or bool(
            re.search(
                r"\b(?:across|throughout) europe\b|\beurope[- ]wide\b|\bcontinental\b|\bregional differences?\b|\bheterogen|\bmixed\b|\bvar(?:y|ies|ied|iation)\b",
                statement,
            )
        )
        if broad_synthesis_match and decomposition.get("requirements", {}).get(
            "requires_broad_geographic_synthesis"
        ):
            broad_synthesis_publications.add(publication_id)
        if re.search(
            r"\b(?:method|measur|sampling|observ(?:e|ed|ation)|gps|sensor|questionnaire|metabarcod|microhistolog|tracking)\b",
            statement,
        ):
            method_publications.add(publication_id)
        if re.search(
            r"\b(?:limitation|bias|uncertain|constraint|drawback|underestimat|overestimat|resolution|accuracy|cannot|however)\b",
            statement,
        ):
            method_limitation_publications.add(publication_id)
        if re.search(
            r"\b(?:because|due to|driven by|explained by|attribut(?:e|ed|able) to|depend(?:s|ed|ing)? on|heterogen|var(?:y|ies|ied) (?:with|by|across|among))\b",
            statement,
        ):
            explanatory_publications.add(publication_id)
        diagnostic_required = bool(
            decomposition.get("requirements", {}).get("requires_diagnostic_metrics")
        )
        diagnostic_context = " ".join((statement, str(item.get("passage") or "").casefold()))
        diagnostic_match = not diagnostic_required or bool(
            re.search(
                r"\b(?:sensitivity|specificity|predictive value|accuracy|area under (?:the )?curve|auc)\b",
                statement,
            )
            and re.search(r"(?:\b\d+(?:\.\d+)?\s*%|\b0\.\d+\b)", statement)
            and re.search(
                r"\b(?:reference|12[- ]lead|gold standard|clinical)\b.{0,45}\b(?:ecg|electrocardiogram)\b|\b(?:ecg|electrocardiogram)\b.{0,45}\b(?:reference|gold standard)\b",
                diagnostic_context,
            )
        )
        if diagnostic_required and diagnostic_match:
            diagnostic_publications.add(publication_id)
        # A result sentence may say "the battery" while the exact surrounding
        # passage establishes that it is the requested technology. Such a record
        # is safe to quote in an answer, but it must not independently satisfy the
        # stricter cross-publication adequacy count unless the sentence names the
        # subject itself.
        if (
            complete_scope
            and subject_match
            and statement_scope_match
            and outcome_match
            and task_match
            and exact_count_match
            and diagnostic_match
            and item.get("id")
        ):
            answer_evidence_ids.append(str(item["id"]))
        if (
            complete_scope
            and subject_match
            and statement_scope_match
            and outcome_match
            and task_match
            and exact_count_match
            and diagnostic_match
        ):
            qualifying_publications.add(publication_id)
            for dimension_id in driver_dimensions & statement_matched:
                dimension_publications[dimension_id].add(publication_id)
            if item.get("id"):
                qualifying_evidence_ids.append(str(item["id"]))
        if (
            item.get("trend_evidence")
            and item.get("statement_trend_signal")
            and complete_scope
            and subject_match
            and statement_scope_match
            and outcome_match
            and temporal_nature_match
            and directional_trend_match
        ):
            trend_publications.add(publication_id)
            trend_years.update(
                int(value) for value in item.get("time_mentions") or [] if str(value).isdigit()
            )

    checks: list[dict[str, Any]] = []
    dimension_minimum = 2 if decomposition.get("task") == "temporal_trend" else 1
    for dimension in decomposition.get("dimensions", []):
        if dimension.get("kind") == "task":
            continue
        count = len(dimension_publications.get(str(dimension["id"]), set()))
        checks.append(
            {
                "id": f"coverage:{dimension['id']}",
                "label": dimension.get("label"),
                "kind": dimension.get("kind"),
                "passed": count >= dimension_minimum,
                "publication_count": count,
                "required": bool(dimension.get("required", True)),
                "minimum": dimension_minimum,
            }
        )
    required_publications = int(
        decomposition.get("requirements", {}).get("minimum_independent_publications") or 1
    )
    checks.append(
        {
            "id": "coverage:independent_publications",
            "label": "independent contributing publications",
            "kind": "evidence_base",
            "passed": len(qualifying_publications) >= required_publications,
            "publication_count": len(qualifying_publications),
            "required": True,
            "minimum": required_publications,
        }
    )
    if decomposition.get("requirements", {}).get("requires_clarification"):
        checks.append(
            {
                "id": "coverage:question_clarity",
                "label": "unambiguous scientific meaning",
                "kind": "question",
                "passed": False,
                "publication_count": 0,
                "required": True,
                "minimum": 1,
            }
        )
    if decomposition.get("requirements", {}).get("requires_exact_global_count"):
        checks.append(
            {
                "id": "coverage:exact_global_count",
                "label": "verifiable exact global census for the requested year",
                "kind": "question",
                "passed": bool(exact_count_publications),
                "publication_count": len(exact_count_publications),
                "required": True,
                "minimum": 1,
            }
        )
    if decomposition.get("requirements", {}).get("requires_method_evidence"):
        checks.append(
            {
                "id": "coverage:method_evidence",
                "label": "direct evidence about measurement methods",
                "kind": "task",
                "passed": bool(method_publications),
                "publication_count": len(method_publications),
                "required": True,
                "minimum": 1,
            }
        )
    if decomposition.get("requirements", {}).get("requires_method_limitations"):
        checks.append(
            {
                "id": "coverage:method_limitations",
                "label": "source-reported method limitations",
                "kind": "task",
                "passed": bool(method_limitation_publications),
                "publication_count": len(method_limitation_publications),
                "required": True,
                "minimum": 1,
            }
        )
    if decomposition.get("requirements", {}).get("requires_explanatory_evidence"):
        checks.append(
            {
                "id": "coverage:explanatory_evidence",
                "label": "direct evidence explaining differences between studies",
                "kind": "task",
                "passed": bool(explanatory_publications),
                "publication_count": len(explanatory_publications),
                "required": True,
                "minimum": 1,
            }
        )
    if decomposition.get("requirements", {}).get("requires_diagnostic_metrics"):
        checks.append(
            {
                "id": "coverage:diagnostic_metrics",
                "label": "diagnostic metrics tied to a clinical ECG reference standard",
                "kind": "task",
                "passed": bool(diagnostic_publications),
                "publication_count": len(diagnostic_publications),
                "required": True,
                "minimum": 1,
            }
        )
    if decomposition.get("task") == "temporal_trend":
        requested_nature = str(
            decomposition.get("requirements", {}).get("requested_temporal_nature") or "temporal"
        )
        checks.append(
            {
                "id": "coverage:temporal_nature",
                "label": f"{requested_nature} rather than mismatched temporal evidence",
                "kind": "task",
                "passed": bool(temporal_nature_publications),
                "publication_count": len(temporal_nature_publications),
                "required": True,
                "minimum": 1,
            }
        )
        checks.append(
            {
                "id": "coverage:directional_trend",
                "label": "source-reported direction of change",
                "kind": "task",
                "passed": bool(directional_trend_publications),
                "publication_count": len(directional_trend_publications),
                "required": True,
                "minimum": 1,
            }
        )
        broad_period = len(trend_years) >= 2 and max(trend_years) - min(trend_years) >= 5
        checks.append(
            {
                "id": "coverage:multi_period_trend",
                "label": "multi-period trend evidence",
                "kind": "task",
                "passed": len(trend_publications) >= required_publications
                and (broad_period or not trend_years),
                "publication_count": len(trend_publications),
                "required": True,
                "minimum": required_publications,
                "year_min": min(trend_years) if trend_years else None,
                "year_max": max(trend_years) if trend_years else None,
            }
        )
        if decomposition.get("requirements", {}).get("requires_broad_geographic_synthesis"):
            checks.append(
                {
                    "id": "coverage:broad_geographic_synthesis",
                    "label": "continent-wide or explicitly heterogeneous regional synthesis",
                    "kind": "task",
                    "passed": bool(broad_synthesis_publications),
                    "publication_count": len(broad_synthesis_publications),
                    "required": True,
                    "minimum": 1,
                }
            )
        outcome_checks = [item for item in checks if item["kind"] == "outcome"]
        if outcome_checks and decomposition.get("requirements", {}).get(
            "requested_outcomes_are_alternatives"
        ):
            outcome_publications = set().union(
                *(
                    dimension_publications.get(item["id"].removeprefix("coverage:"), set())
                    for item in outcome_checks
                )
            )
            outcome_passed = len(outcome_publications) >= 2
            checks.append(
                {
                    "id": "coverage:requested_outcome",
                    "label": "requested outcome definition",
                    "kind": "outcome_group",
                    "passed": outcome_passed,
                    "required": True,
                    "publication_count": len(outcome_publications),
                }
            )
            for item in outcome_checks:
                item["required"] = False

    failed = [item for item in checks if item.get("required") and not item.get("passed")]
    passed_required = [item for item in checks if item.get("required") and item.get("passed")]
    status = (
        "adequate"
        if not failed and records
        else "partial"
        if passed_required and records
        else "insufficient"
    )
    missing = [str(item.get("label")) for item in failed]
    return {
        "schema_version": "answer_adequacy_v1",
        "status": status,
        "can_answer_overall_question": status == "adequate",
        "checks": checks,
        "missing_requirements": missing,
        "contributing_publications": len(publications),
        "qualifying_publications": len(qualifying_publications),
        "trend_publications": len(trend_publications),
        "qualifying_evidence_ids": qualifying_evidence_ids,
        "answer_evidence_ids": answer_evidence_ids,
        "decision": (
            "The retrieved evidence covers every required scope and adequacy check."
            if status == "adequate"
            else "The retrieved evidence is relevant but does not support an overall answer to the complete question."
            if status == "partial"
            else "The retrieved evidence does not support an answer to the complete question."
        ),
    }


def coverage_follow_up_queries(
    question: str,
    decomposition: dict[str, Any],
    assessment: dict[str, Any],
    *,
    limit: int = 4,
) -> tuple[SearchQuery, ...]:
    if assessment.get("status") == "adequate":
        return ()
    dimensions = decomposition.get("dimensions", [])
    subject = next((item for item in dimensions if item.get("kind") == "subject"), {})
    geography = next((item for item in dimensions if item.get("kind") == "geography"), {})
    time_scope = next((item for item in dimensions if item.get("kind") == "time"), {})
    outcomes = [item for item in dimensions if item.get("kind") == "outcome"]
    base = " ".join(
        filter(None, (str(subject.get("label") or ""), str(geography.get("label") or "")))
    )
    period = str(time_scope.get("search_label") or time_scope.get("label") or "")
    variants: list[tuple[str, str]] = []
    if decomposition.get("task") == "temporal_trend":
        variants.extend(
            (
                (
                    f'{base} {period} "time series" trend',
                    "coverage gap: multi-period trend evidence",
                ),
                (
                    f"{base} {period} longitudinal annual change",
                    "coverage gap: temporal direction and magnitude",
                ),
            )
        )
        for outcome in outcomes[:2]:
            aliases = " ".join(str(item) for item in outcome.get("terms", [])[:4])
            variants.append(
                (
                    f"{base} {period} {aliases} trend",
                    f"coverage gap: {outcome.get('label')} outcome",
                )
            )
    elif decomposition.get("task") in {"comparison", "contradiction"}:
        terms = [str(item) for item in subject.get("terms", []) if item]
        outcome_terms = []
        for outcome in outcomes[:2]:
            candidates = [str(item) for item in outcome.get("terms", []) if item]
            preferred = next((item for item in candidates if " " in item), None)
            outcome_terms.append(preferred or str(outcome.get("label") or ""))
        terms = [*outcome_terms, *terms]
        canonical = " ".join(f'"{item}"' if " " in item else item for item in terms if item)
        variants.extend(
            (
                (canonical, "coverage gap: additional directly relevant studies"),
                (
                    f"{canonical} measured modeled experimental",
                    "coverage gap: evidence and method diversity",
                ),
                (
                    f"{canonical} operating conditions system cell",
                    "coverage gap: comparison context",
                ),
            )
        )
    else:
        for missing in assessment.get("missing_requirements", [])[:2]:
            variants.append((f"{question} {missing}", f"coverage gap: {missing}"))
    result = []
    seen = set()
    for text, purpose in variants:
        cleaned = " ".join(text.split())[:300]
        if not cleaned or cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        identifier = (
            "query:coverage:" + hashlib.sha256(f"{purpose}\x1f{cleaned}".encode()).hexdigest()[:12]
        )
        result.append(SearchQuery(identifier, cleaned, purpose))
    return tuple(result[:limit])


def gate_model_analysis(analysis: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    if assessment.get("can_answer_overall_question"):
        return analysis
    result = dict(analysis)
    result["answer"] = None
    result["answer_withheld"] = True
    result["answer_withheld_reason"] = result.get("answer_withheld_reason") or assessment.get(
        "decision"
    )
    result["coverage_withheld_reason"] = assessment.get("decision")
    if result.get("status") != "unavailable":
        result["status"] = "coverage_limited"
    return result


def _temporal_scope(question: str) -> dict[str, Any] | None:
    century = re.search(r"\b(1[5-9]|20|21)(?:st|nd|rd|th) century\b", question)
    if century:
        value = int(century.group(1))
        start = (value - 1) * 100 + 1
        return {
            "label": century.group(0),
            "search_label": f"{start - 1} present",
            "start_year": start,
            "end_year": value * 100,
            "terms": [century.group(0), str(start - 1), str(start)],
        }
    years = [int(item) for item in re.findall(r"\b(?:18|19|20)\d{2}\b", question)]
    if len(years) >= 2:
        return {
            "label": f"{min(years)}–{max(years)}",
            "search_label": f"{min(years)} {max(years)}",
            "start_year": min(years),
            "end_year": max(years),
            "terms": [str(item) for item in years],
        }
    if len(years) == 1 and "since" in question:
        return {
            "label": f"since {years[0]}",
            "search_label": f"{years[0]} present",
            "start_year": years[0],
            "end_year": 2200,
            "terms": [str(years[0]), "since"],
        }
    return None


def _time_dimension_present(text: str, years: tuple[str, ...], dimension: dict[str, Any]) -> bool:
    start, end = dimension.get("start_year"), dimension.get("end_year")
    if not isinstance(start, int) or not isinstance(end, int):
        return any(_contains(text, str(term)) for term in dimension.get("terms", []))
    in_range = sorted({int(year) for year in years if start <= int(year) <= end})
    if dimension.get("requires_temporal_comparison") is False:
        return bool(in_range)
    label = str(dimension.get("label") or "").casefold()
    if "century" in label:
        number = re.search(r"\b(1[5-9]|20|21)", label)
        explicit = bool(
            number
            and re.search(
                rf"\b{number.group(1)}(?:st|nd|rd|th)?(?:[-‐‑‒–— ]+)century\b",
                text,
            )
        )
        return explicit or (len(in_range) >= 2 and in_range[-1] - in_range[0] >= 5)
    if label.startswith("since "):
        return ("since" in text and str(start) in text) or (
            len(in_range) >= 2 and in_range[-1] > in_range[0]
        )
    return len(in_range) >= 2 and in_range[-1] > in_range[0]


def _contains(text: str, term: str) -> bool:
    return concept_present(text, term)


def _term_present(text: str, term: str) -> bool:
    normalized = term.casefold()
    if _contains(text, normalized):
        return True
    if normalized.endswith("y") and len(normalized) > 3:
        return _contains(text, normalized[:-1] + "ies")
    if normalized.endswith("ies") and len(normalized) > 4:
        return _contains(text, normalized[:-3] + "y")
    if normalized.endswith("s") and len(normalized) > 4:
        return _contains(text, normalized[:-1])
    if len(normalized) > 3:
        return _contains(text, normalized + "s")
    return False


def _group_present(text: str, terms: list[Any] | tuple[Any, ...]) -> bool:
    normalized = {str(term).casefold() for term in terms}
    if any(_term_present(text, term) for term in normalized):
        return True
    if "temperature" in normalized and re.search(r"(?:°\s*c|\bkelvin\b|\b\d{2,4}\s*k\b)", text):
        return True
    if "current density" in normalized and re.search(
        r"\b\d+(?:\.\d+)?\s*(?:m?a\s*(?:cm|m)[−–-]?2|c(?:\s|[,.;)]|$))",
        text,
    ):
        return True
    if "cycle life" in normalized and re.search(r"\b\d+(?:,\d+)?\s*cycles?\b", text):
        return True
    return False
