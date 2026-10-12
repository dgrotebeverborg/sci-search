"""Bounded, declarative table preparation. Never execute model-provided code."""

import copy
import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime
from pathlib import PurePosixPath

try:
    from .tabular import read_csv
except ImportError:
    from tabular import read_csv

ENCODINGS = ("utf-8-sig", "utf-16", "cp1252")
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entry": {"type": "string"},
        "encoding": {"type": "string", "enum": list(ENCODINGS)},
        "delimiter": {"type": "string", "enum": [",", ";", "\t", "|"]},
        "header_row": {"type": "integer", "minimum": 1, "maximum": 40},
        "reason": {"type": "string"},
    },
}
PLAN_SCHEMA["required"] = list(PLAN_SCHEMA["properties"])
PLAN_SCHEMA["properties"]["end_row"] = {
    "type": ["integer", "null"],
    "minimum": 2,
    "description": "Optional inclusive physical last line of a complete table section, immediately before a different table header. Never truncate observations.",
}
TRANSFORM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["none", "unpivot", "count_events", "year_from_date", "daily_mean"],
        },
        "columns": {"type": "array", "items": {"type": "string"}, "maxItems": 200},
        "year_column": {"type": "string"},
        "id_column": {"type": "string"},
        "entity_column": {"type": "string"},
        "date_format": {"type": "string", "enum": ["", "%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]},
        "reason": {"type": "string"},
    },
}
TRANSFORM_SCHEMA["required"] = list(TRANSFORM_SCHEMA["properties"])
TRANSFORM_SCHEMA["properties"].update(
    {
        "value_column": {"type": "string"},
        "decimal_separator": {"type": "string", "enum": [".", ","]},
        "missing_values": {"type": "array", "items": {"type": "string"}},
        "aggregation_evidence": {
            "type": "string",
            "description": "Exact source quote explicitly identifying daily means, not once-daily snapshots.",
        },
    }
)


def _files(body):
    if body.startswith(b"\x1f\x8b"):
        try:
            from .statistical_tables import decompress
        except ImportError:
            from statistical_tables import decompress
        body = decompress(body)
    if len(body) > 5_000_000:
        raise ValueError("Table exceeds the 5 MB analysis limit")
    if not body.startswith(b"PK"):
        return {"": body}, ""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(entries) > 40 or sum(e.file_size for e in entries) > 10_000_000:
            raise ValueError("Data ZIP exceeds its expansion limit")
        if (
            len(set(names)) != len(names)
            or any(
                PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n
                for n in names
            )
            or any(e.flag_bits & 1 for e in entries)
        ):
            raise ValueError("Unsafe data ZIP entries")
        tables = {n: archive.read(n) for n in names if n.lower().endswith((".csv", ".tsv"))}
        metadata = "\n".join(
            n + "\n" + archive.read(n)[:10000].decode("utf-8-sig", errors="replace")
            for n in names
            if n.lower().endswith((".txt", ".md", ".xml"))
        )[:30000]
        return tables, metadata


def _decode(body, encoding):
    if encoding not in ENCODINGS:
        raise ValueError("Unsupported encoding")
    if encoding == "utf-16" and not body.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("UTF-16 requires a byte order mark")
    text = body.decode(encoding)
    if "\x00" in text or text.lstrip().startswith(("<", "{", "[")):
        raise ValueError("Source is not a delimited text table")
    return text


def inspect_table(body):
    tables, metadata = _files(body)
    candidates = []
    for entry, data in tables.items():
        for encoding in ENCODINGS:
            try:
                text = _decode(data, encoding)
            except (ValueError, UnicodeError):
                continue
            candidates.append(
                {
                    "entry": entry,
                    "encoding": encoding,
                    "lines": [
                        {"line": i + 1, "text": line[:1000]}
                        for i, line in enumerate(text.splitlines()[:40])
                    ],
                }
            )
            break
    if not candidates:
        raise ValueError("No supported text tables found for inspection")
    return {"candidates": candidates, "metadata": metadata}


def _write(headers, rows, origins):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    provenance = {}
    line = output.getvalue().count("\n") + 1
    for row, origin in zip(rows, origins, strict=True):
        if line > 200000 or len(rows) > 50000:
            raise ValueError("Prepared table exceeds row limit")
        rendered = io.StringIO(newline="")
        csv.writer(rendered).writerow(row)
        record = rendered.getvalue()
        output.write(record)
        provenance[str(line)] = {"source_reference": origin}
        line += record.count("\n")
    data = output.getvalue().encode()
    read_csv(data)  # Validate every output row, not just the preview.
    return data, provenance


