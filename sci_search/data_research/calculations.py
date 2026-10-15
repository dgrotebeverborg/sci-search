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


def unit_key(unit):
    return "".join(str(unit).lower().split())


def factor(source, target):
    left, right = unit_key(source), unit_key(target)
    if left and left == right:
        return 1
    if left not in UNITS or right not in UNITS or UNITS[left][0] != UNITS[right][0]:
        raise ValueError("Units are incompatible or conversion is unsupported")
    return UNITS[left][1] / UNITS[right][1]


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
        if op in {"index", "real_index", "deflate"} and (
            not comparable(source) or (reference is not None and not comparable(reference))
        ):
            raise ValueError("Source comparability flags prevent comparison with the base year")
        if op in {"index", "real_index"}:
            baseline = rows.get(base, {}).get("value")
            if not finite(baseline) or baseline <= 0:
                raise ValueError(f"Missing or non-positive input baseline for {base}")
            if source.get("measure_type") not in {"ratio", "index", "percentage"}:
                raise ValueError("Input scale does not support a base-year index")
        if op in {"deflate", "real_index"}:
            if UNITS.get(unit_key(source.get("unit")), ("", 0))[0] not in {"EUR", "USD"}:
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
            )
            result["conversion_factor"] = multiplier
    except ValueError as exc:
        failure = str(exc)
        rows, refs = {}, {}
    for year in years:
        row, ref = rows.get(year, {}), refs.get(year, {})
        value, other = row.get("value"), ref.get("value")
        reason = failure
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
                else:
                    output = 100 * value * multiplier / other
                if not finite(output) or (op == "share" and not 0 <= output <= 100):
                    reason, output = "Result outside the finite, valid range", None
            except (ArithmeticError, ValueError):
                reason, output = "Calculation outside the finite, valid range", None
        inputs = [{"role": "input", "year": year, "observation": row}]
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
