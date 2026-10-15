"""Plain-language summary of a saved result: the answer, how certain it is, and why.

A pure function over a dashboard snapshot. It makes no model calls and never changes evidence.
"""

from __future__ import annotations

import re
from typing import Any

MAX_SOURCES = 5
MAX_LEFT_OUT = 10
LABELS = {
    "strong": "Strong evidence",
    "moderate": "Moderate evidence",
    "weak": "Weak evidence",
    "insufficient": "Not enough evidence",
    "not_assessed": "Not assessed",
}
DECISIONS = {"excluded": "Excluded", "uncertain": "Needs review", "background": "Background only"}
COVERAGE_KINDS = {"geography", "subject", "subject_part", "population", "time", "outcome", "topic"}
TREND_CHECKS = {"temporal_nature", "directional_trend", "multi_period_trend"}


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    blocks = {
        b.get("id"): b.get("data") if isinstance(b.get("data"), (dict, list)) else {}
        for b in snapshot.get("blocks") or []
        if isinstance(b, dict)
    }
    question = str(snapshot.get("question") or "")
    answer = _dict(blocks.get("answer"))
    adequacy = _dict(answer.get("answer_adequacy"))
    data = _dict(answer.get("data_analysis"))
    scope = _dict(_dict(blocks.get("scope")).get("research_scope"))
    landscape = _dict(blocks.get("landscape"))
    studies = [s for s in _dict(blocks.get("studies")).get("studies") or [] if isinstance(s, dict)]
    references = [r for r in blocks.get("references") or [] if isinstance(r, dict)]
    evidence = [e for e in blocks.get("evidence") or [] if isinstance(e, dict)]
    documents = _dict(snapshot.get("documents"))

    included = [_study(s, documents) for s in studies if _decision(s) == "included"]
    missing = _missing(adequacy, scope, question)
    data_part = _data(data) if data else None
    return {
        "answer": _answer(answer),
        "certainty": _certainty(
            _dict(snapshot.get("result_quality")),
            adequacy,
            scope,
            data_part,
            included,
            missing,
            question,
        ),
        "key_sources": _key_sources(answer, evidence, references, data_part, documents),
        "data": data_part,
        "literature": _literature(studies, landscape)
        if any(_decision(s) for s in studies)
        else None,
        "included": included,
        "left_out": _left_out(studies, documents),
        "missing": missing,
        "landscape_line": _landscape_line(landscape, len(included)),
    }


