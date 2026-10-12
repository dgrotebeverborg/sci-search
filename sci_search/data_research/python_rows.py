"""Deterministic publication contract for script-extracted annual observations.

This module is also copied into standalone research packages.
"""

import csv
import io
import math

try:
    from .tabular import analyse_csv
except ImportError:
    from tabular import analyse_csv


def analyse_observations(payload, scope):
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not 0 < len(rows) <= 50000:
        raise ValueError("Expected 1–50000 extracted observations")
    for key in ("assumptions", "checks"):
        notes = payload.get(key, [])
        if (
            not isinstance(notes, list)
            or len(notes) > 100
            or any(not isinstance(note, str) or len(note) > 2000 for note in notes)
        ):
            raise ValueError("Invalid extracted " + key)
    groups, seen = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Observation must be an object")
        for key in ("entity", "unit", "measurement", "source_reference"):
            if not isinstance(row.get(key), str) or not row[key].strip() or len(row[key]) > 2000:
                raise ValueError("Invalid observation " + key)
        if row["measurement"] not in scope["measurements"]:
            raise ValueError("Unrequested measurement")
        if type(row.get("year")) is not int or not 1800 <= row["year"] <= 2199:
            raise ValueError("Invalid observation year")
        value = row.get("value")
        if value is not None and type(value) not in (int, float):
            raise ValueError("Observation value must be numeric or null")
        if value is not None and not math.isfinite(value):
            raise ValueError("Observation must be finite")
        key = row["measurement"], row["entity"], row["year"]
        if key in seen:
            raise ValueError("Duplicate measurement/entity/year")
        seen.add(key)
        groups.setdefault((row["measurement"], row["unit"]), []).append(row)
    components = []
    for (measurement, unit), group in groups.items():
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["Year", "Entity", "Value"])
        for row in group:
            writer.writerow([row["year"], row["entity"], row["value"]])
        entities = list(dict.fromkeys(r["entity"] for r in group))
        if len(entities) > 1000:
            raise ValueError("Extracted data exceeds 1000 series")
        result = analyse_csv(
            stream.getvalue().encode(),
            dict(
                year_column="Year",
                entity_column="Entity",
                value_column="Value",
                entities=entities,
                unit=unit,
                output_unit=unit,
                label=measurement,
                filters={},
                missing_values=[""],
            ),
            scope,
        )
        references = {(r["entity"], r["year"]): r["source_reference"] for r in group}
        for series in result["series"]:
            for observation in series["annual"]:
                observation["source_reference"] = references.get(
                    (series["entity"], observation["year"])
                )
        components.append(result)
    return {
        "kind": "tabular",
        "method": "executed_python_extraction_v1",
        "scope": scope,
        "components": components,
        "series": [s for c in components for s in c["series"]],
        "limitations": [
            "Python extraction and its semantic review are model-assisted, not independent expert validation.",
            "Missing observations remain missing. Descriptive changes do not establish causation.",
        ],
    }
