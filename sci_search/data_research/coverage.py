"""Conservative question coverage. Existing analyses are never mutated or spliced."""

import itertools
import math
import re

from sci_search.data_research import coverage_bindings
from sci_search.data_research.countries import (
    COUNTRY_NAMES,
    canonical_country,
    country_mentions,
)

ALIASES = {
    "male": ("male", "males", "men", "mannen"),
    "female": ("female", "females", "women", "vrouwen"),
}


def _geography_matches(value, text):
    country = canonical_country(value)
    if country:
        return country in country_mentions(text)
    return _matches(value, text)


def _matches(value, text):
    aliases = ALIASES.get(value, (value,))
    return any(re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text, re.I) for a in aliases)


def _dimension_matches(dimension, value, text):
    # Country aliases belong only to explicitly geographic categories. In particular,
    # an ordinary answer "No" must not acquire the ISO2 meaning Norway.
    name = " ".join(str(dimension).casefold().replace("_", " ").replace("-", " ").split())
    country_dimensions = {
        "country",
        "country of birth",
        "birth country",
        "country of residence",
        "country of citizenship",
        "citizenship",
        "nationality",
        "reporting country",
        "partner country",
        "origin country",
        "destination country",
    }
    match = _geography_matches if name in country_dimensions else _matches
    return match(value, text)


def _region_members(scope, entity):
    """Countries of the requested region when the question names only the region."""
    from sci_search.data_research.wildfire import EU27, EUROPE

    if scope.get("countries") or not entity or entity != (scope.get("geography") or ""):
        return ()
    return {"eu27": tuple(EU27), "europe": tuple(EUROPE)}.get(scope.get("country_scope"), ())


def _country_panel(scope, entity, measurement, analyses, start, end):
    """A source reporting most of a region's countries covers the regional question.

    A single country never stands in for its region, and countries are not
    averaged: the panel is retained as separate country series. Only years that
    a majority of the region's countries report count as covered.
    """
    members = set(_region_members(scope, entity))
    if not members:
        return None
    best = None
    for source_index, analysis in enumerate(analyses):
        by_year: dict[int, set[str]] = {}
        countries = set()
        for series in analysis.get("series", []):
            if series.get("label") != measurement:
                continue
            identity = series.get("identity", {})
            mentioned = country_mentions(identity.get("geography", series.get("entity", "")))
            if len(mentioned) != 1 or not mentioned <= members:
                continue
            countries |= mentioned
            for row in series.get("annual", []):
                if (
                    _finite(row.get("value"))
                    and (start is None or row["year"] >= start)
                    and (end is None or row["year"] <= end)
                ):
                    by_year.setdefault(row["year"], set()).update(mentioned)
        needed = len(members) // 2 + 1
        years = sorted(y for y, present in by_year.items() if len(present) >= needed)
        if years and (best is None or len(years) > len(best["years"])):
            best = {
                "source_index": source_index,
                "series_index": None,
                "country_panel": sorted(countries),
                "sex_identity": (),
                "entity": f"{len(countries)} countries",
                "unit": None,
                "years": years,
                "values": {},
            }
    return best


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _source_choices(scope, analyses):
    """Only a delegated definition choice may prefer one complete reviewed source.

    Pick the first complete source as one whole comparison panel. Never splice
    countries/years or silently resolve conflicts under the default strict policy.
    """
    choices = {}
    for requirement in scope.get("requirements", []):
        if requirement.get("definition_policy") != "choose_documented":
            continue
        name = requirement["measurement"]
        if name not in scope.get("measurements", []):
            continue
        strict = {
            **scope,
            "measurements": [name],
            "requirements": [{**requirement, "definition_policy": "specified"}],
        }
        for index, analysis in enumerate(analyses):
            if analysis.get("execution", {}).get("status") != "verified":
                continue
            reviews = [analysis.get("semantic_review", {})] + [
                c.get("semantic_review", {}) for c in analysis.get("components", [])
            ]
            evidence = [
                e
                for review in reviews
                if review.get("accepted")
                for item in review.get("measurements", [])
                if item.get("measurement") == name
                for check in item.get("checks", [])
                if check.get("aspect") == "definition" and check.get("status") == "supported"
                for e in check.get("evidence", [])
                if e.get("quote")
            ]
            if not evidence or name not in evaluate(strict, [analysis])["complete_measurements"]:
                continue
            choices[name] = {
                "source_index": index,
                "source_sha256": analysis.get("source", {}).get("sha256", ""),
                "definition": "\n".join(dict.fromkeys(e["quote"] for e in evidence)),
                "evidence": evidence,
                "reason": "The question permits a documented definition choice. This first reviewed source covers the entire requested comparison; alternative definitions are retained separately.",
                "alternative_source_indexes": [
                    i
                    for i, a in enumerate(analyses)
                    if i != index and any(s.get("label") == name for s in a.get("series", []))
                ],
            }
            break
    return choices


