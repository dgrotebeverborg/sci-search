# sci_search/data_research/connectors/eurostat.py
"""Eurostat SDMX 2.1 connector: dataset list, structure, series keys and key-filtered TSV."""

import re
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

from sci_search.data_research.connectors import base
from sci_search.data_research.retrieval import fetch_scoped

NAME = "eurostat"
PUBLISHER = "Eurostat"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
HOSTS = {"ec.europa.eu"}
API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
NS = {
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_ISO = (
    "AUT AT BEL BE BGR BG HRV HR CYP CY CZE CZ DNK DK EST EE FIN FI FRA FR DEU DE GRC EL HUN HU "
    "IRL IE ITA IT LVA LV LTU LT LUX LU MLT MT NLD NL POL PL PRT PT ROU RO SVK SK SVN SI ESP ES "
    "SWE SE ALB AL AND AD BLR BY BIH BA GBR UK ISL IS LIE LI MCO MC MDA MD MNE ME MKD MK NOR NO "
    "RUS RU SMR SM SRB RS CHE CH TUR TR UKR UA ARM AM AZE AZ GEO GE XKX XK"
).split()
ISO3_TO_GEO = dict(zip(_ISO[0::2], _ISO[1::2], strict=True))


def _name(node):
    names = node.findall("c:Name", NS)
    for name in names:
        if name.get(XML_LANG) == "en":
            return name.text or ""
    return names[0].text if names else ""


def dataset_from_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        return None
    match = re.match(
        r"^/eurostat/(?:databrowser/view|web/products-datasets/-)/([A-Za-z0-9_]+)(?:/|$)",
        parts.path,
    )
    if not match:
        return None
    return re.sub(r"__custom_\d+$", "", match[1], flags=re.I).lower()


def search(terms, scope, *, fetch, cache_dir):
    body, digest = base.catalogue(
        NAME, API + "/dataflow/ESTAT/all?detail=allstubs", fetch, cache_dir
    )
    root = ElementTree.fromstring(body)
    found = []
    for flow in root.iter("{%s}Dataflow" % NS["s"]):
        title = _name(flow)
        points = base.score(title, terms)
        if points:
            found.append((points, flow.get("id", "").lower(), title))
    found.sort(key=lambda item: -item[0])
    candidates = [
        base.DatasetCandidate(
            NAME,
            dataset,
            title,
            "unknown",
            landing_url=f"https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table",
        )
        for _, dataset, title in found[:10]
    ]
    return candidates, digest


def _structure(dataset, fetch):
    body, _, _ = fetch(
        f"{API}/dataflow/ESTAT/{dataset}?references=descendants&detail=referencepartial"
    )
    root = ElementTree.fromstring(body)
    codelists = {
        cl.get("id"): {code.get("id"): _name(code) for code in cl.findall("s:Code", NS)}
        for cl in root.iter("{%s}Codelist" % NS["s"])
    }
    dimensions = []
    for dim in root.iter("{%s}Dimension" % NS["s"]):
        enumeration = dim.find("s:LocalRepresentation/s:Enumeration", NS)
        refs = (
            [r for r in enumeration if r.tag.rpartition("}")[2] == "Ref"]
            if enumeration is not None
            else []
        )
        codelist = refs[0].get("id") if refs else dim.get("id", "").upper()
        dimensions.append(
            (int(dim.get("position", "0")), dim.get("id"), codelists.get(codelist, {}))
        )
    dimensions.sort()
    flow = next(root.iter("{%s}Dataflow" % NS["s"]), None)
    return [(d, codes) for _, d, codes in dimensions], _name(flow) if flow is not None else dataset


def _key(order, filters):
    return ".".join("+".join(filters.get(d, [])) for d in order)


def _series_keys(dataset, order, filters, scope, fetch):
    query = {"format": "TSV", "detail": "serieskeysonly"}
    if scope.get("start_year"):
        query["startPeriod"] = str(scope["start_year"])
    try:
        body, _, _ = fetch(f"{API}/data/{dataset}/{_key(order, filters)}/?{urlencode(query)}")
    except ValueError:
        return {}  # Eurostat answers 404 when the key matches no series
    lines = body.decode("utf-8-sig").splitlines()
    header = lines[0].split(",") if lines else []
    observed = {d: set() for d in header}
    for line in lines[1:]:
        for d, code in zip(header, line.split(","), strict=False):
            observed[d].add(code.strip())
    return observed if len(lines) > 1 else {}


def describe(candidate, scope, *, fetch):
    order, title = _structure(candidate.dataset, fetch)
    keys = [d for d, _ in order]
    observed = _series_keys(candidate.dataset, keys, {"freq": ["A"]}, scope, fetch)
    if not observed:
        # Name what the dataset does publish, so the rejection states the frequency.
        labels = dict(order).get("freq", {})
        found = _series_keys(candidate.dataset, keys, {}, scope, fetch).get("freq", set())
        named = ", ".join(sorted(labels.get(c, c) for c in found)) or "not annual"
        raise base.DatasetRejected(f"dataset is {named}; no aggregation was performed")
    wanted_geo = {ISO3_TO_GEO[c] for c in scope.get("countries") or [] if c in ISO3_TO_GEO}
    if wanted_geo and not observed.get("geo", set()) & wanted_geo:
        raise base.DatasetRejected(
            "none of the requested countries has published series: " + ", ".join(sorted(wanted_geo))
        )
    dimensions = []
    for d, codes in order:
        present = observed.get(d, set())
        if d == "geo" and wanted_geo:
            present = present & wanted_geo
        dimensions.append(base.Dimension(d, d, {c: codes.get(c, c) for c in sorted(present)}))
    definitions = (
        title
        + "\n"
        + "\n".join(
            f"{d.id}: " + "; ".join(f"{c}={label}" for c, label in d.codes.items())
            for d in dimensions
        )
    )
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dimensions),
        years=(),
        licence_url=LICENCE_URL,
        definitions=definitions[:30000],
        publisher=PUBLISHER,
        extra={"order": [d for d, _ in order]},
    )


