"""PxWeb connector for a reviewed list of installations (API v1 and v2), via JSON-stat 2."""

import json
import re
from urllib.parse import quote, urlencode

from sci_search.data_research.connectors import base

NAME = "pxweb"
# "table" is the id pattern for that installation's tables; "country" the one country it covers.
# Ids keep the source's casing: PxWeb servers may be case-sensitive.
INSTALLATIONS = {
    "scb": {
        "host": "statistikdatabasen.scb.se",
        "version": 2,
        "base": "https://statistikdatabasen.scb.se/api/v2",
        "publisher": "Statistics Sweden",
        "licence": "https://creativecommons.org/licenses/by/4.0/",
        "table": re.compile(r"TAB\d+"),
        "country": "SWE",
    },
    "ssb": {
        "host": "data.ssb.no",
        "version": 1,
        "base": "https://data.ssb.no/api/v0/en/table",
        "publisher": "Statistics Norway",
        "licence": "https://data.norge.no/nlod/en/2.0",
        "table_from_title": True,
        "table": re.compile(r"\d{5}"),
        "country": "NOR",
    },
}
HOSTS = {i["host"] for i in INSTALLATIONS.values()}
PUBLISHER = "PxWeb statistical office"
LICENCE_URL = ""
FREQUENCY_NAMES = {"M": "monthly", "Q": "quarterly", "H": "half-yearly", "S": "half-yearly"}
FREQUENCY_NAMES.update({"W": "weekly", "D": "daily"})


def _frequency(code):
    """Frequency name of a period code such as 2014H2 or 2020M05; "annual" for a bare year."""
    if base.annual(code):
        return "annual"
    match = re.search(r"[MQHSWD]", code.strip().upper())
    return FREQUENCY_NAMES[match.group()] if match else "not annual"


def dataset_from_url(url):
    match = re.match(r"^https://statistikdatabasen\.scb\.se/api/v2/tables/(TAB\d+)(?:[/?]|$)", url)
    if match:
        return "scb:" + match[1]
    match = re.match(r"^https://data\.ssb\.no/api/v0/en/table/(\d{5})(?:[/?]|$)", url)
    return "ssb:" + match[1] if match else None


def _split(dataset):
    installation, _, table = dataset.partition(":")
    inst = INSTALLATIONS.get(installation)
    if not inst or not inst["table"].fullmatch(table):
        raise base.DatasetRejected("not a PxWeb table identifier")
    return inst, installation, table


def _covers(inst, countries):
    return not countries or inst["country"] in countries


def search(terms, scope, *, fetch, cache_dir):
    countries = list(scope.get("countries") or [])
    candidates = []
    for name, inst in INSTALLATIONS.items():
        if not _covers(inst, countries):
            continue
        for term in terms[:4]:
            if inst["version"] == 2:
                query = urlencode({"query": term, "lang": "en", "pageSize": 10})
                body, _, _ = fetch(f"{inst['base']}/tables?{query}")
                for t in json.loads(body).get("tables", []):
                    if not inst["table"].fullmatch(t.get("id", "")):
                        continue
                    first = t.get("firstPeriod", "")
                    frequency = _frequency(first) if first else "unknown"
                    candidates.append(
                        base.DatasetCandidate(
                            NAME,
                            f"{name}:{t['id']}",
                            t.get("label", ""),
                            frequency,
                            first,
                            t.get("lastPeriod", ""),
                            f"{inst['base']}/tables/{t['id']}",
                        )
                    )
            else:
                body, _, _ = fetch(f"{inst['base']}/?{urlencode({'query': term})}")
                for t in json.loads(body)[:10]:
                    if inst.get("table_from_title"):
                        number = re.match(r"^(\d+):", t.get("title", ""))
                        path = number[1] if number else ""
                    else:
                        path = (t.get("path", "").rstrip("/") + "/" + t.get("id", "")).lstrip("/")
                    if not inst["table"].fullmatch(path):
                        continue
                    candidates.append(
                        base.DatasetCandidate(
                            NAME,
                            f"{name}:{path}",
                            t["title"],
                            "unknown",
                            landing_url=f"{inst['base']}/{path}",
                        )
                    )
    unique = {c.dataset: c for c in candidates}
    ranked = sorted(unique.values(), key=lambda c: -base.score(c.title, terms))
    # Keep a few per installation so one large catalogue cannot crowd the others out.
    kept = []
    for name in INSTALLATIONS:
        kept += [c for c in ranked if c.dataset.startswith(name + ":")][:5]
    return sorted(kept, key=lambda c: -base.score(c.title, terms)), ""


