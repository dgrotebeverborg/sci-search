"""Our World in Data grapher CSV reader. Pure; also runs in the sandbox."""

import csv
import hashlib
import io
import json
import re


def prepare_owid(body, selection):
    if len(body) > 5_000_000:
        raise ValueError("OWID response exceeds the 5 MB analysis limit")
    envelope = json.loads(body.decode("utf-8"))
    columns = envelope["metadata"].get("columns", {})
    indicator = selection.get("indicator")
    if indicator not in columns:
        raise ValueError("Selected OWID indicator is not in the chart metadata")
    unit = (columns[indicator].get("unit") or columns[indicator].get("shortUnit") or "").strip()
    if not unit:
        raise ValueError("OWID indicator has no documented unit")
    reader = csv.DictReader(io.StringIO(envelope["csv"]))
    if not {"entity", "year", indicator} <= set(reader.fieldnames or []):
        raise ValueError("OWID CSV lacks entity, year or the selected indicator column")
    wanted = selection.get("entities") or []
    if len(wanted) > 60:
        raise ValueError("OWID selection exceeds 60 entities")
    rows = list(reader)
    observed = {r["entity"] for r in rows}
    if not wanted or not set(wanted) <= observed:
        raise ValueError("Selected OWID entities are not in the chart data")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Year", "Series", "Code", "Value", "Unit", "Status"])
    provenance, line, seen = {}, 2, set()
    for number, row in enumerate(rows, 2):
        if row["entity"] not in wanted:
            continue
        if not re.fullmatch(r"-?\d{1,4}", row["year"]):
            raise ValueError("dataset is not annual; no aggregation was performed")
        if (row["entity"], row["year"]) in seen:
            raise ValueError(f"OWID CSV has a duplicate {row['entity']} {row['year']} row")
        seen.add((row["entity"], row["year"]))
        value = row[indicator].strip() or ":"
        writer.writerow([row["year"], row["entity"], row.get("code", ""), value, unit, ""])
        provenance[str(line)] = {
            "source_reference": f"csv-line:{number}",
            "unit": unit,
            "status": "",
            "source_value": row[indicator],
        }
        line += 1
    table = output.getvalue().encode()
    return table, dict(
        format="owid_csv_v1",
        selection={"reader": "owid_csv", **{k: v for k, v in selection.items() if k != "reader"}},
        row_provenance=provenance,
        normalized_sha256=hashlib.sha256(table).hexdigest(),
        checks={"output_rows": line - 2},
        metadata=json.dumps(columns[indicator], ensure_ascii=False)[:30000],
        limitations=[
            "Our World in Data republishes data from the sources named in its metadata; check the original source definitions.",
        ],
    )