def fetch(description, selection, scope, *, fetch, post):
    from sci_search.data_research.statistical_tables import inspect_statistics

    selection = base.validate_selection(description, selection)
    order = description.extra["order"]
    filters = selection["filters"]
    query = {"format": "TSV", "compressed": "true"}
    if scope.get("start_year"):
        query["startPeriod"] = str(scope["start_year"])
    if scope.get("end_year"):
        query["endPeriod"] = str(scope["end_year"])
    url = f"{API}/data/{description.candidate.dataset}/{_key(order, filters)}/?{urlencode(query)}"
    raw, _, final = fetch_scoped(url, scope, fetch, [])
    preview = inspect_statistics(raw)
    notes = []
    kept = {}
    for d in order:
        present = [c for c in filters[d] if c in preview["dimension_values"].get(d, [])]
        missing = [c for c in filters[d] if c not in present]
        if not present:
            raise base.SelectionError(
                f"No published series for the selected {d} codes",
                {"published_codes": preview["dimension_values"]},
            )
        if missing:
            if d not in selection["series_dimensions"]:
                raise base.SelectionError(
                    f"Fixed code for {d} has no published series",
                    {"published_codes": preview["dimension_values"]},
                )
            notes.append(f"No data published for {d}: " + ", ".join(missing))
        kept[d] = present
    labels = {d.id: d.codes for d in description.dimensions}
    return base.Fetched(
        raw=raw,
        request={"method": "GET", "url": final},
        selection={
            "reader": "statistical_tsv",
            "filters": [{"dimension": d, "values": kept[d]} for d in order],
            "series_dimensions": selection["series_dimensions"],
            "code_labels": labels,
            "reason": selection["reason"],
        },
        artifact="source.tsv.gz",
        notes=tuple(notes),
    )


def mapping(table, preparation, selection, measurement):
    return base.series_mapping(table, measurement)
