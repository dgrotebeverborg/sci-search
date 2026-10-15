# sci_search/data_research/connectors/eurostat.py
"""Eurostat SDMX 2.1 connector: dataset list, structure, series keys and key-filtered TSV."""

import re
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

from sci_search.data_research.connectors import base
from sci_search.data_research.retrieval import fetch_scoped

NAME = "eurostat"
# Search-term languages: the catalogue titles are English.
LANGUAGES = ("en",)
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


def _name(node, tag="c:Name"):
    names = node.findall(tag, NS)
    for name in names:
        if name.get(XML_LANG) == "en":
            return name.text or ""
    return (names[0].text or "") if names else ""


def _xml(body, message, error):
    """Parse an SDMX body; an HTML error page or truncated body raises error with message."""
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise error(f"{message} ({exc})") from exc


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
    root = _xml(body, "Eurostat catalogue is not XML", ValueError)
    found = []
    for flow in root.iter("{%s}Dataflow" % NS["s"]):
        if not DATASET.fullmatch(flow.get("id", "").lower()):
            continue
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
    """Dimensions in key order as (id, concept name, codelist description, codes), and the title."""
    _checked(dataset)
    body, _, _ = fetch(
        f"{API}/dataflow/ESTAT/{dataset}?references=descendants&detail=referencepartial"
    )
    root = _xml(body, f"Eurostat structure for {dataset} is not XML", base.DatasetRejected)
    codelists = {
        cl.get("id"): (
            _name(cl, "c:Description"),
            {code.get("id"): _name(code) for code in cl.findall("s:Code", NS)},
        )
        for cl in root.iter("{%s}Codelist" % NS["s"])
    }
    concepts = {c.get("id"): _name(c) for c in root.iter("{%s}Concept" % NS["s"])}
    dimensions = []
    for dim in root.iter("{%s}Dimension" % NS["s"]):
        enumeration = dim.find("s:LocalRepresentation/s:Enumeration", NS)
        refs = (
            [r for r in enumeration if r.tag.rpartition("}")[2] == "Ref"]
            if enumeration is not None
            else []
        )
        codelist = refs[0].get("id") if refs else dim.get("id", "").upper()
        identity = dim.find("s:ConceptIdentity", NS)
        d = dim.get("id")
        concept = next(iter(identity), None) if identity is not None else None
        label = concepts.get(concept.get("id") if concept is not None else d) or d
        about, codes = codelists.get(codelist, ("", {}))
        dimensions.append((int(dim.get("position", "0")), d, label, about, codes))
    dimensions.sort()
    flow = next(root.iter("{%s}Dataflow" % NS["s"]), None)
    return [item[1:] for item in dimensions], _name(flow) if flow is not None else dataset


DATASET = re.compile(r"[a-z0-9_]+")
FREQUENCIES = {
    "D": "daily",
    "W": "weekly",
    "M": "monthly",
    "Q": "quarterly",
    "S": "half-yearly",
    "A": "annual",
}


def _checked(dataset):
    if not DATASET.fullmatch(dataset):
        raise base.DatasetRejected("not a Eurostat dataset code")
    return dataset


def _key(order, filters):
    return ".".join("+".join(filters.get(d, [])) for d in order)


def _series_rows(dataset, order, filters, scope, fetch):
    """Published series keys matching filters, one {dimension: code} per series."""
    query = {"format": "TSV", "detail": "serieskeysonly"}
    if scope.get("start_year"):
        query["startPeriod"] = str(scope["start_year"])
    try:
        body, _, _ = fetch(f"{API}/data/{dataset}/{_key(order, filters)}/?{urlencode(query)}")
    except ValueError as exc:
        if "HTTP 404" in str(exc):  # Eurostat answers 404 when the key matches no series
            return []
        raise
    lines = body.decode("utf-8-sig").splitlines()
    header = lines[0].split(",") if lines else []
    return [
        {d: code.strip() for d, code in zip(header, line.split(","), strict=False)}
        for line in lines[1:]
    ]


def _series_keys(dataset, order, filters, scope, fetch):
    observed = {}
    for row in _series_rows(dataset, order, filters, scope, fetch):
        for d, code in row.items():
            observed.setdefault(d, set()).add(code)
    return observed


