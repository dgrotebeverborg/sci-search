"""Bounded annual statistical TSV reader, including Eurostat series keys and flags.

Format: https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-faq/tsv-format
"""

import csv
import gzip
import hashlib
import io
import json
import re
import zlib
from typing import Any

# These suffixes occur in publisher code labels when a table has no unit dimension.
# Never infer a unit from an opaque code or an arbitrary mention in a description.
DECLARED_UNITS = {"thousand hectares", "thousand tonnes", "tonnes per hectare", "percentage"}


def declared_unit(codes, labels):
    if "unit" in codes:
        return codes["unit"]
    units = {
        label.rpartition(" - ")[2]
        for dimension, code in codes.items()
        if (label := labels.get(dimension, {}).get(code, ""))
        and label.rpartition(" - ")[1]
        and label.rpartition(" - ")[2] in DECLARED_UNITS
    }
    return next(iter(units)) if len(units) == 1 else ""


MAX_EXPANDED = 10_000_000
SELECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "filters": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dimension": {"type": "string"},
                    "values": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 200,
                    },
                },
                "required": ["dimension", "values"],
            },
        },
        "series_dimensions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 8,
        },
        "reason": {"type": "string"},
    },
    "required": ["filters", "series_dimensions", "reason"],
}


def decompress(body):
    if not body.startswith(b"\x1f\x8b"):
        return body
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            expanded = stream.read(MAX_EXPANDED + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError("Invalid GZIP dataset") from exc
    if len(expanded) > MAX_EXPANDED:
        raise ValueError("GZIP dataset exceeds the expanded-size limit")
    return expanded


def _read(body):
    data = decompress(body)
    if len(data) > MAX_EXPANDED:
        raise ValueError("Statistical table exceeds expanded-size limit")
    text = data.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text), delimiter="\t", strict=True)
    header = next(reader, [])
    if not header or not header[0].endswith("\\TIME_PERIOD"):
        raise ValueError("Not a statistical TSV table")
    dimensions = header[0].removesuffix("\\TIME_PERIOD").split(",")
    if not all(re.fullmatch("[A-Za-z][A-Za-z0-9_]*", d) for d in dimensions) or len(
        set(dimensions)
    ) != len(dimensions):
        raise ValueError("Invalid statistical dimension names")
    if set(dimensions) & {"Year", "Value", "Series", "Unit", "Status"}:
        raise ValueError("Statistical dimension collides with output columns")
    years = [y.strip() for y in header[1:]]
    if (
        not years
        or len(years) > 201
        or len(set(years)) != len(years)
        or any(not re.fullmatch(r"(18|19|20|21)\d{2}", y) for y in years)
    ):
        raise ValueError("Statistical reader requires distinct annual periods")
    records = []
    seen = set()
    previous = reader.line_num
    for row in reader:
        line = previous + 1
        previous = reader.line_num
        if not row:
            continue
        if len(records) >= 50000 or len(row) != len(header):
            raise ValueError("Malformed or excessive statistical series")
        codes = row[0].split(",")
        if len(codes) != len(dimensions) or not all(codes) or tuple(codes) in seen:
            raise ValueError("Invalid or duplicate statistical series key")
        seen.add(tuple(codes))
        records.append((line, dict(zip(dimensions, codes, strict=True)), row[1:]))
    if not records:
        raise ValueError("Statistical table has no series")
    return dimensions, years, records


def inspect_statistics(body) -> dict[str, Any]:
    dimensions, years, records = _read(body)
    return dict(
        dimensions=dimensions,
        years=years,
        series_count=len(records),
        dimension_values={d: list(dict.fromkeys(c[d] for _, c, _ in records)) for d in dimensions},
        sample=[
            {"source_row": line, "dimensions": c, "observations": values[:4]}
            for line, c, values in records[:5]
        ],
    )


def inspect_if_statistics(body):
    data = decompress(body)
    if b"\\TIME_PERIOD\t" not in data[:2000]:
        return None
    return inspect_statistics(data)