def evaluate(scope, analyses, *, period_searched=False):
    """Coverage of every requested cell.

    An open period is satisfied only after a follow-up search for earlier or
    longer comparable data has been carried out (``period_searched``).
    """
    choices = _source_choices(scope, analyses)
    requirements = {r["measurement"]: r for r in scope.get("requirements", [])}
    # A regional request is not an implicit request for every constituent country.
    # Explicit country lists and per-measurement entities still take precedence.
    countries = scope.get("countries") or []
    start, end = scope.get("start_year"), scope.get("end_year")
    requested_years = set(range(start, end + 1)) if start is not None and end is not None else None
    cells = []
    for measurement in scope.get("measurements", []):
        requirement = requirements.get(measurement, {})
        entities = requirement.get("entities") or countries or [scope.get("geography") or ""]
        # Normalize only the sex dimension; preserve unrelated category and entity names.
        sex_aliases = {alias: key for key in ("female", "male") for alias in ALIASES[key]}
        dims = [
            {
                **dimension,
                "values": list(
                    dict.fromkeys(sex_aliases.get(v.casefold(), v) for v in dimension["values"])
                ),
            }
            if dimension["dimension"] == "sex"
            else dimension
            for dimension in requirement.get("breakdowns", [])
        ]
        combinations = list(itertools.product(*(d["values"] for d in dims)))
        for entity, values in itertools.product(entities, combinations):
            other_entities = set(entities)
            if not requirement.get("entities") or any(
                _geography_matches(c, entity) for c in COUNTRY_NAMES
            ):
                other_entities.update(COUNTRY_NAMES)
            elif countries:
                other_entities.update(
                    set(COUNTRY_NAMES) - {canonical_country(c) or c for c in countries}
                )
            dimensions = dict(zip((d["dimension"] for d in dims), values, strict=True))
            matches = []
            for source_index, analysis in enumerate(analyses):
                if measurement in choices and source_index != choices[measurement]["source_index"]:
                    continue
                for series_index, series in enumerate(analysis.get("series", [])):
                    if series.get("label") != measurement:
                        continue
                    text = series.get("entity", "")
                    # Source identities, when available, are retained with the executed result.
                    identity = series.get("identity", {})
                    geography = identity.get("geography", text)
                    bound = coverage_bindings.matches(
                        scope,
                        {"measurement": measurement, "entity": entity, "dimensions": dimensions},
                        analysis,
                        series,
                    )
                    if (
                        not bound
                        and entity
                        and (
                            not _geography_matches(entity, geography)
                            or any(
                                other != entity
                                and not _geography_matches(other, entity)
                                and not _geography_matches(entity, other)
                                and _geography_matches(other, geography)
                                for other in other_entities
                            )
                        )
                    ):
                        continue
                    if not bound and any(
                        (
                            not _dimension_matches(
                                d, v, identity.get("dimensions", {}).get(d, text)
                            )
                            or any(
                                other != v
                                and _dimension_matches(
                                    d, other, identity.get("dimensions", {}).get(d, text)
                                )
                                for dim in dims
                                if dim["dimension"] == d
                                for other in set(dim["values"])
                                | ({"male", "female"} if v in {"male", "female"} else set())
                            )
                        )
                        for d, v in dimensions.items()
                    ):
                        continue
                    years = {
                        r["year"]
                        for r in series.get("annual", [])
                        if _finite(r.get("value"))
                        and (start is None or r["year"] >= start)
                        and (end is None or r["year"] <= end)
                    }
                    matches.append(
                        {
                            "source_index": source_index,
                            "series_index": series_index,
                            **({"scope_binding": True} if bound else {}),
                            "sex_identity": (dimensions["sex"],)
                            if bound and "sex" in dimensions
                            else tuple(
                                v
                                for v in ("male", "female")
                                if _matches(v, identity.get("dimensions", {}).get("sex", text))
                            ),
                            "entity": text,
                            "unit": series.get("unit"),
                            "years": sorted(years),
                            "values": {
                                r["year"]: r["value"]
                                for r in series.get("annual", [])
                                if r["year"] in years
                            },
                        }
                    )
            if not matches and not dimensions:
                panel = _country_panel(scope, entity, measurement, analyses, start, end)
                if panel:
                    matches.append(panel)
            best = max(matches, key=lambda m: len(m["years"]), default={"years": []})
            years = set(best["years"])
            missing = sorted(requested_years - years) if requested_years is not None else []
            conflicts = []
            for left, right in itertools.combinations(matches, 2):
                if (
                    left["source_index"] == right["source_index"]
                    and not left.get("scope_binding")
                    and not right.get("scope_binding")
                ) or left["sex_identity"] != right["sex_identity"]:
                    continue
                overlap = set(left["years"]) & set(right["years"])
                different = sorted(y for y in overlap if left["values"][y] != right["values"][y])
                if overlap and (left["unit"] != right["unit"] or different):
                    conflicts.append(
                        {
                            "sources": [left["source_index"], right["source_index"]],
                            "years": different,
                            "units": [left["unit"], right["unit"]],
                        }
                    )
            reason = ""
            if requirement.get("frequency", "annual") not in {"annual", "unspecified"}:
                reason = "Requested frequency is not supported by the annual output contract"
            elif not years:
                reason = "No matching numeric observations"
            elif (
                requirement.get("definition_policy") == "choose_documented"
                and measurement not in choices
            ):
                reason = "No single reviewed source covers the requested comparison under one documented definition"
            elif conflicts:
                reason = "Overlapping sources differ; definitions, units or revisions need reconciliation"
            elif requested_years is None and not period_searched:
                reason = "Open period requires a coverage search"
            elif missing:
                reason = "Requested years missing from a single source series"
            status = "complete" if not reason else "partial" if years else "missing"
            cells.append(
                {
                    "measurement": measurement,
                    "entity": entity,
                    "dimensions": dimensions,
                    "status": status,
                    "missing_years": missing,
                    "reason": reason,
                    "available_years": sorted(years),
                    "sources": matches,
                    "conflicts": conflicts,
                }
            )
    gaps = [c for c in cells if c["status"] != "complete"]
    complete = [
        m
        for m in scope.get("measurements", [])
        if any(c["measurement"] == m for c in cells)
        and not any(c["measurement"] == m for c in gaps)
    ]
    return {
        "version": 1,
        "cells": cells,
        "gaps": gaps,
        "complete_measurements": complete,
        **({"source_choices": choices} if choices else {}),
        "qualification": "Coverage describes retained observations, not exhaustive discovery or scientific validation.",
    }


