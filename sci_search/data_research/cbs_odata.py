"""Bounded CBS OData snapshots, including the original response bytes for replay."""

import csv
import hashlib
import io
import json
import re
import zipfile
from urllib.parse import urlencode, urljoin, urlsplit


def pages(url, fetch, *, max_rows=50000):
    initial = urlsplit(url)
    seen, retained, rows, size = set(), [], [], 0
    while url:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != initial.netloc
            or parsed.path != initial.path
            or parsed.fragment
            or parsed.username
            or url in seen
            or len(seen) >= 20
        ):
            raise ValueError("Unsafe, repeated or excessive CBS pagination")
        seen.add(url)
        body, _, final_url = fetch(url)
        final = urlsplit(final_url)
        if (
            final.scheme != initial.scheme
            or final.netloc != initial.netloc
            or final.path != initial.path
        ):
            raise ValueError("CBS pagination redirected outside the dataset endpoint")
        size += len(body)
        if size > 5_000_000:
            raise ValueError("CBS API slice exceeds the 5 MB acquisition limit")
        value = json.loads(body)
        batch = value.get("value", [value])
        if not isinstance(batch, list) or not all(isinstance(r, dict) for r in batch):
            raise ValueError("Invalid CBS API response shape")
        rows.extend(batch)
        if len(rows) > max_rows:
            raise ValueError("CBS API response exceeds its row limit")
        retained.append(
            {
                "url": url,
                "body": body.decode("utf-8-sig"),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        link = value.get("@odata.nextLink")
        if link is not None and not isinstance(link, str):
            raise ValueError("Invalid CBS pagination link")
        url = urljoin(url, link) if link else None
    return rows, retained


def metadata(snapshot):
    documents = {}
    for endpoint, entries in snapshot["metadata"].items():
        rows = []
        for entry in entries:
            document = json.loads(entry["body"])
            rows.extend(document.get("value", [document]))
        documents[endpoint] = rows
    dims = documents["Dimensions"]
    if len(dims) > 20 or any(
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", d["Identifier"]) for d in dims
    ):
        raise ValueError("Invalid CBS dimension identifiers")
    return {
        "dataset": documents["Properties"],
        "measures": documents["MeasureCodes"],
        "dimensions": [{**d, "CodesUrl": d["Identifier"] + "Codes.csv"} for d in dims],
        "codes": {
            d["Identifier"]: {c["Identifier"]: c for c in documents[d["Identifier"] + "Codes"]}
            for d in dims
        },
    }


def describe_snapshot(root, fetch):
    snapshot = {"format": "cbs_odata_v1", "metadata": {}, "observations": []}
    for endpoint in ("Properties", "MeasureCodes", "Dimensions"):
        rows, raw = pages(root + "/" + endpoint, fetch, max_rows=1000)
        snapshot["metadata"][endpoint] = raw
        if endpoint == "Dimensions":
            if len(rows) > 20:
                raise ValueError("Too many CBS dimensions")
            for dimension in rows:
                identifier = dimension["Identifier"]
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", identifier):
                    raise ValueError("Invalid CBS dimension identifier")
                _, codes = pages(root + "/" + identifier + "Codes", fetch, max_rows=1000)
                snapshot["metadata"][identifier + "Codes"] = codes
    if len(json.dumps(snapshot).encode()) > 5_000_000:
        raise ValueError("CBS API metadata exceeds the 5 MB limit")
    return snapshot


def acquire(snapshot, root, selection, years, fetch):
    info = metadata(snapshot)
    time = next(d["Identifier"] for d in info["dimensions"] if d["Kind"] == "TimeDimension")
    filters = {**selection["filters"], time: [f"{year}JJ00" for year in years]}

    def literal(value):
        return "'" + value.replace("'", "''") + "'"

    expression = " and ".join(
        "(" + " or ".join(f"{key} eq {literal(code)}" for code in codes) + ")"
        for key, codes in filters.items()
    )
    url = root + "/Observations?" + urlencode({"$filter": expression})
    rows, retained = pages(url, fetch)
    if not rows:
        raise ValueError("CBS selection contains no observations")
    # Do not trust an API which ignores a supplied filter or pages into another selection.
    if any(any(row.get(key) not in codes for key, codes in filters.items()) for row in rows):
        raise ValueError("CBS response contains observations outside the requested selection")
    result = {**snapshot, "observations": retained}
    body = json.dumps(result, ensure_ascii=False).encode()
    if len(body) > 10_000_000:
        raise ValueError("CBS API snapshot exceeds the 10 MB limit")
    return body, {
        "method": "GET",
        "url": url,
        "snapshot": True,
        "pages": [{k: v for k, v in p.items() if k != "body"} for p in retained],
    }


def prepare_snapshot(body):
    snapshot = json.loads(body)
    if snapshot.get("format") != "cbs_odata_v1" or len(body) > 10_000_000:
        raise ValueError("Invalid CBS API snapshot")
    info = metadata(snapshot)
    observations, references = [], []
    for page_index, page in enumerate(snapshot["observations"]):
        rows = json.loads(page["body"])["value"]
        observations.extend(rows)
        references.extend(
            f"observations/{page_index}/body/value/{index}" for index in range(len(rows))
        )
    if not observations or len(observations) > 50000:
        raise ValueError("Invalid CBS observation count")
    tables = {
        "Properties.csv": info["dataset"],
        "Dimensions.csv": info["dimensions"],
        "MeasureCodes.csv": info["measures"],
        "Observations.csv": observations,
    }
    tables.update({key + "Codes.csv": list(value.values()) for key, value in info["codes"].items()})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, rows in tables.items():
            stream = io.StringIO(newline="")
            fields = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(
                {k: "" if v is None else str(v) for k, v in row.items()} for row in rows
            )
            archive.writestr(name, stream.getvalue())
    try:
        from .packages import prepare_table
    except ImportError:
        from packages import prepare_table
    table, preparation = prepare_table(output.getvalue())
    preparation["format"] = "cbs_odata_v1"
    for key, provenance in preparation["row_provenance"].items():
        provenance["source_reference"] = references[int(key) - 2]
        provenance["entry"] = "source.json"
    return table, preparation
