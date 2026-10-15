"""Independently check direct numeric references; never certify semantic meaning.

This module travels with offline calculation packages. Unsupported or absent locators
remain explicitly unverified; an asserted structured locator must actually resolve.
"""

import json
import math
from decimal import Decimal

try:
    from .tabular import read_csv
except ImportError:
    from tabular import read_csv


def verify_observations(body, payload):
    documents = {}
    references = []
    verified, unverified = 0, 0
    for row in payload["observations"]:
        locator = row.get("source_locator")
        if locator is None:
            unverified += 1
            continue
        if not isinstance(locator, dict):
            raise ValueError("Malformed numeric source reference")
        kind = locator.get("format")
        try:
            if kind == "json":
                if "json" not in documents:
                    documents["json"] = json.loads(body)
                value = documents["json"]
                path = locator.get("path")
                if not isinstance(path, list) or not path or len(path) > 40:
                    raise ValueError("Invalid JSON reference path")
                for key in path:
                    if isinstance(value, list):
                        if type(key) is not int or key < 0:
                            raise ValueError("Invalid JSON reference index")
                    elif not isinstance(value, dict) or not isinstance(key, str):
                        raise ValueError("Invalid JSON reference key")
                    value = value[key]
            elif kind == "csv":
                if "csv" not in documents:
                    _, rows, numbers = read_csv(body, with_line_numbers=True)
                    documents["csv"] = dict(zip(numbers, rows, strict=True))
                if type(locator.get("line")) is not int:
                    raise ValueError("Invalid CSV reference line")
                value = documents["csv"][locator["line"]][locator["column"]]
            elif kind == "text":
                if "lines" not in documents:
                    documents["lines"] = body.decode("utf-8-sig").splitlines()
                line, column = locator.get("line"), locator.get("column")
                if type(line) is not int or line < 1 or type(column) is not int or column < 1:
                    raise ValueError("Invalid text reference line or column")
                text = documents["lines"][line - 1]
                delimiter = locator.get("delimiter")
                if delimiter is not None and (
                    not isinstance(delimiter, str) or len(delimiter) != 1
                ):
                    raise ValueError("Invalid text reference delimiter")
                value = text.split(delimiter)[column - 1]
                if len(references) < 60:
                    references.append({"line": line, "column": column, "text": text[:2000]})
            else:
                raise ValueError("Unsupported structured source reference format")
        except (KeyError, IndexError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Numeric source reference does not resolve") from exc
        if isinstance(value, str):
            decimal = locator.get("decimal_separator", ".")
            if decimal not in {".", ","}:
                raise ValueError("Invalid numeric reference decimal separator")
            value = value.strip()
            value = None if value == "" else float(value.replace(decimal, "."))
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("Non-numeric source reference")
        factor = locator.get("factor", 1)
        if type(factor) not in (int, float) or not math.isfinite(factor) or factor == 0:
            raise ValueError("Invalid source reference conversion factor")
        if value is not None and factor != 1:
            value = float(Decimal(str(value)) * Decimal(str(factor)))
            if not math.isfinite(value):
                raise ValueError("Non-finite converted source value")
        actual = row.get("value")
        rounded_conversion = (
            factor != 1
            and value is not None
            and type(actual) in (int, float)
            and math.isfinite(actual)
            and abs(value - actual) <= 4 * max(math.ulp(value), math.ulp(actual))
        )
        if value != actual and not rounded_conversion:
            raise ValueError("Extracted value differs from original source reference")
        verified += 1
    return {
        "value_verified": verified,
        "unverified": unverified,
        **({"references": references} if references else {}),
        "qualification": "Direct numeric values checked against original bytes; definitions, units and entity selection still require meaning review.",
    }
