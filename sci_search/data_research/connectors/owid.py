# sci_search/data_research/connectors/owid.py
"""Our World in Data connector: chart search, grapher CSV and metadata."""

import csv
import hashlib
import io
import json
import re
from urllib.parse import urlencode, urlsplit

from sci_search.data_research.connectors import base

NAME = "owid"
PUBLISHER = "Our World in Data"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
HOSTS = {"ourworldindata.org"}
GRAPHER = "https://ourworldindata.org/grapher/"
SLUG = re.compile(r"[a-z0-9-]+")
COUNTRY_CODE = re.compile(r"[A-Z]{3}")  # aggregates have empty or OWID_ codes
MAX_BYTES = 5_000_000


def dataset_from_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        return None
    match = re.fullmatch(r"/grapher/([a-z0-9-]+)", parts.path)
    return match[1] if match else None


def _checked(dataset):
    if not SLUG.fullmatch(dataset):
        raise base.DatasetRejected("not an Our World in Data chart slug")
    return dataset


def _csv_url(slug):
    return f"{GRAPHER}{slug}.csv?v=1&csvType=full&useColumnShortNames=true"


def _capped(body):
    if len(body) > MAX_BYTES:
        raise base.DatasetRejected("OWID response exceeds the 5 MB analysis limit")


def search(terms, scope, *, fetch, cache_dir):
    found = {}
    for term in terms[:4]:
        body, _, _ = fetch("https://ourworldindata.org/api/search?" + urlencode({"q": term}))
        for result in json.loads(body).get("results", []):
            slug = result.get("slug", "")
            if result.get("type") == "chart" and SLUG.fullmatch(slug):
                found.setdefault(slug, result.get("title", slug))
    ranked = sorted(found.items(), key=lambda item: -base.score(item[1], terms))
    candidates = [
        base.DatasetCandidate(NAME, slug, title, "annual", landing_url=GRAPHER + slug)
        for slug, title in ranked[:10]
    ]
    return candidates, ""


def _frequency(year):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", year):
        return "daily"
    if re.fullmatch(r"\d{4}-\d{2}", year):
        return "monthly"
    return "not annual"


def describe(candidate, scope, *, fetch):
    slug = _checked(candidate.dataset)
    csv_body, _, _ = fetch(_csv_url(slug))
    _capped(csv_body)
    meta_body, _, _ = fetch(f"{GRAPHER}{slug}.metadata.json?v=1")
    _capped(meta_body)
    metadata = json.loads(meta_body)
    columns = {
        v["shortName"]: v
        for v in metadata.get("columns", {}).values()
        if isinstance(v, dict) and v.get("shortName")
    }
    csv_text = csv_body.decode("utf-8")  # the BOM stays, so the stored text hashes to csv_sha256
    reader = csv.DictReader(io.StringIO(csv_text.removeprefix("\ufeff")))
    fields = reader.fieldnames or []
    if not {"entity", "year"} <= set(fields):
        raise base.DatasetRejected("OWID CSV lacks entity or year columns")
    rows = list(reader)
    for row in rows:
        if not re.fullmatch(r"-?\d{1,4}", row["year"]):
            raise base.DatasetRejected(
                f"dataset is {_frequency(row['year'])}; no aggregation was performed"
            )
    start, end = scope.get("start_year"), scope.get("end_year")
    in_period = [
        r
        for r in rows
        if (start is None or int(r["year"]) >= start) and (end is None or int(r["year"]) <= end)
    ]
    if not in_period:
        raise base.DatasetRejected(
            "dataset has no annual series in the requested period; no aggregation was performed"
        )
    codes = {r["entity"]: r.get("code", "") for r in in_period}
    wanted = list(scope.get("countries") or [])
    present = {c for c in codes.values() if COUNTRY_CODE.fullmatch(c)}
    missing = [c for c in wanted if c not in present]
    if wanted and len(missing) == len(wanted):
        raise base.DatasetRejected(
            "none of the requested countries has published series: " + ", ".join(missing)
        )
    entities = {e: e for e, code in codes.items() if not wanted or code in wanted}
    indicators = {}
    for short in (f for f in fields if f not in {"entity", "code", "year"}):
        info = columns.get(short, {})
        if info.get("unit") or info.get("shortUnit"):
            unit = info.get("unit") or info.get("shortUnit")
            indicators[short] = f"{info.get('titleShort', short)} ({unit})"
    if not indicators:
        raise base.DatasetRejected("OWID chart has no indicator with a documented unit")
    envelope = json.dumps(
        {"csv": csv_text, "metadata": meta_body.decode("utf-8")}, ensure_ascii=False
    ).encode()
    if len(envelope) > MAX_BYTES:
        raise base.DatasetRejected("OWID chart exceeds the 5 MB analysis limit")
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=(
            base.Dimension("indicator", "Indicator", indicators),
            base.Dimension("entity", "Entity", entities),
        ),
        years=tuple(sorted({int(r["year"]) for r in in_period})),
        licence_url=LICENCE_URL,
        definitions=json.dumps(columns, ensure_ascii=False)[:30000],
        publisher=PUBLISHER,
        payload=envelope,
        extra={
            "csv_sha256": hashlib.sha256(csv_body).hexdigest(),
            "metadata_sha256": hashlib.sha256(meta_body).hexdigest(),
            "missing_countries": missing,
        },
    )


def fetch(description, selection, scope, *, fetch, post):
    slug = _checked(description.candidate.dataset)
    selection = base.validate_selection(description, selection)
    filters = selection["filters"]
    if len(filters["indicator"]) != 1 or "indicator" in selection["series_dimensions"]:
        raise base.SelectionError("Select exactly one indicator and do not use it as a series")
    notes = []
    if description.extra.get("missing_countries"):
        notes.append(
            "No data published for countries: " + ", ".join(description.extra["missing_countries"])
        )
    return base.Fetched(
        raw=description.payload,
        request={
            "method": "GET",
            "url": _csv_url(slug),
            "csv_sha256": description.extra["csv_sha256"],
            "metadata_sha256": description.extra["metadata_sha256"],
        },
        selection={
            "reader": "owid_csv",
            "indicator": filters["indicator"][0],
            "entities": filters["entity"],
            "reason": selection["reason"],
        },
        artifact="source.json",
        notes=tuple(notes),
    )


def mapping(table, preparation, selection, measurement):
    return base.series_mapping(table, measurement)
