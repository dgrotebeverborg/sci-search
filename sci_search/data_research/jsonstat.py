"""Annual JSON-stat 2 reader for PxWeb responses. Pure; also runs in the sandbox."""

import csv
import hashlib
import io
import itertools
import json
import math
import re


def _order(category):
    index = category.get("index")
    if isinstance(index, dict):
        return sorted(index, key=index.get)
    if isinstance(index, list):
        return list(index)
    return list(category.get("label", {}))


def _frequency(code):
    match = re.search(r"[MQHSWD]", code.strip().upper())
    names = {"M": "monthly", "Q": "quarterly", "H": "half-yearly", "S": "half-yearly"}
    names.update({"W": "weekly", "D": "daily"})
    return names[match.group()] if match else "not annual"


def prepare_jsonstat(body, selection):
    if len(body) > 5_000_000:
        raise ValueError("JSON-stat response exceeds the 5 MB analysis limit")
    data = json.loads(body.decode("utf-8-sig"))
    if data.get("class") != "dataset":
        raise ValueError("Response is not a JSON-stat dataset")
    ids, sizes, dims = data["id"], data["size"], data["dimension"]
    if len(ids) != len(sizes) or set(ids) != set(dims):
        raise ValueError("Inconsistent JSON-stat dimensions")
    time = (data.get("role") or {}).get("time") or []
    if len(time) != 1:
        raise ValueError("JSON-stat dataset needs exactly one time dimension")
    time_id = time[0]
    order = {d: _order(dims[d]["category"]) for d in ids}
    if [len(order[d]) for d in ids] != sizes:
        raise ValueError("JSON-stat category counts do not match sizes")
    years = []
    for code in order[time_id]:
        if not re.fullmatch(r"(?:18|19|20|21)\d{2}", code.strip()):
            raise ValueError(f"dataset is {_frequency(code)}; no aggregation was performed")
        years.append(code.strip())
    others = [d for d in ids if d != time_id]
    series = selection.get("series_dimensions") or []
    if not set(series) <= set(others):
        raise ValueError("Series dimensions must be JSON-stat dimensions")
    for d in others:
        if d not in series and len(order[d]) != 1:
            raise ValueError(f"Dimension {d} is not a series dimension and needs exactly one code")
    metric = ((data.get("role") or {}).get("metric") or [None])[0]
    units = dims[metric]["category"].get("unit", {}) if metric else {}
    values = data["value"]
    if isinstance(values, list):
        if len(values) != math.prod(sizes):
            raise ValueError("JSON-stat value count does not match its dimensions")
        values = dict(enumerate(values))
    else:
        values = {int(k): v for k, v in values.items()}
    status = data.get("status") or {}
    if isinstance(status, list):
        status = dict(enumerate(status))
    elif isinstance(status, str):
        status = {i: status for i in values}
    else:
        status = {int(k): v for k, v in status.items()}
    labels = {d: dims[d]["category"].get("label", {}) for d in others}
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Year", "Series", *others, "Value", "Unit", "Status"])
    provenance, numeric, line = {}, 0, 2
    strides = []
    stride = 1
    for size in reversed(sizes):
        strides.insert(0, stride)
        stride *= size
    for combination in itertools.product(*[range(len(order[d])) for d in others]):
        codes = {d: order[d][i] for d, i in zip(others, combination, strict=True)}
        unit_code = codes.get(metric) if metric else None
        unit = (units.get(unit_code) or {}).get("base", "") if unit_code else ""
        if not unit:
            raise ValueError("JSON-stat measure has no documented unit")
        entity = (
            " | ".join(
                d + "=" + codes[d] + (f" ({labels[d][codes[d]]})" if codes[d] in labels[d] else "")
                for d in series
            )
            or "value"
        )
        for t, year in enumerate(years):
            position = {**dict(zip(others, combination, strict=True)), time_id: t}
            flat = sum(position[d] * strides[i] for i, d in enumerate(ids))
            value = values.get(flat)
            text = (
                ":"
                if value is None
                else repr(float(value))
                if isinstance(value, float)
                else str(value)
            )
            if value is not None:
                numeric += 1
            flag = str(status.get(flat, "") or "")
            writer.writerow([year, entity, *[codes[d] for d in others], text, unit, flag])
            provenance[str(line)] = {
                "source_reference": f"index:{flat}; period:{year}",
                "unit": unit,
                "status": flag,
                "source_value": "" if value is None else str(value),
                "dimensions": codes,
            }
            line += 1
    table = output.getvalue().encode()
    return table, dict(
        format="jsonstat2_v1",
        selection={"reader": "jsonstat2", **{k: v for k, v in selection.items() if k != "reader"}},
        row_provenance=provenance,
        normalized_sha256=hashlib.sha256(table).hexdigest(),
        checks={"output_rows": line - 2, "numeric_observations": numeric},
        metadata=json.dumps(
            {
                "dimension_labels": {d: dims[d].get("label", d) for d in ids},
                "code_labels": labels,
                "units": units,
            },
            ensure_ascii=False,
        ),
        limitations=[
            "Values were requested from the statistical API for the selected codes only; no aggregation was performed.",
            "Original status codes are retained; ':' means not published.",
        ],
    )