def prepare_delimited(body, selection=None):
    tables, metadata = _files(body)
    if selection is None:
        if len(tables) != 1:
            raise ValueError("Select one observed table from the ZIP")
        entry, raw = next(iter(tables.items()))
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = _decode(raw, encoding)
        lines = text.splitlines(keepends=True)
        offset = 0
        while offset < len(lines) and (
            not lines[offset].strip() or lines[offset].lstrip().startswith("#")
        ):
            offset += 1
        try:
            delimiter = (
                csv.Sniffer().sniff("".join(lines[offset:])[:10000], delimiters=",;\t|").delimiter
            )
        except csv.Error:
            delimiter = ","
        selection = dict(entry=entry, encoding=encoding, delimiter=delimiter, header_row=offset + 1)
    entry = selection.get("entry", "")
    if entry not in tables:
        raise ValueError("Selected table was not observed")
    delimiter, header_row = selection["delimiter"], selection["header_row"]
    if (
        delimiter not in ",;\t|"
        or len(delimiter) != 1
        or type(header_row) is not int
        or not 1 <= header_row <= 40
    ):
        raise ValueError("Invalid delimiter or header row")
    text = _decode(tables[entry], selection["encoding"])
    lines = text.splitlines(keepends=True)
    metadata += "\n" + "".join(lines[: header_row - 1])
    end_row = selection.get("end_row")
    if end_row is not None:
        if type(end_row) is not int or not header_row < end_row <= len(lines):
            raise ValueError("Invalid table section boundary")
        tail = "".join(lines[end_row:])
        boundary = next(
            (row for row in csv.reader(io.StringIO(tail), delimiter=delimiter, strict=True) if row),
            [],
        )
        if end_row < len(lines) and (
            len([cell for cell in boundary if cell.strip()]) < 2
            or any(cell.strip() and not re.search(r"[a-zA-Z]", cell) for cell in boundary)
        ):
            raise ValueError(
                "The selected section boundary would discard observations instead of a new table header"
            )
        metadata += "\nFollowing table sections retained in original source:\n" + tail[:10000]
    reader = csv.reader(
        io.StringIO("".join(lines[header_row - 1 : end_row])), delimiter=delimiter, strict=True
    )
    headers = [h.strip() for h in next(reader, [])]
    if end_row is not None and end_row < len(lines) and [c.strip() for c in boundary] == headers:
        raise ValueError("The selected section boundary repeats the same table header")
    if len(headers) > 300:
        raise ValueError("Table exceeds column limit")
    rows, origins = [], []
    previous = reader.line_num
    for row in reader:
        source_line = header_row + previous
        previous = reader.line_num
        if not row:
            continue
        if len(rows) >= 50000 or len(row) != len(headers):
            raise ValueError("Malformed or excessive table rows; no rows were silently dropped")
        rows.append(row)
        origins.append(f"{entry}:{source_line}" if entry else f"line:{source_line}")
    original_width = len(headers)
    while headers and not headers[-1] and all(not r[len(headers) - 1].strip() for r in rows):
        headers.pop()
    if len(headers) < 2 or any(not h for h in headers) or len(set(headers)) != len(headers):
        raise ValueError("Nonempty unique column names required; inspect the header row")
    rows = [r[: len(headers)] for r in rows]
    data, provenance = _write(headers, rows, origins)
    return data, {
        "format": "prepared_delimited_v1",
        "entry": entry,
        "selection": {"reader": "delimited", **selection},
        "metadata": metadata,
        "row_provenance": provenance,
        "normalized_sha256": hashlib.sha256(data).hexdigest(),
        "checks": {
            **({"selected_end_row": end_row} if end_row is not None else {}),
            "input_rows": len(rows),
            "output_rows": len(rows),
            "removed_empty_columns": original_width - len(headers),
        },
        "limitations": [
            f"Table preparation: {selection['encoding']}; header at line {header_row}; removed {original_width - len(headers)} entirely empty trailing columns. "
            + (
                f"Selected complete section through line {end_row}; other sections retained in source."
                if end_row is not None
                else "All data rows retained."
            )
        ],
    }


