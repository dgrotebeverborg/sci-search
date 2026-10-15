"""Transparent scientific query planning, candidate normalization and screening."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from sci_search.concept_matching import concept_present
from sci_search.profiles import PROFILES
from sci_search.question_planning import ResearchPlan, plan_focus, plan_question


@dataclass(frozen=True, slots=True)
class SearchQuery:
    id: str
    text: str
    purpose: str


@dataclass(frozen=True, slots=True)
class PublicationCandidate:
    id: str
    title: str
    abstract: str
    year: int | None
    doi: str | None
    authors: tuple[str, ...]
    publication_type: str
    source_url: str | None
    full_text_url: str | None = None
    document_fingerprint: str | None = None
    author_ids: tuple[str, ...] = ()
    institutions: tuple[str, ...] = ()
    institution_ids: tuple[str, ...] = ()
    affiliations: tuple[str, ...] = ()
    openalex_id: str | None = None
    pmcid: str | None = None
    cited_by_count: int = 0
    is_open_access: bool = False
    license: str | None = None
    has_pdf: bool = False
    has_structured_fulltext: bool = False
    has_local_fulltext: bool = False
    is_retracted: bool = False
    providers: tuple[str, ...] = ()
    matched_query_ids: tuple[str, ...] = ()
    citation_relations: tuple[str, ...] = ()
    relevance_score: float = 0.0
    concept_coverage: float = 0.0
    screening_status: str = "candidate"
    screening_reason: str = "not screened"
    oa_landing_urls: tuple[str, ...] = ()


def plan_search_queries(
    question: str, *, plan: ResearchPlan | None = None
) -> tuple[ResearchPlan, tuple[SearchQuery, ...]]:
    plan = plan or plan_question(question)
    concepts = list(plan.concepts)
    focus = plan_focus(plan)
    core = " ".join(concepts[:5])
    variants: list[tuple[str, str]] = [(question.strip().rstrip("?"), "natural-language question")]
    if plan.entity_phrases and not focus:
        variants.append(
            (
                " ".join(f'"{phrase}"' for phrase in plan.entity_phrases[:4]),
                "compound scientific entities",
            )
        )
    if core:
        variants.append((core, "canonical concepts"))
    if focus:
        variants.append((" ".join((focus[0], *focus[2])), "explanatory subject and scope"))
        # Studies usually cover one place or one subject part; a query naming all of them
        # mostly finds the rare study that covers every one.
        subjects = plan.subject_terms or (focus[0],)
        if len(subjects) > 1:
            for subject in subjects:
                variants.append(
                    (" ".join((subject, *focus[1], *focus[2])), f"subject part: {subject}")
                )
        if len(focus[2]) > 1:
            for place in focus[2]:
                variants.append((" ".join((*subjects, *focus[1], place)), f"one place: {place}"))
    # Put task-specific strategies before broad sensitivity variants. The query
    # budget is deliberately bounded, and the previous ordering could exhaust
    # all eight slots before a diagnostic, trend, or explanatory query was
    # emitted. That produced many topic matches while missing the study designs
    # actually needed to answer the question.
    lowered_question = question.casefold()
    if focus and plan.intent == "relationship":
        variants.append(
            (core + " association evidence", "association evidence")
            if plan.relationship_type == "association"
            else (core + " drivers mechanisms evidence", "explanatory evidence")
        )
    elif plan.intent == "temporal_trend":
        if any(term in lowered_question for term in ("project", "future", "scenario")):
            variants.append((core + " projection scenario model", "projected temporal evidence"))
        else:
            variants.append((core + " observed trend time series", "observed temporal evidence"))
            if "precipitation" in lowered_question:
                variants.append(
                    (
                        core
                        + " snowfall rainfall accumulation reconstruction surface mass balance observations",
                        "observed precipitation components",
                    )
                )
    elif plan.intent == "method":
        variants.append(
            (
                core + " methods measurement validation limitations",
                "methods and validation evidence",
            )
        )
    elif plan.intent in {"relationship", "comparison", "contradiction"}:
        if any(
            term in lowered_question
            for term in ("accur", "diagnos", "detect", "sensitivity", "specificity")
        ):
            variants.append(
                (
                    core + " sensitivity specificity reference standard validation",
                    "diagnostic accuracy evidence",
                )
            )
        elif lowered_question.startswith("why ") or "what explains" in lowered_question:
            variants.append(
                (core + " heterogeneity moderators meta-analysis", "explanatory synthesis evidence")
            )
        else:
            variants.append(
                (core + " comparative experiment field study", "empirical relationship evidence")
            )
    elif plan.intent == "limitation":
        variants.append((core + " mechanism experimental evidence", "mechanistic evidence"))
    else:
        variants.append((core + " results evidence", "reported evidence"))
    if len(concepts) >= 3:
        # Sensitivity queries deliberately relax one concept. Metadata often uses
        # a specific proxy (leaf type, canopy height, NaCl) instead of the broader
        # term present in the research question. Strict screening is applied after
        # discovery, so this improves recall without automatically admitting noise.
        for omitted in concepts:
            if focus and omitted in (*plan.subject_terms, focus[0], *focus[2]):
                continue
            relaxed = " ".join(concept for concept in concepts if concept != omitted)
            variants.append((relaxed, f"sensitivity query; omitted {omitted}"))
    if plan.profile_id != "generic":
        domain_terms = []
        for concept in concepts[:4]:
            aliases = PROFILES[plan.profile_id].expand(concept)
            domain_terms.append(aliases[1] if len(aliases) > 1 else concept)
        variants.append((" ".join(domain_terms), f"{plan.profile_id} vocabulary"))
        if len(concepts) >= 2:
            primary = PROFILES[plan.profile_id].expand(concepts[0])[:4]
            secondary_all = PROFILES[plan.profile_id].expand(concepts[1])
            secondary = tuple(
                dict.fromkeys(
                    (
                        *secondary_all[:4],
                        *secondary_all[4::3],
                        *secondary_all[-2:],
                    )
                )
            )[:9]

            def quote(value: str) -> str:
                return f'"{value}"' if " " in value else value

            boolean_query = (
                "("
                + " OR ".join(quote(value) for value in primary)
                + ") AND ("
                + " OR ".join(quote(value) for value in secondary)
                + ")"
            )
            variants.append((boolean_query, f"{plan.profile_id} Boolean synonym recall"))
            facet_aliases = [value for value in secondary_all[1:] if "selection" in value]
            facet_aliases.extend(
                value
                for value in secondary_all[1:]
                if " " not in value and not value.startswith("forag")
            )
            for alias in tuple(dict.fromkeys(facet_aliases))[:3]:
                variants.append(
                    (f'{concepts[0]} "{alias}"', f"{plan.profile_id} synonym facet: {alias}")
                )
    queries: list[SearchQuery] = []
    seen: set[str] = set()
    for text, purpose in variants:
        cleaned = " ".join(text.split())[:300]
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        query_id = "query:" + hashlib.sha256(f"{purpose}\x1f{cleaned}".encode()).hexdigest()[:12]
        queries.append(SearchQuery(query_id, cleaned, purpose))
    return plan, tuple(queries[:8])


def merge_candidates(
    candidates: Iterable[PublicationCandidate],
) -> tuple[PublicationCandidate, ...]:
    merged: dict[str, PublicationCandidate] = {}
    for candidate in candidates:
        key = _dedupe_key(candidate)
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        merged[key] = _combine_candidates(existing, candidate)

    # Crossref can expose a discussion-paper DOI and the final-version DOI for
    # one identical OA PDF. The DOI pass above enriches cached records with the
    # discovered PDF URL; this second pass then collapses those versions by the
    # actual source document used for analysis.
    documents: dict[str, PublicationCandidate] = {}
    for candidate in merged.values():
        key = (
            "document:" + candidate.document_fingerprint
            if candidate.document_fingerprint
            else "fulltext:" + candidate.full_text_url.casefold().split("?", 1)[0].rstrip("/")
            if candidate.full_text_url
            else _dedupe_key(candidate)
        )
        documents[key] = (
            _combine_candidates(documents[key], candidate) if key in documents else candidate
        )
    return tuple(documents.values())


def _combine_candidates(
    existing: PublicationCandidate, candidate: PublicationCandidate
) -> PublicationCandidate:
    authors, author_ids = _merge_named_entities(
        existing.authors,
        existing.author_ids,
        candidate.authors,
        candidate.author_ids,
    )
    institutions, institution_ids = _merge_named_entities(
        existing.institutions,
        existing.institution_ids,
        candidate.institutions,
        candidate.institution_ids,
    )
    return replace(
        existing,
        abstract=existing.abstract
        if len(existing.abstract) >= len(candidate.abstract)
        else candidate.abstract,
        doi=existing.doi or candidate.doi,
        authors=authors,
        author_ids=author_ids,
        institutions=institutions,
        institution_ids=institution_ids,
        affiliations=tuple(dict.fromkeys((*existing.affiliations, *candidate.affiliations))),
        source_url=existing.source_url or candidate.source_url,
        full_text_url=existing.full_text_url or candidate.full_text_url,
        oa_landing_urls=tuple(
            dict.fromkeys((*existing.oa_landing_urls, *candidate.oa_landing_urls))
        ),
        document_fingerprint=existing.document_fingerprint or candidate.document_fingerprint,
        openalex_id=existing.openalex_id or candidate.openalex_id,
        pmcid=existing.pmcid or candidate.pmcid,
        cited_by_count=max(existing.cited_by_count, candidate.cited_by_count),
        is_open_access=existing.is_open_access or candidate.is_open_access,
        license=existing.license or candidate.license,
        has_pdf=existing.has_pdf or candidate.has_pdf,
        has_structured_fulltext=existing.has_structured_fulltext
        or candidate.has_structured_fulltext,
        has_local_fulltext=existing.has_local_fulltext or candidate.has_local_fulltext,
        is_retracted=existing.is_retracted or candidate.is_retracted,
        providers=tuple(dict.fromkeys((*existing.providers, *candidate.providers))),
        matched_query_ids=tuple(
            dict.fromkeys((*existing.matched_query_ids, *candidate.matched_query_ids))
        ),
        citation_relations=tuple(
            dict.fromkeys((*existing.citation_relations, *candidate.citation_relations))
        ),
    )


def _merge_named_entities(
    left_names: tuple[str, ...],
    left_ids: tuple[str, ...],
    right_names: tuple[str, ...],
    right_ids: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Merge display names while keeping each optional stable identifier aligned."""
    pairs: list[tuple[str, str]] = []
    for names, identifiers in ((left_names, left_ids), (right_names, right_ids)):
        for index, name in enumerate(names):
            cleaned = " ".join(str(name).split())
            identifier = str(identifiers[index]).strip() if index < len(identifiers) else ""
            if not cleaned:
                continue
            match = next(
                (
                    position
                    for position, (known_name, known_id) in enumerate(pairs)
                    if (identifier and known_id == identifier)
                    or (
                        known_name.casefold() == cleaned.casefold()
                        and (not identifier or not known_id)
                    )
                ),
                None,
            )
            if match is None:
                pairs.append((cleaned, identifier))
            elif identifier and not pairs[match][1]:
                pairs[match] = (pairs[match][0], identifier)
    return tuple(name for name, _ in pairs), tuple(identifier for _, identifier in pairs)


