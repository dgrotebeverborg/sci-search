"""Inspectable model research strategy; contains no executable code or URLs."""

import re

from sci_search.data_research import calculation_contract, requirements

LAST_PROJECTED_YEAR = 2100
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "route",
        "rationale",
        "measurements",
        "geography",
        "start_year",
        "end_year",
        "calculations",
        "calculation_requests",
        "unresolved_calculations",
    ],
    "properties": {
        "requirements": requirements.SCHEMA,
        "calculations": calculation_contract.SCHEMA,
        "calculation_requests": calculation_contract.REQUEST_SCHEMA,
        "unresolved_calculations": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "route": {"type": "string", "enum": ["literature", "data", "both"]},
        "rationale": {"type": "string"},
        "measurements": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "geography": {"type": "string"},
        "country_scope": {"type": "string", "enum": ["europe", "eu27", "other"]},
        "countries": {"type": "array", "items": {"type": "string"}, "maxItems": 60},
        "start_year": {"type": ["integer", "null"]},
        "end_year": {"type": ["integer", "null"]},
    },
}
PROMPT = (
    " Include requirements for each data measurement: its definition, explicitly requested "
    "non-country entities (stations, basins, sites), breakdown dimensions with requested values, "
    "frequency, measure_type and observation_type. Use readable labels (male/female, not invented "
    "dataset codes). Do not invent breakdowns or infer that all requested data exists. "
    "Countries belong in countries and named cities/sites in entities; do not repeat them as "
    "breakdowns. A request to identify whether figures are citywide OR station-level asks for "
    "source qualification, not both as required breakdown values. Only require both when the "
    "user explicitly asks for both series. Preserve requested output calculations in definitions, "
    "and include base inputs for new calculations (for a newly computed ratio, numerator and "
    "denominator). Published percentages, rates and indices are already base series: retain "
    "them directly rather than requiring underlying counts or reconstructing their denominator. "
    " Copy measurement names EXACTLY from measurements into requirements.measurement and "
    "calculation input/reference, including any parenthesized units. Use ratio for monetary "
    "amounts, counts, and physical quantities such as electricity generation; interval is for "
    "scales without a meaningful zero, such as Celsius temperatures. Use index for CPI. "
    " Include calculations as an explicit list (empty when no additional numerical output is "
    "requested). Each calculation names an exact input measurement, and a distinct reference "
    "measurement for share/deflate/real_index. Operations: index (nominal base-year index), "
    "real_index (inflation-adjusted base-year index), deflate (constant-base-year monetary values), "
    "convert (requested physical unit), share (numerator as percent of denominator). When a physical output unit is explicitly requested, include convert with that target unit even if a source might already use it; compatible identity conversions are valid. Use stable "
    "unique id and readable label; base_year is required only for index/real_index/deflate; "
    "target_unit only for convert; use null for irrelevant reference/base_year/target_unit. "
    " Always include unresolved_calculations (empty when none): retain each explicitly requested "
    "numerical calculation or cross-check that these operations cannot execute, with a short "
    "description and reason. Do not silently omit it, substitute a different operation, or present "
    "an unsupported derived output as if it were a published input dataset. Examples include "
    "production divided by area, per-population recomputation, and subtraction of a multi-year "
    "reference mean. Share is only a percentage of a compatible total, not a general division. "
    "Operations also include difference (subtraction in the original unit) and percentage_point_change "
    "(subtraction of published percentages, NOT relative percent change). For these operations "
    "base_year=null requests year-on-year differences within the requested interval; an explicit "
    "base_year requests differences from that year's value. Use null reference and target_unit. "
    "Explicitly requested percentage-point changes MUST have a percentage_point_change calculation. "
    "For annual changes and an endpoint comparison, include two calculations. If timing is ambiguous, "
    "state the chosen interpretation in assumptions. Do not rely on descriptive endpoint summaries "
    "as a replacement for requested numerical outputs. "
    "Include calculation_requests: enumerate EVERY numerical transformation or cross-check requested "
    "in the original question, each with description and matching calculation_ids; use an empty "
    "unresolved_reason when executable, otherwise empty calculation_ids and the explicit unresolved_reason. "
    "Each request MUST also specify kind, independently identifying the mathematics requested "
    "by the user: index, real_index, deflate, convert, share, year_on_year_difference, "
    "baseline_difference, year_on_year_percentage_points, baseline_percentage_points, "
    "cross_series_difference, cross_series_percentage_points, reference_mean_anomaly, ratio, or other. "
    "Across groups (for example women minus men in the SAME year) is cross_series_difference, "
    "NEVER year_on_year_difference. Across-group subtraction, general ratios and reference-mean "
    "anomalies are currently unsupported: preserve their kind with empty calculation_ids and "
    "an unresolved_reason. Do not relabel their mathematical intent to fit an executable operation. "
    "Enumerate annual changes and baseline comparisons as separate requests. "
    "Only use an empty list when the question requests no calculations. "
    "Each requirement has definition_policy: specified by default. Use choose_documented ONLY when "
    "the question explicitly permits choosing a source definition and stating which was used. "
    "Never use it when the question specifies a denominator/definition, asks to compare definitions, "
    "or reconcile competing sources. A chosen source must still satisfy all other constraints. "
    "Retain published percentages directly, without requesting a share calculation. Explanations "
    "of methods or missing years belong in definitions, never as numerical measurements. "
    " Also choose research_strategy: literature for explanations, mechanisms, interventions, "
    "relationships or evidence synthesis; data for descriptive numerical questions answerable "
    "from published datasets; both when the user asks for numerical developments AND explanations. "
    "Do not force data research onto every quantitative scientific question. Describe requested "
    "measurements and geography faithfully. Measurements are published base series, including "
    "published percentages, rates and indices. Requested changes, trends and rebasing are "
    "calculations on those series, not separate datasets. "
    "Base variables may be observed or modelled. Preserve the requested observation type even "
    "for future years: a request for observations does not authorize projections. Never replace "
    "explicitly excluded projections with scenario data. Only when projections are requested or "
    "permitted, name projected variables with their scenario family, for example 'projected "
    "glacier runoff (SSP scenarios)'. Both start_year and end_year may extend to 2100. "
    "When datasets could answer part of a literature question, offer that data version as one of "
    "the options instead of leaving measurements empty. "
    "Set country_scope to europe for broader Europe, eu27 ONLY when EU/European Union is explicitly "
    "requested, and other for other geographies. Do not read a negated EU restriction as EU scope. "
    "When the geography names specific countries, list them in countries as ISO 3166-1 alpha-3 "
    "codes; otherwise leave countries empty. "
    "Distinguish Europe from EU; broader Europe includes "
    "explicit coverage gaps. Resolve 'this century' to 2001 through the last complete calendar year. "
    "Preserve an explicitly requested output interval exactly, including future-only intervals; "
    "do not replace it with years available in a dataset or silently drop it. Distinguish output "
    "periods from reference/baseline periods and index base years. "
    "Use null years when no interval is specified; do not invent a time restriction. "
    "Null dates mean seek the longest comparable historical series, not merely the first usable dataset. "
    "This strategy is a proposal, not a claim that a suitable dataset exists. "
    "Choose both for changes in hazard, risk or vulnerability: these often need study-based assessment "
    "as well as observations, even when explanations were not explicitly requested. "
    "For literature route measurements may be empty. Do not name a preset dataset."
)


