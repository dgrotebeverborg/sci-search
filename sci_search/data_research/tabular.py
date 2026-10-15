"""Small declarative annual-series engine. No model-generated numbers or code."""

import csv
import io
import math
import re
from typing import Literal, overload

CONVERSIONS = {("ha", "km2"): 0.01, ("hectares", "km²"): 0.01, ("ha", "km²"): 0.01}


def changes(first, last, unit, label, scope):
    """Only ratio scales with a positive baseline support ordinary percentage change."""
    normalized = unit.casefold().strip()
    requirement = next((r for r in scope.get("requirements", []) if r["measurement"] == label), {})
    kind = requirement.get("measure_type", "unknown")
    if normalized in {"°c", "°f", "degc", "degf", "celsius", "fahrenheit"} or any(
        word in normalized for word in ("celsius", "fahrenheit", "anomaly", "anomalie")
    ):
        kind = "interval"
    elif normalized in {"%", "percent", "percentage", "pct", "pc"}:
        kind = "percentage"
    elif kind == "unknown" and normalized in {
        "people",
        "persons",
        "person",
        "count",
        "number",
        "years",
        "yr",
        "ha",
        "hectares",
        "km2",
        "km²",
        "m2",
        "m²",
        "kg",
        "tonnes",
        "mwh",
        "gwh",
        "kwh",
        "mw",
        "kw",
        "ppm",
        "eur",
        "usd",
        "m3/s",
        "m³/s",
    }:
        kind = "ratio"
    delta = last - first if first is not None and last is not None else None
    if delta is not None and not math.isfinite(delta):
        delta = None
    percent = (
        100 * (delta / first)
        if (delta is not None and first > 0 and kind in {"ratio", "percentage"})
        else None
    )
    if percent is not None and not math.isfinite(percent):
        percent = None
    return {
        "absolute_change": delta,
        "absolute_change_unit": "percentage points" if kind == "percentage" else unit,
        "change_percent": percent,
        "measure_type": kind,
        "change_note": "Relative change requires a supported ratio scale and positive, available baseline."
        if percent is None
        else "Relative endpoint change; not a causal or significance assessment.",
    }


MAPPING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **{
            k: {"type": "string"}
            for k in (
                "year_column",
                "entity_column",
                "value_column",
                "unit",
                "output_unit",
                "label",
                "decimal_separator",
            )
        },
        "entities": {"type": "array", "items": {"type": "string"}, "maxItems": 200},
        "missing_values": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}
# Filters use a list in model requests (strict JSON schema cannot allow arbitrary keys).
MODEL_MAPPING_SCHEMA = {
    **MAPPING_SCHEMA,
    "properties": {
        **MAPPING_SCHEMA["properties"],
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["column", "value"],
                "properties": {"column": {"type": "string"}, "value": {"type": "string"}},
            },
        },
    },
}
MODEL_MAPPING_SCHEMA["required"] = list(MODEL_MAPPING_SCHEMA["properties"])


@overload
def read_csv(
    body: bytes, *, with_line_numbers: Literal[False] = False, delimiter: str | None = None
) -> tuple[list[str], list[dict[str, str]]]: ...


@overload
def read_csv(
    body: bytes, *, with_line_numbers: Literal[True], delimiter: str | None = None
) -> tuple[list[str], list[dict[str, str]], list[int]]: ...


