"""Backward-compatible, bounded descriptions of the requested data, not source claims."""

import math

from sci_search.data_research.wildfire import COUNTRY_NAMES


def normalize_geography(items, countries, geography):
    """Remove only an exact duplicate of the entity axis, never a second geographic concept."""
    names = {code.casefold(): name.casefold() for code, name in COUNTRY_NAMES.items()}
    names.update({"nederland": "netherlands", "duitsland": "germany"})

    def canonical(value):
        text = value.strip().casefold()
        return names.get(text, text)

    result = []
    for item in items:
        entities = item.get("entities") or countries or [geography]
        keys = {canonical(e) for e in entities}
        breakdowns = []
        for dim in item.get("breakdowns", []):
            duplicate = (
                dim["dimension"].strip().casefold()
                in {
                    "country",
                    "countries",
                    "city",
                    "cities",
                    "geography",
                    "land",
                    "landen",
                    "stad",
                    "steden",
                }
                and len(dim["values"]) == len(keys)
                and {canonical(v) for v in dim["values"]} == keys
            )
            if not duplicate:
                breakdowns.append(dim)
        result.append({**item, "breakdowns": breakdowns})
    return result


ENUMS = {
    "definition_policy": ("choose_documented", "specified"),
    "frequency": ("annual", "monthly", "daily", "unspecified"),
    "measure_type": ("ratio", "interval", "percentage", "index", "unknown"),
    "observation_type": ("observed", "projected", "unspecified"),
}
SCHEMA = {
    "type": "array",
    "maxItems": 5,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["measurement", "definition", "entities", "breakdowns", *ENUMS],
        "properties": {
            "measurement": {"type": "string"},
            "definition": {"type": "string"},
            "entities": {"type": "array", "items": {"type": "string"}, "maxItems": 60},
            **{key: {"type": "string", "enum": list(values)} for key, values in ENUMS.items()},
            "breakdowns": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["dimension", "values"],
                    "properties": {
                        "dimension": {"type": "string"},
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                    },
                },
            },
        },
    },
}


def _strings(values, limit):
    return (
        isinstance(values, list)
        and len(values) <= limit
        and all(isinstance(v, str) and 0 < len(v.strip()) <= 300 for v in values)
        and len(set(values)) == len(values)
    )


def validate(items, measurements):
    if not isinstance(items, list) or len(items) > 5:
        raise ValueError("Invalid data requirements")
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid data requirement")
        name = item.get("measurement")
        if not isinstance(name, str) or name not in measurements or name in seen:
            raise ValueError(
                f"Unknown or duplicate requirement measurement {name!r}; copy an exact unique name from {measurements}"
            )
        seen.add(name)
        normalized = {"measurement": name}
        definition = item.get("definition", "")
        if not isinstance(definition, str) or len(definition) > 2000:
            raise ValueError("Invalid requirement definition")
        normalized["definition"] = definition
        for key, choices in ENUMS.items():
            value = item.get(key, "annual" if key == "frequency" else choices[-1])
            if value not in choices:
                raise ValueError("Invalid requirement " + key)
            normalized[key] = value
        entities = item.get("entities", [])
        if not _strings(entities, 60):
            raise ValueError("Invalid requirement entities")
        normalized["entities"] = entities.copy()
        breakdowns = item.get("breakdowns", [])
        if not isinstance(breakdowns, list) or len(breakdowns) > 4:
            raise ValueError("Invalid requirement breakdowns")
        dims, normalized["breakdowns"] = set(), []
        for entry in breakdowns:
            if not isinstance(entry, dict):
                raise ValueError("Invalid requirement breakdown")
            dimension, values = entry.get("dimension"), entry.get("values")
            if (
                not isinstance(dimension, str)
                or not dimension.strip()
                or len(dimension) > 100
                or dimension in dims
                or not _strings(values, 20)
                or not values
            ):
                raise ValueError("Invalid requirement breakdown")
            dims.add(dimension)
            normalized["breakdowns"].append({"dimension": dimension, "values": values.copy()})
        if (
            math.prod(len(d["values"]) for d in normalized["breakdowns"]) * max(60, len(entities))
            > 6000
        ):
            raise ValueError("Requirement breakdown exceeds 6000 coverage cells")
        result.append(normalized)
    return result