def transform_table(body, preparation, plan):
    if preparation.get("format") in {"cbs_csv_zip_v1", "statistical_tsv_v1"}:
        raise ValueError(
            "CBS/statistical tables are already normalized; further transformations must preserve authoritative units and are not supported"
        )
    if plan["operation"] == "daily_mean":
        try:
            from .daily import aggregate_daily
        except ImportError:
            from daily import aggregate_daily
        return aggregate_daily(body, preparation, plan)
    headers, rows, lines = read_csv(body, with_line_numbers=True)
    operation = plan["operation"]
    prep = copy.deepcopy(preparation)
    origins = [
        prep.get("row_provenance", {}).get(str(n), {}).get("source_reference", f"line:{n}")
        for n in lines
    ]
    output, refs = [], []
    if operation == "unpivot":
        columns = plan["columns"]
        if (
            not columns
            or len(set(columns)) != len(columns)
            or not set(columns) <= set(headers)
            or any(not re.fullmatch(r"(18|19|20|21)\d{2}", c) for c in columns)
        ):
            raise ValueError("Unpivot requires distinct observed four-digit year columns")
        keep = [h for h in headers if h not in columns]
        if set(keep) & {"Year", "Value"} or len(rows) * len(columns) > 50000:
            raise ValueError("Unpivot collides with columns or exceeds row limit")
        for row, origin in zip(rows, origins, strict=True):
            for column in columns:
                output.append([row[h] for h in keep] + [column, row[column]])
                refs.append(f"{origin}; column:{column}")
        out_headers = keep + ["Year", "Value"]
    elif operation in {"count_events", "year_from_date"}:
        key, fmt = plan["year_column"], plan.get("date_format", "")
        if key not in headers or fmt not in {"", "%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"}:
            raise ValueError(
                "Select an observed year/date column and explicit supported date format"
            )
        years = []
        for row in rows:
            raw = row[key].strip()
            if fmt in {"", "%Y"}:
                if not re.fullmatch(r"(18|19|20|21)\d{2}", raw):
                    raise ValueError("Expected an unambiguous year; explicit date format required")
                year = int(raw)
            else:
                year = datetime.strptime(raw, fmt).year
            if not 1800 <= year <= 2199:
                raise ValueError("Year outside supported range")
            years.append(str(year))
        if operation == "year_from_date":
            if "Year" in headers and key != "Year":
                raise ValueError("Year output column already exists")
            out_headers = [h for h in headers if h != key] + ["Year"]
            output = [
                [row[h] for h in headers if h != key] + [year]
                for row, year in zip(rows, years, strict=True)
            ]
            refs = origins
        else:
            identifier, entity = plan["id_column"], plan.get("entity_column", "")
            if identifier not in headers or (entity and entity not in headers):
                raise ValueError("Event ID and entity columns must be observed")
            ids = [r[identifier].strip() for r in rows]
            if not all(ids) or len(set(ids)) != len(ids):
                raise ValueError(
                    "Event identifiers must be nonempty and unique; no deduplication guessed"
                )
            if entity in {"Year", "Recorded events"}:
                raise ValueError("Output column collision")
            groups = {}
            for row, year, origin in zip(rows, years, origins, strict=True):
                if entity and not row[entity].strip():
                    raise ValueError("Missing event geography/category")
                group = (row[entity] if entity else "", year)
                groups.setdefault(group, []).append(origin)
            out_headers = ([entity] if entity else []) + ["Year", "Recorded events"]
            for (label, year), sources in sorted(groups.items()):
                output.append(([label] if entity else []) + [year, str(len(sources))])
                refs.append("; ".join(sources))
            prep.setdefault("checks", {})["counted_events"] = len(ids)
            prep.setdefault("limitations", []).append(
                "Counts describe unique recorded events, not underlying hazard or risk. Missing years are not filled with zero; reporting completeness and changes in coverage require separate assessment."
            )
    else:
        raise ValueError("Unsupported transformation; executable code is never accepted")
    data, provenance = _write(out_headers, output, refs)
    prep["row_provenance"] = provenance
    prep["normalized_sha256"] = hashlib.sha256(data).hexdigest()
    prep.setdefault("transformations", []).append(plan)
    prep.setdefault("checks", {})["transformed_rows"] = len(output)
    prep.setdefault("limitations", []).append(
        f"Applied checked transformation: {operation}. " + plan.get("reason", "")
    )
    return data, prep