def _int(value: Any, default: int = 0) -> int:
    """A count from a saved result; malformed values fall back instead of raising."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _decision(study: dict[str, Any]) -> str:
    return str(_dict(study.get("screening")).get("decision") or "")


def _as_written(label: str, question: str) -> str:
    """The label as the researcher wrote it ("united kingdom" -> "United Kingdom")."""
    match = re.search(re.escape(label), question, re.IGNORECASE) if label else None
    return match.group(0) if match else label


def _place(label: str, question: str) -> str:
    written = _as_written(label, question)
    article = re.search(rf"\b(the)\s+{re.escape(written)}", question, re.IGNORECASE)
    return f"the {written}" if article else written


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _answer(answer: dict[str, Any]) -> dict[str, Any] | None:
    summary = _dict(answer.get("executive_summary"))
    if not summary.get("text"):
        return None
    return {"text": str(summary["text"]), "evidence_ids": list(summary.get("evidence_ids") or [])}


def _url(item: dict[str, Any], documents: dict[str, Any]) -> str | None:
    if item.get("source_url"):
        return str(item["source_url"])
    if item.get("doi"):
        return "https://doi.org/" + str(item["doi"])
    publication = str(item.get("publication_id") or item.get("id") or "")
    return _dict(documents.get(publication)).get("url")


def _study(study: dict[str, Any], documents: dict[str, Any]) -> dict[str, Any]:
    decision = _decision(study)
    return {
        "title": str(study.get("title") or "Untitled publication"),
        "year": study.get("year"),
        "url": _url(study, documents),
        "decision": DECISIONS.get(decision, "Counted as evidence"),
        "reason": str(_dict(study.get("screening")).get("reason") or ""),
    }


def _left_out(studies: list[dict[str, Any]], documents: dict[str, Any]) -> list[dict[str, Any]]:
    order = {"excluded": 0, "uncertain": 0, "background": 1}
    read = [s for s in studies if _decision(s) in order]
    read.sort(key=lambda s: order[_decision(s)])
    return [_study(s, documents) for s in read[:MAX_LEFT_OUT]]


def _missing(adequacy: dict[str, Any], scope: dict[str, Any], question: str) -> list[str]:
    drivers = set(_dict(scope.get("requirements")).get("alternative_driver_dimensions") or [])
    sentences: list[str] = []
    explained: set[str] = set()
    for check in adequacy.get("checks") or []:
        if not isinstance(check, dict) or check.get("passed") or not check.get("required", True):
            continue
        identifier = str(check.get("id") or "").removeprefix("coverage:")
        label = str(check.get("label") or "")
        if not identifier and not label:
            continue
        explained.add(label.casefold())
        kind = check.get("kind")
        if identifier in drivers:
            text = f"No included study links {_as_written(label, question)} to the outcome."
        elif kind == "geography":
            text = f"No included study covers {_place(label, question)}."
        elif kind == "time":
            text = f"No included study covers the requested period ({label})."
        elif kind in COVERAGE_KINDS:
            text = f"No included study covers {_as_written(label, question)}."
        elif identifier == "independent_publications":
            count, minimum = (
                _int(check.get("publication_count")),
                _int(check.get("minimum"), 1) or 1,
            )
            text = (
                "No single passage answers the whole question."
                if not count
                else f"{count} of {minimum} required studies answer the whole question."
            )
        elif identifier in TREND_CHECKS:
            text = "No study reports a change over time for the requested period."
        else:
            text = (label[:1].upper() + label[1:]).rstrip(".") + "."
        if text not in sentences:
            sentences.append(text)
    # Older results record a missing requirement without a matching labelled check.
    for requirement in adequacy.get("missing_requirements") or []:
        label = str(requirement).strip()
        text = f"{label[:1].upper()}{label[1:]} is missing."
        if label and label.casefold() not in explained and text not in sentences:
            sentences.append(text)
    return sentences


def _certainty(quality, adequacy, scope, data_part, included, missing, question) -> dict[str, Any]:
    status = quality.get("status")
    contributing = _int(adequacy.get("qualifying_publications"))
    if status == "adequate":
        level = "strong"
    elif status == "insufficient":
        level = "insufficient"
    elif status == "partial":
        checks = [c for c in adequacy.get("checks") or [] if isinstance(c, dict)]
        failed = [c for c in checks if c.get("required", True) and not c.get("passed")]
        independent = next(
            (c for c in checks if c.get("id") == "coverage:independent_publications"), {}
        )
        minimum = _int(independent.get("minimum")) or _int(
            _dict(scope.get("requirements")).get("minimum_independent_publications"), 1
        )
        moderate = contributing >= max(1, minimum) and len(failed) <= 1
        level = "moderate" if moderate else "weak"
    else:
        level = "not_assessed"
    if level == "not_assessed":
        sentence = "The evidence for this saved result was not assessed."
    else:
        sentence = _sentence(adequacy, data_part, included, contributing, missing, question)
    return {"level": level, "label": LABELS[level], "sentence": sentence}


def _sentence(adequacy, data_part, included, contributing, missing, question) -> str:
    leads = []
    datasets = (data_part or {}).get("datasets") or []
    if datasets:
        first = datasets[0]
        detail = ", ".join(
            p
            for p in (
                ", ".join(first.get("entities") or []),
                f"{first['first_year']}–{first['last_year']}" if first.get("first_year") else "",
            )
            if p
        )
        leads.append(
            _plural(len(datasets), "dataset") + " analysed" + (f" ({detail})" if detail else "")
        )
    if included:
        covered = [
            _place(str(c.get("label") or ""), question)
            for c in adequacy.get("checks") or []
            if isinstance(c, dict) and c.get("kind") == "geography" and c.get("publication_count")
        ]
        one = len(included) == 1
        leads.append(
            f"{len(included)} {'study counts' if one else 'studies count'} as evidence"
            + (f", covering {_join(covered)}" if covered else "")
        )
    if not included and contributing:
        # Older results record contributing publications without screening decisions.
        noun = "publication contributes" if contributing == 1 else "publications contribute"
        leads.append(f"{contributing} {noun} to the answer")
    lead = " and ".join(leads) or "No study or dataset answers the question directly"
    gaps = [m[:1].lower() + m[1:-1] for m in missing[:2]]
    return "; ".join([lead, *gaps]) + "."


def _series(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    series = list(analysis.get("series") or [])
    for component in analysis.get("components") or []:
        series += _dict(component).get("series") or []
    return [s for s in series if isinstance(s, dict)]


def _data(data: dict[str, Any]) -> dict[str, Any]:
    datasets = []
    for analysis in data.get("analyses") or []:
        if not isinstance(analysis, dict):
            continue
        source = _dict(analysis.get("source"))
        series = _series(analysis)
        years = [
            int(row["year"])
            for s in series
            for row in s.get("annual") or []
            if isinstance(row, dict) and isinstance(row.get("year"), int)
        ]
        entities = list(
            dict.fromkeys(str(s.get("entity") or "").split(":")[0].strip() for s in series)
        )
        datasets.append(
            {
                "title": str(source.get("title") or "Dataset"),
                "publisher": source.get("publisher"),
                "url": source.get("url"),
                "kind": "dataset",
                "year": None,
                "entities": [e for e in entities if e][:8],
                "first_year": min(years) if years else None,
                "last_year": max(years) if years else None,
                "unit": next((s.get("unit") for s in series if s.get("unit")), None),
            }
        )
    not_used = sum(
        1
        for a in data.get("assessments") or []
        if isinstance(a, dict) and a.get("decision") != "analysed"
    )
    return {"datasets": datasets, "not_used": not_used}


def _key_sources(answer, evidence, references, data_part, documents) -> list[dict[str, Any]]:
    sources = list((data_part or {}).get("datasets") or [])
    publication_of = {str(e.get("id")): str(e.get("publication_id")) for e in evidence}
    cited = [
        publication_of.get(str(i))
        for i in _dict(answer.get("executive_summary")).get("evidence_ids") or []
    ]
    passages = [str(e.get("publication_id")) for e in evidence]
    ranked = sorted(
        references,
        key=lambda r: (
            -cited.count(str(r.get("publication_id"))),
            -passages.count(str(r.get("publication_id"))),
            r.get("number") or 0,
        ),
    )
    for reference in ranked:
        sources.append(
            {
                "title": str(reference.get("title") or "Untitled publication"),
                "year": reference.get("year"),
                "publisher": None,
                "url": _url(reference, documents),
                "kind": "publication",
            }
        )
    return sources[:MAX_SOURCES]


def _literature(studies: list[dict[str, Any]], landscape: dict[str, Any]) -> dict[str, int]:
    coverage = _dict(landscape.get("coverage"))
    decisions = [_decision(s) for s in studies]
    read = [d for d in decisions if d in {"included", "excluded", "uncertain", "background"}]
    return {
        "found": _int(coverage.get("records")) or len(studies),
        "full_texts": _int(coverage.get("full_texts_acquired")) or len(read),
        "included": decisions.count("included"),
        "uncertain": decisions.count("uncertain"),
        "background": decisions.count("background"),
        "excluded": decisions.count("excluded"),
    }


def _landscape_line(landscape: dict[str, Any], included: int) -> str | None:
    records = _int(_dict(landscape.get("coverage")).get("records"))
    if not records:
        return None
    years = [
        int(row["year"])
        for row in landscape.get("publication_timeline") or []
        if isinstance(row, dict) and str(row.get("year", "")).isdigit()
    ]
    span = f", {min(years)}–{max(years)}" if years else ""
    found = f"{records} {'study' if records == 1 else 'studies'}"
    counted = "none count" if not included else "1 counts" if included == 1 else f"{included} count"
    return f"{found} found{span}; {counted} as evidence."