def screen_candidates(
    candidates: Iterable[PublicationCandidate],
    plan: ResearchPlan,
    *,
    limit: int = 30,
) -> tuple[PublicationCandidate, ...]:
    scored: list[PublicationCandidate] = []
    focus = plan_focus(plan)
    query_terms = _meaningful_tokens(" ".join(plan.concepts))
    for candidate in candidates:
        searchable = f"{candidate.title} {candidate.abstract}".lower()
        source_terms = set(_tokens(searchable))
        concept_hits = tuple(
            _concept_present(concept, plan, searchable, source_terms) for concept in plan.concepts
        )
        covered = sum(concept_hits)
        coverage = covered / max(1, len(plan.concepts))
        title_searchable = candidate.title.lower()
        title_terms = set(_tokens(title_searchable))
        title_covered = sum(
            _concept_present(concept, plan, title_searchable, title_terms)
            for concept in plan.concepts
        )
        title_coverage = title_covered / max(1, len(plan.concepts))
        term_overlap = len(query_terms & source_terms) / max(1, len(query_terms))
        query_diversity = min(1.0, len(candidate.matched_query_ids) / 2)
        processable = bool(
            candidate.has_local_fulltext
            or candidate.pmcid
            or candidate.is_open_access
            and (
                candidate.has_structured_fulltext
                or candidate.has_pdf
                or candidate.full_text_url
                or candidate.oa_landing_urls
            )
        )
        availability = (
            1.0
            if processable and (candidate.pmcid or candidate.has_structured_fulltext)
            else 0.65
            if processable
            else 0.2
            if candidate.is_open_access
            else 0.0
        )
        citation_signal = min(1.0, math.log1p(max(0, candidate.cited_by_count)) / math.log(101))
        score = round(
            coverage * 0.38
            + title_coverage * 0.25
            + term_overlap * 0.15
            + query_diversity * 0.08
            + availability * 0.1
            + citation_signal * 0.04,
            4,
        )
        coverage_ratio = 0.5 if plan.profile_id == "generic" else 0.67
        required_concepts = (
            len(plan.concepts)
            if len(plan.concepts) <= 2
            else math.ceil(len(plan.concepts) * coverage_ratio)
        )
        if candidate.is_retracted:
            status, reason = "excluded", "marked retracted by a discovery provider"
        elif any(_term_in_text(term, searchable) for term in plan.exclusion_terms):
            status, reason = (
                "excluded",
                "matches an explicit exclusion in the confirmed research brief",
            )
        elif (
            plan.profile_id == "generic"
            and plan.intent == "relationship"
            and concept_hits
            and not concept_hits[0]
        ):
            status, reason = (
                "excluded",
                f"the primary relationship subject {plan.concepts[0]!r} is absent from the metadata",
            )
        elif focus:
            # Metadata screening is a recall gate. A study about the outcome
            # may examine just one driver; full-text screening establishes scope.
            if not concept_hits[0]:
                status, reason = (
                    "excluded",
                    f"the explanatory subject {focus[0]!r} is absent from the metadata",
                )
            else:
                status = "selected" if processable else "unavailable"
                reason = "the explanatory subject is present; driver and geographic relevance require full-text screening"
        elif covered < required_concepts:
            status, reason = (
                "excluded",
                f"concept coverage {covered}/{len(plan.concepts)} is below the required {required_concepts}/{len(plan.concepts)}",
            )
        elif not candidate.abstract and coverage < 1:
            if processable and title_covered >= required_concepts:
                status = "selected"
                reason = (
                    f"title covered {title_covered}/{len(plan.concepts)} planned concepts and a processable full text is indicated; "
                    "abstract unavailable, so full-text evidence gates remain required"
                )
            else:
                status, reason = (
                    "uncertain",
                    "metadata matches, but no abstract is available for screening",
                )
        else:
            status = "selected" if processable else "unavailable"
            reason = (
                f"covered {covered}/{len(plan.concepts)} planned concepts; "
                f"matched {len(candidate.matched_query_ids)} search strategies; "
                + (
                    "processable full text indicated"
                    if status == "selected"
                    else "no downloadable full text indicated"
                )
                + ("; abstract unavailable" if not candidate.abstract else "")
            )
        scored.append(
            replace(
                candidate,
                relevance_score=score,
                concept_coverage=round(coverage, 4),
                screening_status=status,
                screening_reason=reason,
            )
        )
    ranked = sorted(
        scored,
        key=lambda item: (
            -item.relevance_score,
            -len(item.matched_query_ids),
            -item.cited_by_count,
            item.title.lower(),
        ),
    )
    selected_seen = 0
    result: list[PublicationCandidate] = []
    for candidate in ranked:
        if candidate.screening_status == "selected":
            selected_seen += 1
            if selected_seen > limit:
                candidate = replace(
                    candidate,
                    screening_status="not_selected",
                    screening_reason=f"ranked below the top-{limit} screening limit",
                )
        result.append(candidate)
    return tuple(result)