def describe(candidate, scope, *, fetch):
    order, title = _structure(candidate.dataset, fetch)
    keys = [d for d, *_ in order]
    observed = _series_keys(candidate.dataset, keys, {"freq": ["A"]}, scope, fetch)
    if not observed:
        # Name what the dataset does publish, so the rejection states the frequency.
        labels = next((codes for d, *_, codes in order if d == "freq"), {})
        found = _series_keys(candidate.dataset, keys, {}, scope, fetch).get("freq", set())
        if "A" in found or not found:
            raise base.DatasetRejected(
                "dataset has no annual series in the requested period; no aggregation was performed"
            )
        named = ", ".join(sorted(FREQUENCIES.get(c) or labels.get(c, c) for c in found))
        raise base.DatasetRejected(f"dataset is {named}; no aggregation was performed")
    countries = list(scope.get("countries") or [])
    unmapped = [c for c in countries if c not in ISO3_TO_GEO]
    if countries and len(unmapped) == len(countries):
        raise base.DatasetRejected(
            "no Eurostat geo code for the requested countries: " + ", ".join(unmapped)
        )
    wanted_geo = {ISO3_TO_GEO[c] for c in countries if c in ISO3_TO_GEO}
    missing_geo = sorted(wanted_geo - observed.get("geo", set()))
    if wanted_geo and len(missing_geo) == len(wanted_geo):
        raise base.DatasetRejected(
            "none of the requested countries has published series: " + ", ".join(missing_geo)
        )
    dimensions, lines = [], [title]
    for d, label, about, codes in order:
        present = observed.get(d, set())
        if d == "geo" and wanted_geo:
            present = present & wanted_geo
        dimension = base.Dimension(d, label, {c: codes.get(c, c) for c in sorted(present)})
        dimensions.append(dimension)
        if about:
            lines.append(f"{label} ({d}): {about}")
        lines += [f"{label}: {c} = {name}" for c, name in dimension.codes.items()]
    definitions = "\n".join(lines)
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dimensions),
        years=(),
        licence_url=LICENCE_URL,
        definitions=definitions[:30000],
        publisher=PUBLISHER,
        extra={"order": [d for d, *_ in order], "missing_geo": missing_geo, "unmapped": unmapped},
    )


def documentation(description, *, fetch):
    """Bounded retrieval of official dataset reference metadata, on demand."""
    from urllib.parse import urldefrag

    from sci_search.data_research.retrieval import inspect_page

    dataset = _checked(description.candidate.dataset)
    for suffix in ("esmsip2", "esms"):
        url = f"https://ec.europa.eu/eurostat/cache/metadata/en/{dataset}_{suffix}.htm"
        try:
            body, _, final = fetch(url)
        except (OSError, ValueError):
            continue
        page = inspect_page(body, final)
        if page["text"]:
            documents = [{"url": final, "body": body, "text": page["text"]}]
            seen = {urldefrag(url)[0], urldefrag(final)[0]}
            # Indicator metadata often links to the underlying statistical methodology.
            # Follow only observed official metadata links, never model-supplied URLs.
            for link in page["links"]:
                target = urldefrag(link)[0]
                if target in seen or not re.fullmatch(
                    r"https://ec\.europa\.eu/eurostat/cache/metadata/(?:en|EN)/[a-z0-9_]+\.htm",
                    target,
                ):
                    continue
                seen.add(target)
                try:
                    related, _, resolved = fetch(target)
                    text = inspect_page(related, resolved)["text"]
                    if text:
                        documents.append({"url": resolved, "body": related, "text": text})
                except (OSError, ValueError):
                    pass
                if len(seen) >= 3:
                    break
            return documents
    return []


def fetch(description, selection, scope, *, fetch, post):
    from sci_search.data_research.statistical_tables import inspect_statistics

    _checked(description.candidate.dataset)
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
    try:
        preview = inspect_statistics(raw)
    except ValueError as exc:
        if "has no series" not in str(exc):
            raise
        # Each code is published, but not this combination: Eurostat answers with only a
        # header. List combinations that exist for the selected series codes.
        series = selection["series_dimensions"]
        rows = _series_rows(
            description.candidate.dataset,
            order,
            {d: filters[d] for d in series},
            scope,
            fetch,
        )
        published = []
        for row in rows:
            combination = {d: c for d, c in row.items() if d not in series}
            if combination not in published:
                published.append(combination)
        if not published:
            raise base.DatasetRejected(
                "Eurostat has no published series for the selected series codes"
            ) from exc
        raise base.SelectionError(
            "No published series for this combination of codes; choose a published combination",
            {"published_combinations": published[:30]},
        ) from exc
    notes = []
    if description.extra.get("missing_geo"):
        notes.append("No data published for geo: " + ", ".join(description.extra["missing_geo"]))
    if description.extra.get("unmapped"):
        notes.append("No Eurostat geo code for: " + ", ".join(description.extra["unmapped"]))
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