def read_csv(body, *, with_line_numbers=False, delimiter=None):
    if len(body) > 5_000_000:
        raise ValueError("CSV exceeds the 5 MB analysis limit")
    text = body.decode("utf-8-sig")
    if text.lstrip().startswith(("<", "{", "[")):
        raise ValueError("Source is not a supported CSV table")
    lines = text.splitlines(keepends=True)
    offset = 0
    while offset < len(lines) and (
        not lines[offset].strip() or lines[offset].lstrip().startswith("#")
    ):
        offset += 1
    text = "".join(lines[offset:])
    try:
        dialect = csv.excel if delimiter else csv.Sniffer().sniff(text[:10000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(
        io.StringIO(text), dialect=dialect, **({"delimiter": delimiter} if delimiter else {})
    )
    headers = [h.strip() for h in next(reader, [])]
    if (
        not headers
        or any(not h for h in headers)
        or len(headers) > 100
        or len(set(headers)) != len(headers)
    ):
        raise ValueError("CSV needs unique column names (at most 100)")
    rows, numbers = [], []
    previous_line = reader.line_num
    for row in reader:
        start_line = offset + previous_line + 1
        previous_line = reader.line_num
        if not row:
            continue
        if len(rows) >= 50000 or len(row) != len(headers):
            raise ValueError("CSV has too many or malformed rows")
        rows.append(dict(zip(headers, row, strict=True)))
        numbers.append(start_line)
    if not rows:
        raise ValueError("CSV contains no observations")
    return (headers, rows, numbers) if with_line_numbers else (headers, rows)


def analyse_csv(body, mapping, scope):
    headers, rows, line_numbers = read_csv(body, with_line_numbers=True)
    year_key, value_key = mapping["year_column"], mapping["value_column"]
    entity_key = mapping.get("entity_column", "")
    filters = mapping.get("filters", {})
    if isinstance(filters, list):
        filters = {item["column"]: item["value"] for item in filters}
    if not set([year_key, value_key, *filters, *([entity_key] if entity_key else [])]) <= set(
        headers
    ):
        raise ValueError("Mapping names columns absent from downloaded CSV")
    unit, output = mapping["unit"], mapping["output_unit"]
    factor = 1 if unit == output else CONVERSIONS.get((unit, output))
    if factor is None or not unit:
        raise ValueError("Unsupported or unspecified unit conversion")
    decimal = mapping.get("decimal_separator", ".")
    if decimal not in {".", ","}:
        raise ValueError("Unsupported decimal separator")
    entities = mapping.get("entities") or []
    if entity_key and not entities:
        raise ValueError("Explicit entity selection is required")
    missing = set(mapping.get("missing_values") or ["", "NA", ":"]) | {""}
    records = {}
    for index, row in zip(line_numbers, rows, strict=True):
        if any(row[k] != v for k, v in filters.items()):
            continue
        entity = row[entity_key] if entity_key else mapping["label"]
        if entity_key and entity not in entities:
            continue
        if not re.fullmatch(r"(?:18|19|20|21)\d{2}", row[year_key].strip()):
            raise ValueError("Expected annual four-digit years; aggregation is not automatic")
        year = int(row[year_key])
        if scope.get("start_year") is not None and year < scope["start_year"]:
            continue
        if scope.get("end_year") is not None and year > scope["end_year"]:
            continue
        key = entity, year
        if key in records:
            raise ValueError("Duplicate entity/year; select additional dimensions explicitly")
        raw = row[value_key].strip()
        value = None
        if raw not in missing:
            normalized = raw.replace(decimal, ".")
            if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", normalized):
                raise ValueError("Ambiguous or invalid numeric observation")
            value = float(normalized) * factor
            if not math.isfinite(value):
                raise ValueError("Non-finite observation")
        records[key] = {"year": year, "value": value, "source_row": index, "source_value": raw}
    if not records or not any(r["value"] is not None for r in records.values()):
        raise ValueError("No numeric observations match the selected scope")
    start = scope.get("start_year") or min(y for _, y in records)
    end = scope.get("end_year") or max(y for _, y in records)
    if end - start > 200:
        raise ValueError("Annual series exceeds the 200-year limit")
    series = []
    for entity in entities if entity_key else [mapping["label"]]:
        annual = [
            records.get(
                (entity, y), {"year": y, "value": None, "source_row": None, "source_value": None}
            )
            for y in range(start, end + 1)
        ]
        first, last = annual[0]["value"], annual[-1]["value"]
        series.append(
            {
                "entity": entity,
                **(
                    {
                        "identity": {
                            "geography": mapping.get("identity_geography", entity),
                            "dimensions": mapping.get("identity_dimensions", {}),
                        }
                    }
                    if "identity_geography" in mapping or "identity_dimensions" in mapping
                    else {}
                ),
                "label": mapping["label"],
                "unit": output,
                "annual": annual,
                "missing_years": [r["year"] for r in annual if r["value"] is None],
                **changes(first, last, output, mapping["label"], scope),
            }
        )
    return {
        "series": series,
        "mapping": mapping,
        "scope": scope,
        "method": "annual_observations_v1",
        "conversion_factor": factor,
        "limitations": [
            "No aggregation or interpolation was performed. Each series retains its own definition and unit.",
            "Column mapping and source suitability were assessed by a model and remain inspectable; numerical values come only from the downloaded table.",
            "Descriptive changes do not establish causation or statistical significance.",
        ],
    }