def relationship_metadata_present(candidate: PublicationCandidate, plan: ResearchPlan) -> bool:
    """Whether metadata covers the subject and at least one requested driver.

    This prioritizes acquisition, and does not replace full-text screening.
    """
    if plan.intent != "relationship" or not plan.subject_terms or not plan.driver_terms:
        return False
    searchable = f"{candidate.title} {candidate.abstract}".lower()
    source_terms = set(_tokens(searchable))
    return all(
        _concept_present(term, plan, searchable, source_terms) for term in plan.subject_terms
    ) and any(_concept_present(term, plan, searchable, source_terms) for term in plan.driver_terms)


def _concept_present(
    concept: str, plan: ResearchPlan, searchable: str, source_terms: set[str]
) -> bool:
    aliases = PROFILES[plan.profile_id].expand(concept)
    for alias in aliases:
        if _term_in_text(alias, searchable):
            return True
        alias_tokens = _tokens(alias)
        if len(alias_tokens) == 1 and any(
            _inflection_match(alias_tokens[0], source) for source in source_terms
        ):
            return True
        if len(alias_tokens) > 1 and _ordered_alias_match(alias, searchable):
            return True
    return False


def _ordered_alias_match(alias: str, text: str, *, maximum_gap: int = 3) -> bool:
    """Match multi-word concepts locally, not as unrelated words anywhere in metadata."""
    expected = re.findall(r"[a-z][a-z0-9]{1,}", alias.lower())
    available = re.findall(r"[a-z][a-z0-9]{1,}", text.lower())
    if not expected:
        return False
    for start, value in enumerate(available):
        if not _inflection_match(expected[0], value):
            continue
        position = start
        for token in expected[1:]:
            match = next(
                (
                    index
                    for index in range(
                        position + 1, min(len(available), position + maximum_gap + 2)
                    )
                    if _inflection_match(token, available[index])
                ),
                None,
            )
            if match is None:
                break
            position = match
        else:
            return True
    return False


def _dedupe_key(candidate: PublicationCandidate) -> str:
    if candidate.doi:
        return "doi:" + candidate.doi.lower().removeprefix("https://doi.org/").removeprefix(
            "http://doi.org/"
        )
    normalized = re.sub(r"[^a-z0-9]+", " ", candidate.title.lower()).strip()
    return "title:" + normalized


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z][a-z0-9-]{1,}", text.lower()))


def _meaningful_tokens(text: str) -> set[str]:
    stop = {"about", "and", "evidence", "for", "from", "result", "results", "study", "the", "with"}
    return {token for token in _tokens(text) if token not in stop}


def _term_in_text(term: str, text: str) -> bool:
    return concept_present(text, term)


def _inflection_match(left: str, right: str) -> bool:
    return (
        left == right
        or min(len(left), len(right)) >= 4
        and (left.startswith(right) or right.startswith(left))
    )
