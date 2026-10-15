"""Clickable versions of a research question, and the researcher's changes to them.

The interpretation model proposes options; each is validated into a complete brief here. A change
to a detail (route, measurements, geography, period) is applied without a model call and keeps
the literature plan and the data strategy consistent. Invalid input raises ``ValueError`` with a
reason the researcher can read.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from sci_search.data_research.strategy import SCHEMA as STRATEGY_SCHEMA
from sci_search.data_research.strategy import validate_strategy
from sci_search.question_planning import plan_from_brief

MAX_OPTIONS = 4
ROUTES = ("literature", "data", "both")
NEED_MEASUREMENT = "Choose or type at least one measurement for data research."

_TEXTS = {
    "type": "array",
    "maxItems": 5,
    "items": {"type": "string", "minLength": 1, "maxLength": 150},
}
ALTERNATIVES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["route", "measurements", "geography", "period"],
    "properties": {
        "route": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "enum": list(ROUTES)},
        },
        "measurements": {"type": "array", "maxItems": 4, "items": _TEXTS},
        "geography": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "geography_terms", "countries"],
                "properties": {
                    "label": {"type": "string", "maxLength": 150},
                    "geography_terms": _TEXTS,
                    "countries": {"type": "array", "maxItems": 60, "items": {"type": "string"}},
                },
            },
        },
        "period": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "start_year", "end_year"],
                "properties": {
                    "label": {"type": "string", "maxLength": 80},
                    "start_year": {"type": ["integer", "null"]},
                    "end_year": {"type": ["integer", "null"]},
                },
            },
        },
    },
}


def option_schema(plan_schema: dict[str, Any]) -> dict[str, Any]:
    """One proposed version of the question; ``plan_schema`` is the brief's research_plan schema."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "title",
            "summary",
            "closest",
            "interpreted_question",
            "objective",
            "research_plan",
            "research_strategy",
            "alternatives",
        ],
        "properties": {
            "title": {"type": "string", "minLength": 3, "maxLength": 80},
            "summary": {"type": "string", "minLength": 8, "maxLength": 300},
            "closest": {"type": "boolean"},
            "interpreted_question": {"type": "string", "minLength": 8, "maxLength": 500},
            "objective": {"type": "string", "minLength": 8, "maxLength": 500},
            "research_plan": plan_schema,
            "research_strategy": STRATEGY_SCHEMA,
            "alternatives": ALTERNATIVES_SCHEMA,
        },
    }


def option_briefs(
    question: str, base: dict[str, Any], raw_options: list[Any] | None
) -> list[dict[str, Any]]:
    """Validated options, the closest first; the base brief alone when none is valid."""
    options = []
    for raw in raw_options or []:
        try:
            options.append(_option(question, base, raw))
        except (ValueError, KeyError, TypeError):
            continue  # untrusted model output: an invalid version is dropped, not repaired
    options.sort(key=lambda option: not option["closest"])
    options = options[:MAX_OPTIONS]
    if not options:
        options = [
            {
                "title": "Your question",
                "summary": str(base.get("objective") or base.get("interpreted_question") or ""),
                "closest": True,
                "brief": base,
                "alternatives": {"route": [], "measurements": [], "geography": [], "period": []},
            }
        ]
    for index, option in enumerate(options):
        option["closest"] = index == 0
    return options


