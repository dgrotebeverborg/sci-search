"""Pure arithmetic over resolved series, also executed unchanged in the isolated runner."""

import math
import re

UNITS = {
    "wh": ("energy", 1),
    "kwh": ("energy", 1e3),
    "mwh": ("energy", 1e6),
    "gwh": ("energy", 1e9),
    "twh": ("energy", 1e12),
    "euro": ("EUR", 1),
    "euros": ("EUR", 1),
    "eur": ("EUR", 1),
    "€": ("EUR", 1),
    "1000euro": ("EUR", 1000),
    "thousandeuros": ("EUR", 1000),
    "usd": ("USD", 1),
    "us$": ("USD", 1),
}

# Explicit physical units only. Rates need their denominator in the unit itself.
for dimension, scale, names in (
    ("mass", 1, ("kg", "kilograms")),
    ("mass", 1000, ("t", "tonne", "tonnes", "1000 kg")),
    ("mass", 1e6, ("thousand tonnes",)),
    ("area", 1, ("ha", "hectare", "hectares")),
    ("area", 100, ("km2", "km²")),
    ("area", 1000, ("thousand hectares",)),
    ("mass/area", 1, ("t/ha", "tonnes per hectare", "tonnes/ha")),
    ("mass/area", 0.001, ("kg/ha", "kilograms per hectare")),
    ("celsius", 1, ("°C", "degrees Celsius", "degree Celsius")),
    ("celsius", 0.1, ("0.1 degrees Celsius", "0.1 °C")),
    ("passenger-distance", 1, ("passenger-kilometres", "passenger-kilometers")),
    ("passenger-distance", 1e6, ("million passenger-kilometres", "million passenger-kilometers")),
    ("passenger-distance", 1e9, ("billion passenger-kilometres", "billion passenger-kilometers")),
):
    for name in names:
        UNITS["".join(name.lower().split())] = (dimension, scale)


for name, symbol in (
    ("watt", "wh"),
    ("kilowatt", "kwh"),
    ("megawatt", "mwh"),
    ("gigawatt", "gwh"),
    ("terawatt", "twh"),
):
    for suffix in ("hour", "hours", "-hour", "-hours"):
        UNITS[name + suffix] = UNITS[symbol]


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


# SI symbols are case-sensitive; lowercase and all-uppercase energy abbreviations
# below are explicitly retained application aliases, not arbitrary case folding.
SYMBOL_ALIASES = {
    **{
        s: s.lower()
        for s in (
            "Wh",
            "wh",
            "WH",
            "kWh",
            "kwh",
            "KWH",
            "MWh",
            "mwh",
            "MWH",
            "GWh",
            "gwh",
            "GWH",
            "TWh",
            "twh",
            "TWH",
        )
    },
    **{s: s for s in ("kg", "t", "ha", "km2", "km²", "t/ha", "kg/ha")},
    "°C": "°c",
    "°c": "°c",
}


def unit_key(unit):
    compact = "".join(str(unit).split())
    lowered = compact.lower()
    if lowered in SYMBOL_ALIASES.values():
        return SYMBOL_ALIASES.get(compact, "unsupported:" + compact)
    return lowered


def unit_semantics(unit):
    """Resolve only explicit physical scales, substances and rate denominators."""
    text = str(unit).strip().replace("₂", "2").replace("₄", "4")
    parts = re.split(r"\s+per\s+|/", text, flags=re.I)
    if len(parts) == 2:
        numerator, denominator = parts
        denominator = denominator.strip()
        if denominator.casefold() in {"person", "people", "capita", "inhabitant", "inhabitants"}:
            denominator_dimension, denominator_scale = "person", 1
        else:
            denominator_dimension, denominator_scale = UNITS.get(unit_key(denominator), (None, 0))
        if denominator_dimension not in {"person", "area"}:
            raise ValueError("Unsupported unit denominator")
    elif len(parts) == 1:
        numerator, denominator_dimension, denominator_scale = text, "", 1
    else:
        raise ValueError("Unsupported compound unit")
    substance = ""
    match = re.fullmatch(r"(.+?)\s+(?:of\s+)?(CO2|CH4|carbon dioxide|methane)", numerator, re.I)
    if match is None:
        match = re.fullmatch(r"(.+?)\s+of\s+(.+)", numerator, re.I)
    if match:
        numerator, substance = match.groups()
        substance = substance.strip().casefold()
        substance = {"carbon dioxide": "co2", "methane": "ch4"}.get(substance, substance)
    dimension, scale = UNITS.get(unit_key(numerator), (None, 0))
    if dimension is None or (substance and dimension != "mass"):
        raise ValueError("Units are incompatible or conversion is unsupported")
    if dimension == "mass/area" and not denominator_dimension:
        # Historical compound aliases store tonnes/ha, while parsed mass uses kg.
        dimension, denominator_dimension, scale = "mass", "area", scale * 1000
    return (dimension, denominator_dimension, substance), scale / denominator_scale


