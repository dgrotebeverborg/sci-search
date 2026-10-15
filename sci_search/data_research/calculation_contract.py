"""Bounded, declarative numerical outputs; no model-written expressions."""

OPERATIONS = ("index", "real_index", "deflate", "convert", "share")
FIELDS = {
    "id": {"type": "string"},
    "label": {"type": "string"},
    "operation": {"type": "string", "enum": list(OPERATIONS)},
    "input": {"type": "string"},
    "reference": {"type": ["string", "null"]},
    "base_year": {"type": ["integer", "null"]},
    "target_unit": {"type": ["string", "null"]},
}
SCHEMA = {
    "type": "array",
    "maxItems": 10,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": list(FIELDS),
        "properties": FIELDS,
    },
}


def validate(items, measurements):
    if not isinstance(items, list) or len(items) > 10:
        raise ValueError("Invalid requested calculations")
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise ValueError("Invalid calculation fields")
        for key in ("id", "label", "operation", "input"):
            if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > 300:
                raise ValueError("Invalid calculation " + key)
        op, ref, year, unit = (
            item[k] for k in ("operation", "reference", "base_year", "target_unit")
        )
        if item["id"] in seen or op not in OPERATIONS or item["input"] not in measurements:
            raise ValueError(
                f"Unknown or duplicate calculation {item['id']!r}: operation must be one of {OPERATIONS}; input {item['input']!r} must exactly match one of {measurements}"
            )
        if op in {"share", "real_index", "deflate"}:
            if not isinstance(ref, str) or ref not in measurements or ref == item["input"]:
                raise ValueError(
                    f"Calculation requires a distinct requested reference measurement: {ref!r} must exactly match one of {measurements}"
                )
        elif ref is not None:
            raise ValueError("Unexpected calculation reference")
        if op in {"index", "real_index", "deflate"}:
            if type(year) is not int or not 1800 <= year <= 2100:
                raise ValueError("Calculation requires an explicit base year")
        elif year is not None:
            raise ValueError("Unexpected calculation base year")
        if op == "convert":
            if not isinstance(unit, str) or not unit.strip() or len(unit) > 100:
                raise ValueError("Conversion requires a target unit")
        elif unit is not None:
            raise ValueError("Unexpected calculation target unit")
        seen.add(item["id"])
        result.append(dict(item))
    return result
