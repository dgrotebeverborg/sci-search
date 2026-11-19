"""Plain-language summary of a saved result: the answer, how certain it is, and why.

A pure function over a dashboard snapshot. It makes no model calls and never changes evidence.
"""

from __future__ import annotations

import re
from typing import Any

MAX_SOURCES = 5
MAX_LEFT_OUT = 10
MAX_FINDINGS = 8
MAX_MISSING = 3
MAX_CLOSEST = 3
NO_ANSWER = "No direct answer was found."
PARTS_ONLY = "No study answers the whole question; the closest findings are below."
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
    data_part = _data(data) if data else None
    gaps = _data_gaps(data, {f["measurement"] for f in data_part["findings"]}) if data_part else []
    measured = bool(data_part and data_part["findings"])
    # A measured answer is not contradicted by gaps in the literature it never needed.
    missing = gaps if measured else _missing(adequacy, scope, question) + gaps
    certainty = _certainty(
        _dict(snapshot.get("result_quality")),
        adequacy,
        scope,
        data_part,
        included,
        missing,
        question,
    )
    if measured:
        certainty = _measured_certainty(data_part, gaps, included)
    headline = _headline(_answer(answer), data_part, certainty["level"])
    closest = _closest(answer, data) if headline["kind"] == "none" else []
    if any(item["quote"] for item in closest):
        headline = {"kind": "none", "text": PARTS_ONLY}
    if headline["kind"] == "none" and included:
        many = len(included) != 1
        certainty["sentence"] = (
            f"{_plural(len(included), 'study')} {'are' if many else 'is'} relevant, "
            "but none answers the question directly."
        ).replace("studys", "studies")
    if data_part:
        data_part.pop("_trends", None)
    literature_answer = headline["kind"] == "literature"
    return {
        "headline": headline,
        "answer": _answer(answer),
        "certainty": certainty,
        "closest": closest,
        "key_sources": _key_sources(answer, evidence, references, documents)
        if literature_answer
        else [],
        "data": data_part,
        "literature": _literature(studies, landscape)
        if any(_decision(s) for s in studies)
        else None,
        "included": included,
        "left_out": _left_out(studies, documents),
        "missing": missing[:MAX_MISSING],
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


# Navigation phrases from older data summaries; the page layout already says where to look.
_POINTERS = re.compile(
    r"\s*(?:Inspect the measurements, coverage and source decisions below|"
    r"See the series and source decisions below|"
    r"Source decisions and access limitations are shown below)\.",
)


def _answer(answer: dict[str, Any]) -> dict[str, Any] | None:
    summary = _dict(answer.get("executive_summary"))
    if not summary.get("text"):
        return None
    text = _POINTERS.sub("", str(summary["text"])).strip()
    return {"text": text, "evidence_ids": list(summary.get("evidence_ids") or [])}


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
        if len(label) > 60:
            continue
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
            # How many studies answer it is what the certainty already says.
            continue
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
    # What is missing is listed right under this sentence, so it is not repeated here.
    return (" and ".join(leads) or "No study or dataset answers the question directly") + "."


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
            dict.fromkeys(
                _clean_entity(str(s.get("entity") or "")).split(":")[0].strip() for s in series
            )
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
    findings, trends = _findings(data)
    return {
        "datasets": datasets,
        "not_used": not_used,
        "findings": findings[:MAX_FINDINGS],
        "more_findings": max(0, len(findings) - MAX_FINDINGS),
        # Used for the headline only; not part of the stored summary.
        "_trends": trends,
    }


def _number(value: float) -> str:
    """English-formatted value for a sentence: 93,297 · 4.6 · 0.032."""
    if abs(value) >= 100:
        return f"{value:,.0f}"
    return f"{value:,.3g}" if abs(value) < 1 else f"{value:,.1f}".removesuffix(".0")


def _findings(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """First and last observed value of every analysed series, as the headline numbers."""
    findings: list[dict[str, Any]] = []
    trends: list[dict[str, Any]] = []
    seen: set[str] = set()
    for analysis in data.get("analyses") or []:
        if not isinstance(analysis, dict):
            continue
        units = _dict(
            _dict(_dict(analysis.get("preparation")).get("selection")).get("code_labels")
        ).get("unit")
        for series in _series(analysis):
            rows = [
                r
                for r in series.get("annual") or []
                if isinstance(r, dict)
                and isinstance(r.get("year"), int)
                and isinstance(r.get("value"), (int, float))
                and not isinstance(r.get("value"), bool)
            ]
            if not rows:
                continue
            first, last = rows[0], rows[-1]
            unit = _unit(str(series.get("unit") or ""), _dict(units))
            entity = _clean_entity(str(series.get("entity") or ""))
            label = str(series.get("label") or "").strip()
            name = entity if entity and entity != label else label
            if first["year"] == last["year"]:
                text = f"{name}: {_number(last['value'])} {unit} in {last['year']}"
            else:
                text = (
                    f"{name}: {_number(first['value'])} → {_number(last['value'])} {unit} "
                    f"({first['year']}–{last['year']})"
                )
                change = series.get("change_percent")
                ratio = last["value"] / first["value"] if first["value"] > 0 else 0
                if unit.strip() == "%":
                    # A share changes in percentage points, not in multiples of itself.
                    points = last["value"] - first["value"]
                    text += f", {'+' if points > 0 else ''}{_number(points)} percentage points"
                elif ratio >= 5:
                    # A huge percentage from a tiny start says nothing; the ratio does.
                    text += f", {_number(ratio)} times as high"
                elif isinstance(change, (int, float)) and not isinstance(change, bool):
                    text += f", {'+' if change > 0 else ''}{_number(change)}%"
            finding = {"text": " ".join(text.split()), "measurement": label}
            # Analyses repeat their series per component.
            if finding not in findings and text not in seen:
                seen.add(text)
                findings.append(finding)
                trends.append(
                    {
                        "entity": entity,
                        "label": label,
                        "unit": unit,
                        "first": first,
                        "last": last,
                    }
                )
    return findings, trends


def _data_gaps(data: dict[str, Any], measured: set[str] = frozenset()) -> list[str]:
    """Missing data per measurement; many places with the same gap become one sentence."""
    cells = [c for c in _dict(data.get("coverage")).get("cells") or [] if isinstance(c, dict)]
    totals: dict[str, int] = {}
    groups: dict[tuple[str, str], list[str]] = {}
    for cell in cells:
        what = str(cell.get("measurement") or "").strip()
        totals[what] = totals.get(what, 0) + 1
        if cell.get("status") in {"complete", None} or not what:
            continue
        status = "partial" if cell.get("status") == "partial" else "missing"
        groups.setdefault((what, status), []).append(str(cell.get("entity") or "").strip())
    sentences = []
    for (what, status), places in groups.items():
        places = [p for p in places if p]
        if len(places) > 2:
            where = f" in {len(places)} of {totals[what]} places"
        else:
            where = f" ({_join(places)})" if places else ""
        if status == "partial":
            sentences.append(f"Data are incomplete for {what}{where}.")
        elif what not in measured and len(places) == totals[what]:
            sentences.append(f"No usable data were found for {what}.")
        elif len(places) == totals[what]:
            sentences.append(f"No separate figures per place for {what}; only the total.")
        elif len(places) > 2:
            sentences.append(
                f"{len(places)} of {totals[what]} requested places have no usable data for {what}."
            )
        else:
            sentences.append(f"No usable data were found for {what}{where}.")
    return sentences


def _key_sources(answer, evidence, references, documents) -> list[dict[str, Any]]:
    """Publications the answer rests on: cited first, then by passages; none without a passage."""
    sources: list[dict[str, Any]] = []
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
        publication = str(reference.get("publication_id"))
        if publication not in cited and publication not in passages:
            continue
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


_CODES = re.compile(r"\b[A-Za-z_]+=[\w-]+ \(([^)]*)\)")
_THE = re.compile(r"^(Netherlands|United [A-Z].*|Czech Republic|Philippines|European Union)$")
_GENERIC = re.compile(
    r"does not support|does not resolve the overall question|^Analysed \d+ downloaded dataset",
    re.IGNORECASE,
)


def _clean_entity(text: str) -> str:
    """'geo=AL (Albania) | sex=F (Females)' -> 'Albania, Females'."""
    return _CODES.sub(r"\1", text).replace(" | ", ", ").strip()


def _in(entity: str) -> str:
    return f"the {entity}" if _THE.match(entity) else entity


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _headline(answer: dict[str, Any] | None, data_part, level: str) -> dict[str, str]:
    """One sentence that answers the question, or says plainly that nothing did."""
    trends = (data_part or {}).get("_trends") or []
    if trends:
        return {"kind": "data", "text": _data_headline(trends)}
    text = (answer or {}).get("text") or ""
    if text and not _GENERIC.search(text) and level != "insufficient":
        return {"kind": "literature", "text": text}
    return {"kind": "none", "text": NO_ANSWER}


def _data_headline(trends: list[dict[str, Any]]) -> str:
    # "Life expectancy by country, sex, and year" -> "Life expectancy".
    label = _capital((trends[0]["label"] or "The measured value").split(" by ")[0])
    trends = [
        {**t, "unit": "" if t["unit"].casefold() in label.casefold() else t["unit"]} for t in trends
    ]
    start = min(t["first"]["year"] for t in trends)
    end = max(t["last"]["year"] for t in trends)
    if len(trends) == 1:
        t = trends[0]
        first, last = t["first"], t["last"]
        where = f" in {_in(t['entity'])}" if t["entity"] and t["entity"] != t["label"] else ""
        if first["year"] == last["year"]:
            return f"{label}{where} was {_number(last['value'])} {t['unit']} in {last['year']}.".replace(
                " .", "."
            ).replace("  ", " ")
        verb = (
            "rose"
            if last["value"] > first["value"]
            else "fell"
            if last["value"] < first["value"]
            else "stayed at"
        )
        unit = f" {t['unit']}" if t["unit"] else ""
        if verb == "stayed at":
            return f"{label}{where} stayed at {_number(last['value'])}{unit} ({start}–{end})."
        return (
            f"{label}{where} {verb} from {_number(first['value'])}{unit} in {first['year']} "
            f"to {_number(last['value'])}{unit} in {last['year']}."
        )
    rose = [t["entity"] for t in trends if t["last"]["value"] > t["first"]["value"]]
    fell = [t["entity"] for t in trends if t["last"]["value"] < t["first"]["value"]]
    if len(trends) <= 4:
        parts = [f"rose in {_join([_in(e) for e in rose])}"] if rose else []
        parts += [f"fell in {_join([_in(e) for e in fell])}"] if fell else []
        change = " and ".join(parts) or "did not change"
    else:
        change = f"rose in {len(rose)} of {len(trends)} series" if rose else ""
        if fell:
            change += f"{' and ' if change else ''}fell in {len(fell)}"
        change = change or "did not change"
    return f"{label} {change} ({start}–{end})."


def _measured_certainty(data_part, gaps: list[str], included: list[Any]) -> dict[str, str]:
    datasets = data_part["datasets"]
    publishers = list(dict.fromkeys(str(d.get("publisher") or d["title"]) for d in datasets))
    years = [y for d in datasets for y in (d.get("first_year"), d.get("last_year")) if y]
    span = f", {min(years)}–{max(years)}" if years else ""
    sentence = f"{_plural(len(datasets), 'dataset')} from {_join(publishers)}{span}"
    if included:
        one = len(included) == 1
        sentence += f"; {len(included)} {'study counts' if one else 'studies count'} as evidence"
    if gaps:
        return {"level": "weak", "label": "Partial data", "sentence": sentence + "."}
    return {"level": "moderate", "label": "Measured data", "sentence": sentence + "."}


_MEANING = re.compile(r"^Measurement meaning not confirmed:\s*[^:]*:\s*")


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(?:\s|$)", text.strip())
    return (match.group(1) if match else text.strip()).strip()


def _closest(answer: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    """What came nearest to an answer: partial findings, then data found but not used."""
    items: list[dict[str, Any]] = []
    for finding in _dict(answer.get("investigation_review")).get("partial_findings") or []:
        if not isinstance(finding, dict):
            continue
        doi = finding.get("doi")
        items.append(
            {
                "title": str(finding.get("title") or finding.get("subject") or "Publication"),
                "url": f"https://doi.org/{doi}" if doi else None,
                "note": _short(str(finding.get("qualification") or "")),
                "quote": finding.get("quote") or None,
            }
        )
    titles = set()
    for item in (data or {}).get("assessments") or []:
        if not isinstance(item, dict) or item.get("decision") == "analysed":
            continue
        reason = str(item.get("reason") or "")
        # Only data that was found and read but meant something else is a near answer.
        if not _MEANING.match(reason) or item.get("title") in titles:
            continue
        titles.add(item.get("title"))
        why = _first_sentence(_MEANING.sub("", reason))
        items.append(
            {
                "title": str(item.get("title") or item.get("url") or "Dataset"),
                "url": item.get("url"),
                "note": f"Found, but not used: {why[:1].lower()}{why[1:]}",
                "quote": None,
            }
        )
    return items[:MAX_CLOSEST]


_UNIT_PLURALS = {"year": "years", "day": "days", "hour": "hours", "person": "persons"}


def _unit(code: str, labels: dict[str, Any]) -> str:
    """A statistical unit code as a word: 'YR' with label 'Year' -> 'years'."""
    label = str(labels.get(code) or code)
    return _UNIT_PLURALS.get(label.casefold(), label)


def _short(text: str, limit: int = 300) -> str:
    """At most two sentences, cut at a sentence end where possible."""
    sentences = re.findall(r"[^.!?]+[.!?]+(?:\s|$)", text.strip()) or [text.strip()]
    short = "".join(sentences[:2]).strip()
    return short if len(short) <= limit else short[: limit - 1].rsplit(" ", 1)[0] + "…"
