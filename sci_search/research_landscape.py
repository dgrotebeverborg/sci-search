"""Deterministic bibliometric landscape over a research run's candidate ledger."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

_TOKEN = re.compile(r"[a-z][a-z0-9-]{3,}")
_STOPWORDS = {
    "about",
    "after",
    "against",
    "among",
    "analysis",
    "based",
    "between",
    "could",
    "effect",
    "effects",
    "evidence",
    "from",
    "have",
    "into",
    "investigation",
    "more",
    "application",
    "approach",
    "assessment",
    "development",
    "experiment",
    "method",
    "model",
    "paper",
    "performance",
    "research",
    "results",
    "review",
    "study",
    "studies",
    "their",
    "these",
    "through",
    "using",
    "with",
    "without",
    "which",
    "were",
    "what",
    "when",
    "where",
}


def build_research_landscape(investigation: dict[str, Any]) -> dict[str, Any]:
    """Describe the discovered subject corpus without presenting it as exhaustive."""
    run = (
        investigation.get("research_run")
        if isinstance(investigation.get("research_run"), dict)
        else {}
    )
    raw_records = run.get("candidates") if isinstance(run.get("candidates"), list) else []
    population = [item for item in raw_records if isinstance(item, dict) and item.get("id")]
    population_kind = "deduplicated_discovery_candidate_ledger"
    if not population:
        population = [
            _publication_record(item)
            for item in investigation.get("publications", [])
            if isinstance(item, dict) and item.get("id")
        ]
        population_kind = "configured_full_text_corpus"

    timeline = Counter(
        int(item["year"])
        for item in population
        if isinstance(item.get("year"), int) and 1500 <= int(item["year"]) <= 2200
    )
    authors, author_coverage = _rank_people(population)
    organizations, organization_coverage = _rank_organizations(population)
    types = Counter(str(item.get("publication_type") or "unknown") for item in population)
    providers = Counter(
        provider
        for item in population
        for provider in set(item.get("providers") or [])
        if str(provider).strip()
    )
    selected = sum(item.get("screening_status") == "selected" for item in population)
    acquired_ids = set(run.get("active_publication_ids") or [])
    full_text_count = len(acquired_ids) if raw_records else len(population)
    cited_ids = {
        str(item.get("publication_id"))
        for item in investigation.get("evidence", [])
        if isinstance(item, dict) and item.get("publication_id")
    }
    complete_year = datetime.now(UTC).year - 1
    eligible_years = [year for year in timeline if year <= complete_year]
    anchor_year = max(eligible_years, default=complete_year)
    recent = (anchor_year - 2, anchor_year)
    baseline = (anchor_year - 5, anchor_year - 3)
    term_signals = _term_signals(population, baseline, recent)
    influential = sorted(
        (
            {
                "publication_id": str(item["id"]),
                "title": str(item.get("title") or "Untitled"),
                "year": item.get("year"),
                "cited_by_count": int(item.get("cited_by_count") or 0),
                "source_url": item.get("source_url"),
            }
            for item in population
            if int(item.get("cited_by_count") or 0) > 0
        ),
        key=lambda item: (-item["cited_by_count"], str(item["title"]).casefold()),
    )[:10]
    limitations = [
        "Counts describe the records returned by this recorded search, not every publication in the field.",
        "Author counts use provider IDs when available and normalized names otherwise; unresolved homonyms and name variants may remain.",
        "Organization counts use provider-supplied canonical institutions only. Raw affiliation strings are retained but are not counted as organizations.",
        "Citation counts are provider snapshots and should not be interpreted as evidence quality.",
    ]
    if timeline and max(timeline) > anchor_year:
        limitations.append(
            f"The incomplete {max(timeline)} publication year is shown in the timeline but excluded from trend windows."
        )
    if not organizations:
        limitations.append(
            "No canonical institution metadata was available in this corpus, so organization rankings are omitted."
        )

    return {
        "schema_version": "research_landscape_v1",
        "population_definition": population_kind,
        "question": investigation.get("question"),
        "coverage": {
            "records": len(population),
            "with_year": sum(bool(item.get("year")) for item in population),
            "with_authors": author_coverage,
            "with_canonical_organizations": organization_coverage,
            "selected_for_acquisition": selected,
            "full_texts_acquired": full_text_count,
            "publications_cited_in_review": len(cited_ids),
        },
        "publication_timeline": [
            {"year": year, "publications": timeline[year]} for year in sorted(timeline)
        ],
        "top_authors": authors[:15],
        "top_organizations": organizations[:15],
        "publication_types": _counter_rows(types, "type"),
        "discovery_providers": _counter_rows(providers, "provider"),
        "most_cited_in_discovered_set": influential,
        "trend_method": {
            "baseline_from": baseline[0],
            "baseline_to": baseline[1],
            "recent_from": recent[0],
            "recent_to": recent[1],
            "description": (
                "Title-term signals compare two complete three-year windows. Emerging requires at most 2 baseline records, "
                "at least 6 recent records, a gain of at least 3, and records in at least 2 recent years. Growing uses the "
                "same floors plus a baseline of at least 3 and at least 25% growth; declining requires at least 6 baseline "
                "records and a fall of at least 3 and 25%. All other displayed terms are stable."
            ),
        },
        "title_term_signals": term_signals,
        "limitations": limitations,
    }


def _publication_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "year": item.get("year"),
        "authors": item.get("authors") or [],
        "publication_type": item.get("document_type") or "article",
        "institutions": item.get("institutions") or [],
        "providers": ["local_corpus"],
        "screening_status": "selected",
        "cited_by_count": 0,
        "source_url": item.get("source_url"),
    }


def _rank_people(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    covered = 0
    for item in records:
        identifiers = list(item.get("author_ids") or [])
        names = {
            (
                str(identifiers[index]).strip()
                if index < len(identifiers) and str(identifiers[index]).strip()
                else _normalized_name(value)
            ): " ".join(str(value).split())
            for index, value in enumerate(item.get("authors") or [])
            if str(value).strip()
        }
        if names:
            covered += 1
        for key, value in names.items():
            counts[key] += 1
            display.setdefault(key, value)
    return (
        [
            {
                "author_id": key if key.startswith(("http://", "https://")) else None,
                "name": display[key],
                "publications": count,
            }
            for key, count in counts.most_common()
        ],
        covered,
    )


def _rank_organizations(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    covered = 0
    for item in records:
        identifiers = list(item.get("institution_ids") or [])
        names = {
            (
                str(identifiers[index]).strip()
                if index < len(identifiers) and str(identifiers[index]).strip()
                else _normalized_name(value)
            ): " ".join(str(value).split())
            for index, value in enumerate(item.get("institutions") or [])
            if str(value).strip()
        }
        if names:
            covered += 1
        for key, value in names.items():
            counts[key] += 1
            display.setdefault(key, value)
    return (
        [
            {
                "organization_id": key if key.startswith(("http://", "https://")) else None,
                "name": display[key],
                "publications": count,
            }
            for key, count in counts.most_common()
        ],
        covered,
    )


def _normalized_name(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def _counter_rows(values: Counter[str], label: str) -> list[dict[str, Any]]:
    return [{label: key, "publications": count} for key, count in values.most_common()]


def _term_signals(
    records: list[dict[str, Any]],
    baseline: tuple[int, int],
    recent: tuple[int, int],
) -> list[dict[str, Any]]:
    publications: dict[str, set[str]] = defaultdict(set)
    years: dict[str, list[int]] = defaultdict(list)
    supporting: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        year = item.get("year")
        if not isinstance(year, int) or year < baseline[0] or year > recent[1]:
            continue
        tokens = [
            token
            for token in _TOKEN.findall(str(item.get("title") or "").casefold())
            if token not in _STOPWORDS
        ]
        terms = set(tokens)
        terms.update(f"{left} {right}" for left, right in zip(tokens, tokens[1:], strict=False))
        for term in terms:
            publications[term].add(str(item["id"]))
            years[term].append(year)
            if recent[0] <= year <= recent[1] and len(supporting[term]) < 2:
                supporting[term].append(
                    {"publication_id": str(item["id"]), "title": item.get("title"), "year": year}
                )
    rows = []
    for term, ids in publications.items():
        baseline_count = sum(baseline[0] <= year <= baseline[1] for year in years[term])
        recent_count = sum(recent[0] <= year <= recent[1] for year in years[term])
        change = recent_count - baseline_count
        recent_years = len({year for year in years[term] if recent[0] <= year <= recent[1]})
        if len(ids) < 3 or recent_count < 2:
            continue
        if baseline_count <= 2 and recent_count >= 6 and change >= 3 and recent_years >= 2:
            signal = "emerging"
        elif (
            baseline_count >= 3
            and recent_count >= 6
            and change >= 3
            and change / baseline_count >= 0.25
            and recent_years >= 2
        ):
            signal = "growing"
        elif baseline_count >= 6 and change <= -3 and change / baseline_count <= -0.25:
            signal = "declining"
        else:
            signal = "stable"
        rows.append(
            {
                "term": term,
                "baseline_publications": baseline_count,
                "recent_publications": recent_count,
                "absolute_change": change,
                "classification": signal,
                "supporting_publications": supporting[term],
            }
        )
    priority = {"emerging": 0, "growing": 1, "declining": 2, "stable": 3}
    rows.sort(
        key=lambda item: (
            priority[item["classification"]],
            -abs(item["absolute_change"]),
            -item["recent_publications"],
            item["term"],
        )
    )
    return rows[:12]