def pending(scope, analyses, *, period_searched=False):
    complete = evaluate(scope, analyses, period_searched=period_searched)["complete_measurements"]
    return [m for m in scope["measurements"] if m not in complete]


def period_searched(process):
    """Whether a follow-up search for longer or earlier comparable data completed."""
    return any(
        step.get("action") == "search" and step.get("status") in {"checked", "no_new_sources"}
        for step in (process or {}).get("steps", [])
    )


def planning_summary(scope, analyses, *, searched=False):
    coverage = evaluate(scope, analyses, period_searched=searched)
    gaps = coverage["gaps"]
    return {
        "complete_measurements": coverage["complete_measurements"],
        "requested_combinations": len(coverage["cells"]),
        "missing_combinations": len(gaps),
        "gaps": [
            {k: c[k] for k in ("measurement", "entity", "dimensions", "reason", "missing_years")}
            for c in gaps[:60]
        ],
        "omitted_gaps": max(0, len(gaps) - 60),
    }


def target_scope(scope, analyses, measurement):
    narrowed = {**scope}
    gaps = [g for g in evaluate(scope, analyses)["gaps"] if g["measurement"] == measurement]
    if scope.get("countries") and gaps:
        needed = {g["entity"] for g in gaps}
        countries = [c for c in scope["countries"] if c in needed]
        if countries:
            narrowed["countries"] = countries
    return narrowed
