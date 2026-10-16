"""Conservative question coverage. Existing analyses are never mutated or spliced."""

import itertools
import math
import re

from sci_search.data_research.wildfire import COUNTRY_NAMES

ALIASES = {
    "male": ("male", "males", "men", "mannen"),
    "female": ("female", "females", "women", "vrouwen"),
    "NLD": ("Netherlands", "Nederland", "NLD"),
    "DEU": ("Germany", "Duitsland", "DEU"),
}


def _matches(value, text):
    aliases = ALIASES.get(value, (value, COUNTRY_NAMES.get(value, value)))
    return any(
        re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text, 0 if a in COUNTRY_NAMES else re.I)
        for a in aliases
    )


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def evaluate(scope, analyses):
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
            if not requirement.get("entities") or any(_matches(c, entity) for c in COUNTRY_NAMES):
                other_entities.update(COUNTRY_NAMES)
            elif countries:
                other_entities.update(set(COUNTRY_NAMES) - set(countries))
            dimensions = dict(zip((d["dimension"] for d in dims), values, strict=True))
            matches = []
            for source_index, analysis in enumerate(analyses):
                for series in analysis.get("series", []):
                    if series.get("label") != measurement:
                        continue
                    text = series.get("entity", "")
                    # Source identities, when available, are retained with the executed result.
                    identity = series.get("identity", {})
                    geography = identity.get("geography", text)
                    if entity and (
                        not _matches(entity, geography)
                        or any(
                            other != entity
                            and not _matches(other, entity)
                            and not _matches(entity, other)
                            and _matches(other, geography)
                            for other in other_entities
                        )
                    ):
                        continue
                    if any(
                        (
                            not _matches(v, identity.get("dimensions", {}).get(d, text))
                            or any(
                                other != v
                                and _matches(other, identity.get("dimensions", {}).get(d, text))
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
                            "sex_identity": tuple(
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
            best = max(matches, key=lambda m: len(m["years"]), default={"years": []})
            years = set(best["years"])
            missing = sorted(requested_years - years) if requested_years is not None else []
            conflicts = []
            for left, right in itertools.combinations(matches, 2):
                if (
                    left["source_index"] == right["source_index"]
                    or left["sex_identity"] != right["sex_identity"]
                ):
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
            elif conflicts:
                reason = "Overlapping sources differ; definitions, units or revisions need reconciliation"
            elif requested_years is None:
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
        "qualification": "Coverage describes retained observations, not exhaustive discovery or scientific validation.",
    }


def pending(scope, analyses):
    complete = evaluate(scope, analyses)["complete_measurements"]
    return [m for m in scope["measurements"] if m not in complete]


def planning_summary(scope, analyses):
    coverage = evaluate(scope, analyses)
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