def describe(candidate, scope, *, fetch, require_annual=True):
    inst, _, table = _split(candidate.dataset)
    countries = list(scope.get("countries") or [])
    if not _covers(inst, countries):
        raise base.DatasetRejected(
            f"{inst['publisher']} covers only {inst['country']}; requested: " + ", ".join(countries)
        )
    if inst["version"] == 2:
        body, _, _ = fetch(
            f"{inst['base']}/tables/{table}/metadata?lang=en&outputFormat=json-stat2"
        )
        meta = json.loads(body)
        time = ((meta.get("role") or {}).get("time") or [None])[0]
        dims, time_codes = [], []
        for d in meta["id"]:
            category = meta["dimension"][d]["category"]
            index = category.get("index", {})
            codes = sorted(index, key=index.get) if isinstance(index, dict) else list(index)
            if d == time:
                time_codes = codes
                continue
            labels = category.get("label", {})
            dims.append(
                base.Dimension(
                    d, meta["dimension"][d].get("label", d), {c: labels.get(c, c) for c in codes}
                )
            )
        definitions = json.dumps(
            {
                "label": meta.get("label"),
                "note": meta.get("note"),
                "units": {d: meta["dimension"][d]["category"].get("unit") for d in meta["id"]},
            },
            ensure_ascii=False,
        )
    else:
        body, _, _ = fetch(f"{inst['base']}/{table}")
        meta = json.loads(body)
        dims, time_codes, time = [], [], None
        for v in meta["variables"]:
            if v.get("time"):
                time, time_codes = v["code"], list(v["values"])
                continue
            texts = v.get("valueTexts") or v["values"]
            dims.append(
                base.Dimension(v["code"], v["text"], dict(zip(v["values"], texts, strict=True)))
            )
        definitions = json.dumps({"title": meta.get("title")}, ensure_ascii=False)
    if not time or not time_codes:
        raise base.DatasetRejected("dataset has no time dimension")
    annual = [c for c in time_codes if base.annual(c)]
    if require_annual and len(annual) != len(time_codes):
        named = _frequency(next(c for c in time_codes if not base.annual(c)))
        raise base.DatasetRejected(f"dataset is {named}; no aggregation was performed")
    start, end = scope.get("start_year"), scope.get("end_year")
    years = tuple(
        sorted(
            y
            for y in (base.annual(c) for c in annual)
            if y and (not start or y >= start) and (not end or y <= end)
        )
    )
    if annual and not years:
        raise base.DatasetRejected(
            "dataset has no annual series in the requested period; no aggregation was performed"
        )
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dims),
        years=years,
        licence_url=inst["licence"],
        definitions=definitions[:30000],
        publisher=inst["publisher"],
        extra={
            "time": time,
            "time_codes": time_codes,
            "other_countries": [c for c in countries if c != inst["country"]],
        },
    )


def _periods(description, scope):
    """Time codes to request: the annual ones inside the scope, or all if the table is not annual."""
    codes = description.extra["time_codes"]
    if not all(base.annual(c) for c in codes):
        return codes  # only reachable with require_annual=False; the reader rejects it
    start, end = scope.get("start_year"), scope.get("end_year")
    chosen = [
        c
        for c in codes
        if (not start or base.annual(c) >= start) and (not end or base.annual(c) <= end)
    ]
    if not chosen:
        raise base.DatasetRejected(
            "dataset has no annual series in the requested period; no aggregation was performed"
        )
    return chosen


def fetch(description, selection, scope, *, fetch, post):
    inst, _, table = _split(description.candidate.dataset)
    checked = base.validate_selection(description, selection)
    filters = {**checked["filters"], description.extra["time"]: _periods(description, scope)}
    reader = {
        "reader": "jsonstat2",
        "series_dimensions": checked["series_dimensions"],
        "code_labels": {d.id: d.codes for d in description.dimensions},
        "reason": checked["reason"],
    }
    if inst["version"] == 2:
        params = {"lang": "en", "outputFormat": "json-stat2"}
        params.update({f"valueCodes[{d}]": ",".join(codes) for d, codes in filters.items()})
        raw, _, final = fetch(f"{inst['base']}/tables/{table}/data?{urlencode(params)}")
        request = {"method": "GET", "url": final}
    else:
        payload = {
            "query": [
                {"code": d, "selection": {"filter": "item", "values": codes}}
                for d, codes in filters.items()
            ],
            "response": {"format": "json-stat2"},
        }
        raw, _, final = post(f"{inst['base']}/{quote(table)}", payload)
        request = {"method": "POST", "url": final, "body": payload}
    notes = ()
    if description.extra.get("other_countries"):
        notes = (
            f"{inst['publisher']} covers only {inst['country']}; no data for: "
            + ", ".join(description.extra["other_countries"]),
        )
    return base.Fetched(
        raw=raw, request=request, selection=reader, artifact="source.json", notes=notes
    )


def mapping(table, preparation, selection, measurement):
    return base.series_mapping(table, measurement)
