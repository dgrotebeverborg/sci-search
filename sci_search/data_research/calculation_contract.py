"""Bounded, declarative numerical outputs; no model-written expressions."""

OPERATIONS = (
    "index",
    "real_index",
    "deflate",
    "convert",
    "share",
    "difference",
    "percentage_point_change",
)
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

# Mathematical intent is separate from the executable operation. In particular,
# subtraction across groups must never be satisfied by a temporal difference.
REQUEST_KINDS = {
    "index": ("index", None),
    "real_index": ("real_index", None),
    "deflate": ("deflate", None),
    "convert": ("convert", None),
    "share": ("share", None),
    "year_on_year_difference": ("difference", False),
    "baseline_difference": ("difference", True),
    "year_on_year_percentage_points": ("percentage_point_change", False),
    "baseline_percentage_points": ("percentage_point_change", True),
    "cross_series_difference": None,
    "cross_series_percentage_points": None,
    "reference_mean_anomaly": None,
    "ratio": None,
    "other": None,
}

REQUEST_SCHEMA = {
    "type": "array",
    "maxItems": 10,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["description", "kind", "calculation_ids", "unresolved_reason"],
        "properties": {
            "description": {"type": "string"},
            "kind": {"type": "string", "enum": list(REQUEST_KINDS)},
            "calculation_ids": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
            "unresolved_reason": {"type": "string"},
        },
    },
}


def validate_requests(items, calculations):
    if not isinstance(items, list) or len(items) > 10:
        raise ValueError("Invalid calculation requests")
    available = {c["id"] for c in calculations}
    covered, unresolved = set(), []
    for item in items:
        legacy_fields = {"description", "calculation_ids", "unresolved_reason"}
        if not isinstance(item, dict) or set(item) not in (legacy_fields, legacy_fields | {"kind"}):
            raise ValueError("Invalid calculation request fields")
        description, ids, reason = (
            item[k] for k in ("description", "calculation_ids", "unresolved_reason")
        )
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 500
            or not isinstance(reason, str)
            or len(reason) > 500
            or not isinstance(ids, list)
            or len(ids) > 10
            or any(not isinstance(i, str) or i not in available for i in ids)
            or len(set(ids)) != len(ids)
            or bool(ids) == bool(reason.strip())
        ):
            raise ValueError(
                "Each calculation request needs executable IDs or an unresolved reason"
            )
        if "kind" in item:
            kind = item["kind"]
            if not isinstance(kind, str) or kind not in REQUEST_KINDS:
                raise ValueError("Invalid calculation request meaning")
            expected = REQUEST_KINDS[kind]
            for calculation in calculations:
                if calculation["id"] not in ids:
                    continue
                if (
                    expected is None
                    or calculation["operation"] != expected[0]
                    or (
                        expected[1] is not None
                        and (calculation["base_year"] is not None) != expected[1]
                    )
                ):
                    raise ValueError(
                        f"Calculation {calculation['id']!r} does not implement requested meaning "
                        f"{kind!r}; retain unsupported requests with an unresolved reason"
                    )
        covered.update(ids)
        if reason.strip():
            unresolved.append((description.strip() + ": " + reason.strip())[:500])
    if covered != available:
        raise ValueError("Calculation requests must account for every executable calculation")
    return unresolved


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
        elif op in {"difference", "percentage_point_change"}:
            if year is not None and (type(year) is not int or not 1800 <= year <= 2100):
                raise ValueError("Invalid difference base year")
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