def source_substance(series):
    # Identity dimensions are selected source fields; labels may come from the request.
    indicator = str((series or {}).get("identity", {}).get("dimensions", {}).get("indicator", ""))
    indicator = indicator.replace("₂", "2").replace("₄", "4").casefold()
    if re.search(r"co2[ -]?(?:equivalent|eq)\b", indicator):
        return "co2-equivalent"
    found = set()
    for substance, pattern in (
        ("co2", r"\b(?:co2|carbon dioxide)\b"),
        ("ch4", r"\b(?:ch4|methane)\b"),
    ):
        if re.search(pattern, indicator):
            found.add(substance)
    return next(iter(found)) if len(found) == 1 else ""


def factor(source, target, *, source_series=None, target_series=None):
    source_evidence = source_substance(source_series)
    target_evidence = source_substance(target_series)
    if source_evidence and target_evidence and source_evidence != target_evidence:
        raise ValueError("Unit substances are incompatible or undocumented")
    if str(source).strip() and str(source).strip() == str(target).strip():
        return 1
    left, left_scale = unit_semantics(source)
    right, right_scale = unit_semantics(target)
    if left[:2] != right[:2]:
        raise ValueError("Units are incompatible or conversion is unsupported")
    if left[2] != right[2]:
        left_substance = left[2] or source_substance(source_series)
        right_substance = right[2] or source_substance(target_series)
        if not left_substance or left_substance != right_substance:
            raise ValueError("Unit substances are incompatible or undocumented")
    return left_scale / right_scale


def observations(series):
    rows = series.get("annual", [])
    if any(type(r.get("year")) is not int for r in rows) or len({r["year"] for r in rows}) != len(
        rows
    ):
        raise ValueError("Duplicate or invalid year in input series")
    return {r["year"]: r for r in rows}


def comparable(series):
    if series.get("comparability_note"):
        return False
    for row in series.get("annual", []):
        flag = str(row.get("source_status", "")).strip().lower().replace(" ", "")
        if re.fullmatch("[a-z]{1,3}", flag) and set(flag) - {"p", "e"}:
            return False
    return True