def _option(question: str, base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    strategy = raw.get("research_strategy")
    brief = {
        **deepcopy(base),
        "interpreted_question": " ".join(str(raw["interpreted_question"]).split()),
        "objective": " ".join(str(raw["objective"]).split()),
        "research_plan": deepcopy(raw["research_plan"]),
        "data_research": validate_strategy(strategy, infer_route=True) if strategy else None,
        "ambiguity": "minor" if base.get("ambiguity") == "material" else base.get("ambiguity"),
        "clarification_question": None,
    }
    if not brief["interpreted_question"] or not brief["objective"]:
        raise ValueError("incomplete option")
    return {
        "title": " ".join(str(raw["title"]).split())[:80],
        "summary": " ".join(str(raw["summary"]).split())[:300],
        "closest": raw.get("closest") is True,
        "brief": _refreshed(question, brief),
        "alternatives": _alternatives(raw.get("alternatives")),
    }


def _alternatives(raw: Any) -> dict[str, list[Any]]:
    raw = raw if isinstance(raw, dict) else {}
    result: dict[str, list[Any]] = {"route": [], "measurements": [], "geography": [], "period": []}
    result["route"] = [r for r in raw.get("route") or [] if r in ROUTES]
    for names in raw.get("measurements") or []:
        if (
            isinstance(names, list)
            and names
            and all(isinstance(n, str) and n.strip() for n in names)
        ):
            result["measurements"].append([" ".join(n.split()) for n in names][:5])
    for place in raw.get("geography") or []:
        try:
            result["geography"].append(_place(place))
        except (ValueError, TypeError, AttributeError):
            continue
    for period in raw.get("period") or []:
        try:
            result["period"].append(_period(period))
        except (ValueError, TypeError, AttributeError):
            continue
    return {key: values[:4] for key, values in result.items()}


def _place(value: Any) -> dict[str, Any]:
    terms = [" ".join(str(t).split()) for t in value.get("geography_terms") or [] if str(t).strip()]
    label = " ".join(str(value.get("label") or "").split()) or ", ".join(terms)
    if not terms and label:
        terms = [label]
    if not terms:
        raise ValueError("Give a place, or choose another geography.")
    countries = [str(c).upper() for c in value.get("countries") or []]
    if any(not re.fullmatch(r"[A-Z]{3}", c) for c in countries):
        raise ValueError("Use three-letter country codes, or leave countries empty.")
    return {"label": label, "geography_terms": terms[:5], "countries": countries}


def _period(value: Any) -> dict[str, Any]:
    years = {}
    for key in ("start_year", "end_year"):
        year = value.get(key)
        if year in (None, ""):
            years[key] = None
        elif isinstance(year, int) or (isinstance(year, str) and year.isdigit()):
            years[key] = int(year)
        else:
            raise ValueError("Give the years as numbers.")
    label = " ".join(str(value.get("label") or "").split())
    if not label and (years["start_year"] or years["end_year"]):
        label = f"{years['start_year'] or ''}–{years['end_year'] or ''}"
    return {"label": label, **years}


def adjust(brief: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    """The brief with one detail changed; raises ValueError with a readable reason."""
    brief = deepcopy(brief)
    plan = brief.get("research_plan")
    if not isinstance(plan, dict):
        raise ValueError("This interpretation has no adjustable plan.")
    strategy = brief.get("data_research")
    if strategy and strategy.get("adapter") not in (None, "discovered_data_v1"):
        raise ValueError("This research plan cannot be adjusted here.")
    detail = change.get("detail") if isinstance(change, dict) else None
    value = change.get("value") if isinstance(change, dict) else None

    def ensured() -> dict[str, Any]:
        nonlocal strategy
        if not strategy:
            strategy = {
                "route": "literature",
                "rationale": "Adjusted by the researcher.",
                "measurements": [],
                "geography": ", ".join(plan.get("geography_terms") or []),
                "countries": [],
                "start_year": None,
                "end_year": None,
            }
        return strategy

    if detail == "route":
        if value not in ROUTES:
            raise ValueError("Unknown research approach.")
        if value != "literature" and not ensured().get("measurements"):
            raise ValueError(NEED_MEASUREMENT)
        ensured()["route"] = value
    elif detail == "measurements":
        if not isinstance(value, list) or len(value) > 5:
            raise ValueError("Give up to five measurements.")
        names = [" ".join(str(v).split()) for v in value if str(v).strip()]
        if not names and ensured().get("route") != "literature":
            raise ValueError(NEED_MEASUREMENT)
        ensured()["measurements"] = names
    elif detail == "geography":
        place = _place(value if isinstance(value, dict) else {})
        plan["geography_terms"] = place["geography_terms"]
        if strategy:
            strategy.update(geography=place["label"], countries=place["countries"])
            strategy.pop("country_scope", None)  # inferred again from the new geography
    elif detail == "period":
        period = _period(value if isinstance(value, dict) else {})
        plan["time_terms"] = [period["label"]] if period["label"] else []
        if strategy:
            strategy.update(start_year=period["start_year"], end_year=period["end_year"])
        else:
            # The plan has no years of its own; check them as the data route would.
            validate_strategy({**ensured(), **period, "route": "literature"})
            strategy = None
    else:
        raise ValueError("Unknown detail.")
    brief["research_plan"] = plan
    brief["data_research"] = validate_strategy(strategy) if strategy else None
    return _refreshed(str(brief.get("original_question") or ""), brief)


def _refreshed(question: str, brief: dict[str, Any]) -> dict[str, Any]:
    """Recompute the derived fields of a brief from its validated plan."""
    from sci_search.question_interpretation import _evidence_to_seek

    plan = plan_from_brief(question, brief)
    brief["intent"] = plan.intent
    brief["concepts"] = list(plan.concepts)
    brief["evidence_scope"] = list(_evidence_to_seek(plan))
    brief.pop("options", None)
    brief.pop("clarification_options", None)
    return brief