def prepare_statistics(body, selection):
    dimensions, years, records = _read(body)
    preview = inspect_statistics(body)
    filters = {}
    for item in selection["filters"]:
        d, values = item["dimension"], item["values"]
        if (
            d in filters
            or d not in dimensions
            or not values
            or len(set(values)) != len(values)
            or not set(values) <= set(preview["dimension_values"][d])
        ):
            raise ValueError("Selection contains duplicate or unobserved dimension codes")
        filters[d] = values
    if set(filters) != set(dimensions):
        raise ValueError(
            "Every dimension requires an explicit filter, including comparison dimensions"
        )
    series_dims = selection["series_dimensions"]
    if (
        not series_dims
        or len(set(series_dims)) != len(series_dims)
        or not set(series_dims) <= set(dimensions)
    ):
        raise ValueError("Select observed series dimensions")
    for d in dimensions:
        if d not in series_dims and len(filters.get(d, [])) != 1:
            raise ValueError("Every non-series dimension must be fixed to one observed code: " + d)
    if "unit" in dimensions and len(filters.get("unit", [])) != 1:
        raise ValueError("Select one statistical unit")
    if "freq" in dimensions and filters.get("freq") != ["A"]:
        raise ValueError("Only annual frequency can be analysed")
    selected = [r for r in records if all(r[1][d] in values for d, values in filters.items())]
    if not selected or len(selected) > 200 or len(selected) * len(years) > 50000:
        raise ValueError(
            "Selected statistical series is empty or too large; narrow dimension filters"
        )
    labels = selection.get("code_labels", {})
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Year", "Series", *dimensions, "Value", "Unit", "Status"])
    provenance = {}
    flag_counts = {}
    numeric = 0
    line_out = 2
    keys = set()
    for line, codes, observations in selected:
        # Codes stay in the label, so identically named categories remain distinct.
        entity = " | ".join(
            d
            + "="
            + codes[d]
            + (" (" + labels[d][codes[d]] + ")" if codes[d] in labels.get(d, {}) else "")
            for d in series_dims
        )
        if entity in keys:
            raise ValueError("Selected dimensions collapse distinct statistical series")
        keys.add(entity)
        if "\n" in entity or "\r" in entity:
            raise ValueError("Invalid code label")
        for year, cell in zip(years, observations, strict=True):
            match = re.fullmatch(
                r"\s*(:|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?:\s+([a-zA-Z ]+))?\s*", cell
            )
            if not match:
                raise ValueError("Unsupported statistical observation or status: " + cell[:80])
            raw, status = match.group(1), (match.group(2) or "").strip()
            value = ":" if "c" in status.lower() else raw
            if value != ":":
                numeric += 1
            if status:
                flag_counts[status] = flag_counts.get(status, 0) + 1
            unit = declared_unit(codes, labels)
            writer.writerow([year, entity, *[codes[d] for d in dimensions], value, unit, status])
            provenance[str(line_out)] = {
                "source_reference": f"line:{line}; period:{year}",
                "unit": unit,
                "status": status,
                "source_value": cell,
                "dimensions": codes,
            }
            line_out += 1
    table = output.getvalue().encode()
    if len(table) > 5_000_000:
        raise ValueError("Normalized statistical table exceeds analysis limit; narrow filters")
    return table, dict(
        format="statistical_tsv_v1",
        selection={"reader": "statistical_tsv", **selection},
        row_provenance=provenance,
        normalized_sha256=hashlib.sha256(table).hexdigest(),
        checks={
            "input_series": len(records),
            "selected_series": len(selected),
            "output_rows": len(selected) * len(years),
            "numeric_observations": numeric,
            "status_counts": flag_counts,
        },
        metadata=json.dumps(
            {
                "dimension_codes": preview["dimension_values"],
                "code_labels": labels,
                "selected_filters": filters,
                "unit_column": "Unit retains the source unit code when present. Without a unit dimension, only an explicit recognized unit suffix in a selected code label is retained. YR denotes years in Eurostat tables.",
                "status_flags": "Original status codes retained; colon means missing. b = break in time series; p = provisional; e = estimated; d = differing definition. Unknown codes are retained.",
            },
            ensure_ascii=False,
        ),
        limitations=[
            "Selection assessment: " + selection.get("reason", ""),
            "Each selected country/category combination is kept as a separate series. No countries, sexes or ages were averaged or combined.",
            "Coverage varies by series. Missing values remain missing, including requested years outside the published period.",
            "Original statistical status flags are retained. Endpoint changes are withheld for series marked with breaks, differing definitions or unknown quality codes.",
        ],
    )


def load_code_labels(preview, fetch, source_url, save):
    """Use only the documented Eurostat codelist API; retain exact responses."""
    from urllib.parse import urlsplit

    if urlsplit(source_url).hostname != "ec.europa.eu":
        return {}
    labels = {}
    for dimension in preview["dimensions"]:
        url = f"https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/codelist/ESTAT/{dimension}?format=TSV"
        try:
            body, _, final = fetch(url)
            if urlsplit(final).hostname != "ec.europa.eu":
                continue
            text = decompress(body).decode("utf-8-sig")
            pairs = list(csv.reader(io.StringIO(text), delimiter="\t"))
            if not pairs or any(len(r) != 2 for r in pairs):
                continue
            if len({r[0] for r in pairs}) != len(pairs):
                continue
            allowed = set(preview["dimension_values"][dimension])
            labels[dimension] = {code: label for code, label in pairs if code in allowed}
            save(dimension, body, url)
        except (OSError, ValueError, UnicodeError, csv.Error):
            continue
    return labels