def calculate(plan, source, reference=None, *, years):
    """Never fill gaps, splice sources, pick a replacement base year or mutate inputs."""
    op, base = plan["operation"], plan["base_year"]
    result = {
        "id": plan["id"],
        "label": plan["label"],
        "operation": op,
        "unit": plan.get("target_unit")
        or (
            "%"
            if op == "share"
            else "percentage points"
            if op == "percentage_point_change"
            else source.get("unit", "")
            if op == "difference"
            else f"{base} = 100"
            if op in {"index", "real_index"}
            else f"{source.get('unit', '')} at {base} prices"
        ),
        "formula": {
            "index": "100 * x[t] / x[base]",
            "real_index": "100 * (x[t] / x[base]) * (CPI[base] / CPI[t])",
            "deflate": "x[t] * CPI[base] / CPI[t]",
            "convert": "x[t] * unit_conversion_factor",
            "share": "100 * numerator[t] * unit_conversion_factor / denominator[t]",
            "difference": "x[t] - x[base]" if base is not None else "x[t] - x[t-1]",
            "percentage_point_change": "x[t] - x[base]" if base is not None else "x[t] - x[t-1]",
        }[op],
        "base_year": base,
        "status": "blocked",
        "reason": "",
        "annual": [],
    }
    failure = ""
    baseline = price_base = multiplier = 1
    try:
        rows = observations(source)
        refs = observations(reference) if reference is not None else {}
        if op in {"index", "real_index", "deflate", "difference", "percentage_point_change"} and (
            not comparable(source) or (reference is not None and not comparable(reference))
        ):
            raise ValueError("Source comparability flags prevent comparison with the base year")
        if op == "percentage_point_change" and (
            source.get("measure_type") != "percentage"
            or str(source.get("unit", "")).strip().casefold()
            not in {"%", "pc", "percent", "percentage", "per cent"}
        ):
            raise ValueError(
                "Percentage-point changes require a documented percentage scale and unit"
            )
        if op == "difference" and source.get("measure_type") not in {
            "ratio",
            "interval",
            "index",
            "percentage",
        }:
            raise ValueError("Differences require a documented numeric scale")
        if op in {"index", "real_index"}:
            baseline = rows.get(base, {}).get("value")
            if not finite(baseline) or baseline <= 0:
                raise ValueError(f"Missing or non-positive input baseline for {base}")
            if source.get("measure_type") not in {"ratio", "index", "percentage"}:
                raise ValueError("Input scale does not support a base-year index")
        if op in {"deflate", "real_index"}:
            if not (op == "real_index" and source.get("measure_type") == "index") and UNITS.get(
                unit_key(source.get("unit")), ("", 0)
            )[0] not in {"EUR", "USD"}:
                raise ValueError("Inflation adjustment requires a supported monetary unit")
            if reference is None or reference.get("measure_type") != "index":
                raise ValueError("Inflation adjustment requires a documented price index")
            price_base = refs.get(base, {}).get("value")
            if not finite(price_base) or price_base <= 0:
                raise ValueError(f"Missing or non-positive price-index baseline for {base}")
        multiplier = 1
        if op in {"convert", "share"}:
            if op == "share" and (
                reference is None
                or source.get("measure_type") != "ratio"
                or reference.get("measure_type") != "ratio"
            ):
                raise ValueError("Share requires two ratio-scale measurements")
            multiplier = factor(
                source.get("unit"),
                plan["target_unit"] if op == "convert" else reference.get("unit"),
                source_series=source,
                target_series=reference if op == "share" else None,
            )
            result["conversion_factor"] = multiplier
    except ValueError as exc:
        failure = str(exc)
        rows, refs = {}, {}
    for year in years:
        row, ref = rows.get(year, {}), refs.get(year, {})
        value, other = row.get("value"), ref.get("value")
        reason = failure
        comparison_year = base if base is not None else year - 1
        comparison = rows.get(comparison_year, {})
        if (
            not reason
            and op in {"difference", "percentage_point_change"}
            and not finite(comparison.get("value"))
        ):
            reason = f"Comparison observation missing for {comparison_year}"
        if not reason and not finite(value):
            reason = "Input observation missing or non-finite"
        if (
            not reason
            and op in {"share", "real_index", "deflate"}
            and (not finite(other) or other <= 0)
        ):
            reason = "Reference denominator missing or non-positive"
        output = None
        if not reason:
            try:
                if op == "index":
                    output = 100 * value / baseline
                elif op == "real_index":
                    output = 100 * (value / baseline) * (price_base / other)
                elif op == "deflate":
                    output = value * price_base / other
                elif op == "convert":
                    output = value * multiplier
                elif op in {"difference", "percentage_point_change"}:
                    output = value - comparison["value"]
                else:
                    output = 100 * value * multiplier / other
                if not finite(output) or (op == "share" and not 0 <= output <= 100):
                    reason, output = "Result outside the finite, valid range", None
            except (ArithmeticError, ValueError):
                reason, output = "Calculation outside the finite, valid range", None
        inputs = [{"role": "input", "year": year, "observation": row}]
        if op in {"difference", "percentage_point_change"}:
            inputs.append(
                {"role": "comparison", "year": comparison_year, "observation": comparison}
            )
        if reference is not None:
            inputs.append({"role": "reference", "year": year, "observation": ref})
        if base is not None:
            if op in {"index", "real_index"}:
                inputs.append(
                    {"role": "input baseline", "year": base, "observation": rows.get(base, {})}
                )
            if reference is not None:
                inputs.append(
                    {"role": "reference baseline", "year": base, "observation": refs.get(base, {})}
                )
        result["annual"].append({"year": year, "value": output, "reason": reason, "inputs": inputs})
    available = sum(r["value"] is not None for r in result["annual"])
    result["status"] = (
        "complete"
        if available and available == len(years)
        else "partial"
        if available
        else "blocked"
    )
    result["reason"] = failure or (
        "Some requested years could not be calculated" if result["status"] != "complete" else ""
    )
    return result
