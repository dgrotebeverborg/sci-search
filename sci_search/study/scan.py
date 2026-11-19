"""The grounding scan: what exists for a question, gathered before any plan is written.

Reuses the main app's interpretation, scholarly discovery and dataset discovery. Each
step stands alone: a failed step is recorded and the scan continues.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from typing import Any

from sci_search.data_research.discovery import discover
from sci_search.discovery import PublicationCandidate, SearchQuery, merge_candidates
from sci_search.question_interpretation import interpret_question
from sci_search.question_planning import plan_from_brief, plan_question

STUDIES = 30
MODELS = 10
PER_QUERY = 15
ABSTRACT = 600
_EXPECTED = (OSError, ValueError, KeyError, TimeoutError, TypeError)


def default_providers() -> tuple[Any, ...]:
    from sci_search.configuration import require_openalex_key
    from sci_search.scholarly_providers import CrossrefProvider, EuropePmcProvider, OpenAlexProvider

    email = os.environ.get("CROSSREF_EMAIL") or os.environ.get("UNPAYWALL_EMAIL")
    return (
        OpenAlexProvider(require_openalex_key()),
        EuropePmcProvider(),
        CrossrefProvider(email=email),
    )


def _search(queries: Iterable[SearchQuery], providers) -> list[PublicationCandidate]:
    from sci_search.scholarly_providers import discover_with_providers

    found, _log = discover_with_providers(tuple(queries), tuple(providers), per_query=PER_QUERY)
    return list(found)


def _key(title: str, doi: str | None) -> str:
    return (doi or "").lower() or re.sub(r"\W+", " ", title.lower()).strip()


def _publication(candidate: PublicationCandidate, kind: str) -> dict[str, Any]:
    url = candidate.source_url or (f"https://doi.org/{candidate.doi}" if candidate.doi else None)
    return {
        "title": candidate.title,
        "year": candidate.year,
        "doi": candidate.doi,
        "url": url,
        "abstract": (candidate.abstract or "")[:ABSTRACT],
        "cited_by_count": candidate.cited_by_count,
        "kind": kind,
    }


def _ranked(candidates: list[PublicationCandidate], limit: int) -> list[PublicationCandidate]:
    merged = merge_candidates(candidates)
    return sorted(merged, key=lambda c: c.cited_by_count, reverse=True)[:limit]


def _number(items: list[dict[str, Any]], prefix: str, start: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}{start + i}", **item} for i, item in enumerate(items)]


def _closest_brief(interpretation: dict[str, Any]) -> dict[str, Any]:
    for option in interpretation.get("options") or []:
        if option.get("closest") and isinstance(option.get("brief"), dict):
            return option["brief"]
    return {
        k: v for k, v in interpretation.items() if k not in {"options", "clarification_options"}
    }


def _datasets(found: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "title": str(c.get("title") or ""),
            "url": c.get("url") or c.get("landing_url"),
            "publisher": c.get("publisher"),
            "rationale": c.get("rationale"),
        }
        for c in found.get("candidates") or []
        if isinstance(c, dict) and c.get("title")
    ]


def run_scan(
    question: str,
    *,
    interpret: Callable[[str], dict[str, Any]] = interpret_question,
    providers=None,
    find_datasets: Callable[..., dict[str, Any]] = discover,
    progress: Callable[[str], None] = lambda message: None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    def step(name: str, status: str, detail: str = "") -> None:
        steps.append({"name": name, "status": status, "detail": detail})

    progress("Interpreting the question.")
    brief: dict[str, Any] = {}
    understood = question
    try:
        brief = _closest_brief(interpret(question))
        understood = str(brief.get("interpreted_question") or question)
        step("interpretation", "ok")
    except _EXPECTED as error:
        step("interpretation", "failed", str(error))

    studies: list[PublicationCandidate] = []
    models: list[PublicationCandidate] = []
    try:
        providers = providers if providers is not None else default_providers()
        from sci_search.discovery import plan_search_queries

        try:
            base = plan_from_brief(question, brief or None)
        except ValueError:
            # An ambiguous or partial brief still gets a plain search for the understood question.
            base = plan_question(understood)
        plan, queries = plan_search_queries(understood, plan=base)
        progress(f"Searching publications ({len(queries)} queries).")
        studies = _ranked(_search(queries, providers), STUDIES)
        step("publications", "ok", f"{len(studies)} kept")
        core = " ".join((plan.subject_terms or plan.concepts)[:4]) or understood
        model_queries = (
            SearchQuery("models-1", f"{core} model", "existing models"),
            SearchQuery("models-2", f"{core} scenario study", "existing models"),
        )
        progress("Searching existing models and scenario studies.")
        seen = {_key(c.title, c.doi) for c in studies}
        models = [
            c
            for c in _ranked(_search(model_queries, providers), MODELS * 2)
            if _key(c.title, c.doi) not in seen
        ][:MODELS]
        step("models", "ok", f"{len(models)} kept")
    except _EXPECTED as error:
        for name in ("publications", "models"):
            if name not in {s["name"] for s in steps}:
                step(name, "failed", str(error))

    datasets: list[dict[str, Any]] = []
    strategy = brief.get("data_research") if isinstance(brief.get("data_research"), dict) else None
    if not strategy or strategy.get("route") == "literature":
        step("datasets", "skipped", "The interpretation does not call for data.")
    else:
        progress("Looking for datasets.")
        try:
            datasets = _datasets(find_datasets(understood, strategy))
            step("datasets", "ok", f"{len(datasets)} found")
        except _EXPECTED as error:
            step("datasets", "failed", str(error))

    publications = [_publication(c, "study") for c in studies] + [
        _publication(c, "model") for c in models
    ]
    progress("Scan finished.")
    return {
        "interpretation": {"question": understood, "brief": brief},
        "publications": _number(publications, "P", 1),
        "datasets": _number(datasets, "D", 1),
        "steps": steps,
    }


def extend_scan(
    scan: dict[str, Any],
    terms: list[str],
    *,
    providers=None,
    find_datasets: Callable[..., dict[str, Any]] = discover,
    progress: Callable[[str], None] = lambda message: None,
) -> dict[str, Any]:
    """Search more for the given terms; new items get continuing ids, duplicates are skipped."""
    terms = [t.strip() for t in terms if t.strip()]
    if not terms:
        raise ValueError("Give at least one search term.")
    publications = list(scan.get("publications") or [])
    datasets = list(scan.get("datasets") or [])
    steps = list(scan.get("steps") or [])
    providers = providers if providers is not None else default_providers()
    progress("Searching publications for: " + ", ".join(terms))
    queries = [SearchQuery(f"extra-{i}", term, "extra search") for i, term in enumerate(terms, 1)]
    seen = {_key(p.get("title") or "", p.get("doi")) for p in publications}
    added = []
    try:
        for candidate in _ranked(_search(queries, providers), STUDIES):
            key = _key(candidate.title, candidate.doi)
            if key not in seen:
                seen.add(key)
                added.append(_publication(candidate, "study"))
        steps.append({"name": "extra publications", "status": "ok", "detail": ", ".join(terms)})
    except _EXPECTED as error:
        steps.append({"name": "extra publications", "status": "failed", "detail": str(error)})
    publications += _number(added, "P", len(publications) + 1)

    brief = (scan.get("interpretation") or {}).get("brief") or {}
    strategy = brief.get("data_research") if isinstance(brief.get("data_research"), dict) else None
    if strategy and strategy.get("route") != "literature":
        progress("Looking for datasets for: " + ", ".join(terms))
        try:
            found = _datasets(find_datasets(", ".join(terms), strategy))
            known = {(d.get("url") or d.get("title")) for d in datasets}
            new = [d for d in found if (d.get("url") or d.get("title")) not in known]
            datasets += _number(new, "D", len(datasets) + 1)
            steps.append({"name": "extra datasets", "status": "ok", "detail": ", ".join(terms)})
        except _EXPECTED as error:
            steps.append({"name": "extra datasets", "status": "failed", "detail": str(error)})
    return {**scan, "publications": publications, "datasets": datasets, "steps": steps}