def validate_strategy(value: dict, *, infer_route=False, require_calculation_intent=False) -> dict:
    if not isinstance(value, dict) or value.get("route") not in {"data", "literature", "both"}:
        raise ValueError("Invalid research approach")
    result = {"adapter": "discovered_data_v1", "route": value["route"]}
    for key in ("rationale", "geography"):
        if not isinstance(value.get(key), str) or len(value[key]) > 1500:
            raise ValueError(f"Invalid research strategy {key}")
        result[key] = value[key].strip()
    country_scope = value.get("country_scope")
    if country_scope is None:
        geo = result["geography"].casefold()
        country_scope = (
            "eu27"
            if re.match(r"^(?:eu(?:[- ]?27)?\b|european union\b)", geo)
            else "europe"
            if re.match(r"^europe\b", geo)
            else "other"
        )
    if country_scope not in {"europe", "eu27", "other"}:
        raise ValueError("Invalid country scope")
    result["country_scope"] = country_scope
    countries = value.get("countries") or []
    if (
        not isinstance(countries, list)
        or len(countries) > 60
        or any(not isinstance(c, str) or not re.fullmatch(r"[A-Za-z]{3}", c) for c in countries)
        or len({c.upper() for c in countries}) != len(countries)
    ):
        raise ValueError("Invalid research country codes")
    result["countries"] = [c.upper() for c in countries]
    metrics = value.get("measurements")
    if (
        not isinstance(metrics, list)
        or len(metrics) > 5
        or any(not isinstance(m, str) or not m.strip() or len(m) > 300 for m in metrics)
    ):
        raise ValueError("Invalid requested measurements")
    if value["route"] != "literature" and not metrics:
        raise ValueError("Data research requires requested measurements")
    result["measurements"] = metrics
    if "calculations" in value:
        result["calculations"] = calculation_contract.validate(value["calculations"], metrics)
    if "unresolved_calculations" in value:
        unresolved = value["unresolved_calculations"]
        if (
            not isinstance(unresolved, list)
            or len(unresolved) > 10
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 500
                for item in unresolved
            )
        ):
            raise ValueError("Invalid unresolved calculations")
        result["unresolved_calculations"] = list(dict.fromkeys(item.strip() for item in unresolved))
    if "requirements" in value:
        result["requirements"] = requirements.normalize_geography(
            requirements.validate(value["requirements"], metrics),
            result["countries"],
            result["geography"],
        )
    if require_calculation_intent and (
        (result.get("calculations") and not value.get("calculation_requests"))
        or any(
            not isinstance(item, dict) or "kind" not in item
            for item in value.get("calculation_requests", [])
        )
    ):
        raise ValueError("Fresh calculation requests must declare their mathematical meaning")
    if "calculation_requests" in value:
        unresolved = calculation_contract.validate_requests(
            value["calculation_requests"], result.get("calculations", [])
        )
        result["calculation_requests"] = [dict(r) for r in value["calculation_requests"]]
        result["unresolved_calculations"] = list(
            dict.fromkeys([*result.get("unresolved_calculations", []), *unresolved])
        )
    if (
        infer_route
        and result["route"] == "data"
        and any(re.search(r"\b(hazard|risk|vulnerability)\b", m, re.I) for m in metrics)
    ):
        result["route"] = "both"
        if "Study-based assessment" not in result["rationale"]:
            result["rationale"] += (
                " Study-based assessment is needed alongside data to interpret these concepts."
            )

    # Requested dates describe scope, not whether observations already exist.
    for key in ("start_year", "end_year"):
        year = value.get(key)
        if year is not None and (type(year) is not int or not 1800 <= year <= LAST_PROJECTED_YEAR):
            raise ValueError("Invalid research years")
        result[key] = year
    start, end = result["start_year"], result["end_year"]
    if start is not None and end is not None and (start > end or end - start > 200):
        raise ValueError("Invalid research year interval")
    return result
