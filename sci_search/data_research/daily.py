"""Checked annual means of complete daily-mean observations, without imputation."""

import calendar
import copy
import csv
import hashlib
import io
import math
import re
from datetime import datetime

try:
    from .tabular import read_csv
except ImportError:
    from tabular import read_csv


def aggregate_daily(body: bytes, preparation: dict, plan: dict) -> tuple[bytes, dict]:
    """Average only complete calendar years; retain incomplete years as missing."""
    headers, rows, lines = read_csv(body, with_line_numbers=True)
    date_key = plan.get("year_column", "")
    value_key = plan.get("value_column", "")
    entity_key = plan.get("entity_column", "")
    keys = [date_key, value_key] + ([entity_key] if entity_key else [])
    fmt = plan.get("date_format")
    decimal = plan.get("decimal_separator", ".")
    if plan.get("operation") != "daily_mean":
        raise ValueError("Expected daily_mean operation")
    if len(set(keys)) != len(keys) or not set(keys) <= set(headers):
        raise ValueError("Daily means require distinct observed date, value and entity columns")
    if fmt not in {"%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"}:
        raise ValueError("Daily means require an explicit supported date format")
    if decimal not in {".", ","}:
        raise ValueError("Unsupported decimal separator")
    if set(headers) & {"Year", "Observed days", "Expected days"}:
        raise ValueError("Daily mean output column collision")
    missing_values = plan.get("missing_values", ["", "NA", ":"])
    if not isinstance(missing_values, list) or any(not isinstance(v, str) for v in missing_values):
        raise ValueError("Missing values must be a list of strings")
    missing = set(missing_values) | {""}
    constants = [h for h in headers if h not in keys]
    dimensions, groups, spans, seen = {}, {}, {}, set()
    for row, line in zip(rows, lines, strict=True):
        label = row[entity_key] if entity_key else ""
        if entity_key and not label.strip():
            raise ValueError("Missing daily observation entity")
        values = tuple(row[h] for h in constants)
        if label in dimensions and dimensions[label] != values:
            raise ValueError(
                "Unselected columns vary within entity; select one parameter and quality definition"
            )
        dimensions[label] = values
        raw_date = row[date_key].strip()
        day = datetime.strptime(raw_date, fmt).date()
        if not 1800 <= day.year <= 2199:
            raise ValueError("Year outside supported range")
        if (label, day) in seen:
            raise ValueError("Duplicate daily date for entity")
        seen.add((label, day))
        raw = row[value_key].strip()
        value = None
        if raw not in missing:
            normalized = raw.replace(decimal, ".")
            if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", normalized):
                raise ValueError("Invalid numeric daily observation")
            value = float(normalized)
            if not math.isfinite(value):
                raise ValueError("Non-finite daily observation")
        origin = (
            preparation.get("row_provenance", {})
            .get(str(line), {})
            .get("source_reference", f"line:{line}")
        )
        groups.setdefault((label, day.year), []).append((value, origin))
        low, high = spans.get(label, (day.year, day.year))
        spans[label] = min(low, day.year), max(high, day.year)
    if max(high for _, high in spans.values()) - min(low for low, _ in spans.values()) > 200:
        raise ValueError("Daily aggregation exceeds the 200-year limit")
    if sum(high - low + 1 for low, high in spans.values()) > 50000:
        raise ValueError("Daily aggregation exceeds output row limit")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ([entity_key] if entity_key else [])
        + ["Year", value_key, "Observed days", "Expected days"]
        + constants
    )
    provenance, coverage = {}, []
    line = output.getvalue().count("\n") + 1
    for label, (low, high) in sorted(spans.items()):
        for year in range(low, high + 1):
            observations = groups.get((label, year), [])
            valid = [value for value, _ in observations if value is not None]
            expected = 366 if calendar.isleap(year) else 365
            complete = len(valid) == expected
            # Scale before summation so finite daily values cannot overflow the sum.
            mean = math.fsum(value / expected for value in valid) if complete else None
            if mean is not None and not math.isfinite(mean):
                raise ValueError("Non-finite annual mean")
            record = (
                ([label] if entity_key else [])
                + [str(year), "" if mean is None else repr(mean), str(len(valid)), str(expected)]
                + list(dimensions[label])
            )
            rendered = io.StringIO(newline="")
            csv.writer(rendered).writerow(record)
            text = rendered.getvalue()
            output.write(text)
            provenance[str(line)] = {
                "source_reference": "; ".join(str(origin) for _, origin in observations)
            }
            line += text.count("\n")
            coverage.append(
                dict(
                    entity=label,
                    year=year,
                    observed_days=len(valid),
                    expected_days=expected,
                    status="complete" if complete else "incomplete",
                )
            )
    data = output.getvalue().encode()
    read_csv(data)
    prep = copy.deepcopy(preparation)
    prep["row_provenance"] = provenance
    prep["normalized_sha256"] = hashlib.sha256(data).hexdigest()
    prep["daily_coverage"] = coverage
    prep.setdefault("transformations", []).append(copy.deepcopy(plan))
    prep.setdefault("checks", {})["transformed_rows"] = len(coverage)
    prep.setdefault("limitations", []).append(
        "Annual arithmetic means require one valid daily mean for every calendar day (365 or 366). "
        "Incomplete years and missing middle years remain blank, never zero; no interpolation or imputation was performed. "
        "Observed days counts valid numeric daily means; coverage is recorded for each entity and year."
    )
    return data, prep
