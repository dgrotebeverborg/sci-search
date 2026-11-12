"""CBS connector: catalogue search and CSV packages with their code tables."""

import json
import re
import zipfile
from urllib.parse import urlsplit

from sci_search.data_research import cbs_odata
from sci_search.data_research.connectors import base
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv

NAME = "cbs"
# Search-term languages: most CBS titles are Dutch; some tables have English editions.
LANGUAGES = ("nl", "en")
PUBLISHER = "CBS (Statistics Netherlands)"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
HOSTS = {"www.cbs.nl", "opendata.cbs.nl", "datasets.cbs.nl"}
CATALOGUE = (
    "https://opendata.cbs.nl/ODataCatalog/Tables?$format=json"
    "&$select=Identifier,Title,Frequency,Language,Period,ShortDescription"
)
# Catalogue Frequency values; Stopgezet (discontinued) and Eenmalig (one-off) say nothing about the
# period type, so they are "unknown" and the package reader decides. Other values are "other".
FREQUENCY = {
    "Perjaar": "annual",
    "Permaand": "monthly",
    "Perkwartaal": "quarterly",
    "Tweemaalperjaar": "half-yearly",
    "Stopgezet": "unknown",
    "Eenmalig": "unknown",
}
# datasets.cbs.nl is case-sensitive: ids keep the catalogue's casing. Older tables are lower case
# (80472ned) or have no suffix (03763).
DATASET = re.compile(r"\d{5}[A-Za-z]{0,3}")


def _checked(dataset):
    if not DATASET.fullmatch(dataset):
        raise base.DatasetRejected("not a CBS table identifier")
    return dataset


def package_url(dataset):
    return "https://datasets.cbs.nl/CSV/CBS/nl/" + _checked(dataset)


def dataset_from_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        return None
    match = re.search(
        r"/(?:cijfers/detail|figures/detail|ODataApi/OData|odata/v1/CBS|CSV/CBS/[a-z]{2})/(\d{5}[A-Za-z]{0,3})(?:/|$)",
        parts.path,
    )
    return match[1] if match else None


def search(terms, scope, *, fetch, cache_dir):
    body, digest = base.catalogue(NAME, CATALOGUE, fetch, cache_dir)
    found = []
    for table in json.loads(body)["value"]:
        identifier = table.get("Identifier", "")
        if not DATASET.fullmatch(identifier):
            continue
        title = (table.get("Title") or "").strip()
        points = base.score(title + " " + (table.get("ShortDescription") or ""), terms)
        if points:
            found.append((points, identifier, title, table.get("Frequency")))
    found.sort(key=lambda item: -item[0])
    candidates = [
        base.DatasetCandidate(
            NAME,
            identifier,
            title,
            FREQUENCY.get(frequency or "", "other" if frequency else "unknown"),
            landing_url="https://www.cbs.nl/nl-nl/cijfers/detail/" + identifier,
        )
        for _, identifier, title, frequency in found[:10]
    ]
    return candidates, digest


def _definitions(metadata):
    """The package's titles and descriptions as plain text the meaning review can quote."""
    dataset = metadata["dataset"][0] if metadata["dataset"] else {}
    lines = [
        f"{key}: {dataset[key].strip()}"
        for key in ("Title", "Summary", "Description", "LongDescription")
        if (dataset.get(key) or "").strip()
    ]
    described = set()
    for m in metadata["measures"]:
        lines.append(f"Measure: {m['Title']} ({m['Unit']})")
        about = (m.get("Description") or "").strip()
        if about and about not in described:  # CBS repeats a description for each unit
            described.add(about)
            lines.append(about)
    for d in metadata["dimensions"]:
        title = d.get("Title") or d["Identifier"]
        lines.append(f"Dimension: {title}")
        if (d.get("Description") or "").strip():
            lines.append(d["Description"].strip())
        for code in metadata["codes"].get(d["Identifier"], {}).values():
            if (code.get("Description") or "").strip():
                lines.append(f"{title}: {code['Title'].strip()}: {code['Description'].strip()}")
    return "\n".join(lines)


# CBS also publishes tables for the Caribbean Netherlands, which have no region dimension either.
CARIBBEAN = re.compile(r"Caribisch Nederland|Caribbean Netherlands|Bonaire|Sint Eustatius|\bSaba\b")


def _geography(metadata, definitions):
    """The Netherlands for a table without a region dimension, unless it is Caribbean."""
    regions = {"GeoDimension", "GeoDetailDimension"}
    if any(d["Kind"] in regions for d in metadata["dimensions"]) or CARIBBEAN.search(definitions):
        return None
    return "Netherlands (national table: it has no region dimension)"


def describe(candidate, scope, *, fetch):
    url = package_url(candidate.dataset)
    countries = list(scope.get("countries") or [])
    if countries and "NLD" not in countries:
        raise base.DatasetRejected(
            "CBS covers only the Netherlands; requested: " + ", ".join(countries)
        )
    try:
        # Catalogue frequency describes publication cadence, not every available period.
        if candidate.frequency not in {"annual", "unknown"}:
            raise ValueError("CBS catalogue frequency requires annual code inspection")
        raw, _, _ = fetch(url)
        _, preparation = prepare_table(raw)  # validates the package with the existing CBS reader
    except zipfile.BadZipFile as exc:  # a truncated or non-ZIP body
        raise base.DatasetRejected("not a readable CBS package: " + str(exc)) from exc
    except ValueError as exc:  # a malformed or non-annual package, not a transport failure
        if ("exceeds" in str(exc) and "limit" in str(exc)) or str(exc) in {
            "CBS catalogue frequency requires annual code inspection",
            "CBS code labels are ambiguous",
            "CBS package contains non-annual or unknown periods; no aggregation was performed",
        }:
            root = "https://datasets.cbs.nl/odata/v1/CBS/" + _checked(candidate.dataset)
            snapshot = cbs_odata.describe_snapshot(root, fetch)
            raw = json.dumps(snapshot).encode()
            preparation = {"metadata": json.dumps(cbs_odata.metadata(snapshot)), "odata_root": root}
        else:
            if "non-annual" in str(exc):
                raise base.DatasetRejected(
                    "dataset is not annual; no aggregation was performed (" + str(exc) + ")"
                ) from exc
            raise base.DatasetRejected(str(exc)) from exc
    metadata = json.loads(preparation["metadata"])
    measures = {m["Identifier"]: f"{m['Title']} ({m['Unit']})" for m in metadata["measures"]}
    times = [d["Identifier"] for d in metadata["dimensions"] if d["Kind"] == "TimeDimension"]
    if not times:
        raise base.DatasetRejected("CBS package has no time dimension")
    if len(times) != 1:
        raise base.DatasetRejected("CBS annual analysis requires exactly one time dimension")
    time = times[0]
    dimensions = [base.Dimension("Measure", "Measure", measures)]
    for d in metadata["dimensions"]:
        if d["Identifier"] != time:
            codes = metadata["codes"][d["Identifier"]]
            dimensions.append(
                base.Dimension(
                    d["Identifier"],
                    d.get("Title") or d["Identifier"],
                    {c: v["Title"] for c, v in codes.items()},
                )
            )
    years = {y for y in (base.annual(c) for c in metadata["codes"][time]) if y}
    start, end = scope.get("start_year"), scope.get("end_year")
    years = tuple(sorted(y for y in years if (not start or y >= start) and (not end or y <= end)))
    if not years:
        raise base.DatasetRejected(
            "dataset has no annual series in the requested period; no aggregation was performed"
        )
    extra = {
        **({"odata_root": preparation["odata_root"]} if preparation.get("odata_root") else {}),
        "other_countries": [c for c in countries if c != "NLD"],
        # _check_series: one measure, at most one series dimension; the schema follows it.
        "fixed_dimensions": ["Measure"],
        "max_series_dimensions": 1,
    }
    definitions = _definitions(metadata)
    if geography := _geography(metadata, definitions):
        extra["geography"] = geography
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dimensions),
        years=years,
        licence_url=preparation.get("license_url") or LICENCE_URL,
        definitions=definitions[:30000],
        publisher=PUBLISHER,
        payload=raw,
        extra=extra,
    )


def _check_series(selection, description=None):
    series = selection["series_dimensions"]
    facts = {"dimensions": [d.id for d in description.dimensions]} if description else {}
    if len(series) > 1:
        raise base.SelectionError("CBS selections support at most one series dimension", facts)
    if "Measure" in series:
        raise base.SelectionError(
            "Select one CBS measure; compare measures as separate analyses", facts
        )


def fetch(description, selection, scope, *, fetch, post):
    url = package_url(description.candidate.dataset)
    base.validate_selection(description, selection)
    # Checked here, the stage returns these limits to the model for a repair.
    _check_series(selection, description)
    notes = ()
    if description.extra.get("other_countries"):
        notes = (
            "CBS covers only the Netherlands; no data for: "
            + ", ".join(description.extra["other_countries"]),
        )
    if description.extra.get("odata_root"):
        body, request = cbs_odata.acquire(
            json.loads(description.payload),
            description.extra["odata_root"],
            selection,
            description.years,
            fetch,
        )
        return base.Fetched(
            raw=body,
            request=request,
            selection={"reader": "cbs_odata"},
            artifact="source.json",
            notes=notes,
        )
    return base.Fetched(
        raw=description.payload,
        request={"method": "GET", "url": url},
        selection=None,
        artifact="source.zip",
        notes=notes,
    )


def mapping(table, preparation, selection, measurement):
    _check_series(selection)
    series = selection["series_dimensions"]
    metadata = json.loads(preparation["metadata"])
    measure = selection["filters"]["Measure"][0]
    by_id = {m["Identifier"]: m for m in metadata["measures"]}
    if measure not in by_id:
        raise base.SelectionError("Unknown CBS measure code: " + measure)
    unit = by_id[measure]["Unit"]
    labels = {
        d: {c: v["Title"] for c, v in codes.items()} for d, codes in metadata["codes"].items()
    }
    filters = {"Measure": by_id[measure]["Title"], "Unit": unit}
    for d, codes in selection["filters"].items():
        if d != "Measure" and d not in series:
            filters[d] = labels[d][codes[0]]
    _, rows = read_csv(table)
    selected = [r for r in rows if all(r[k] == v for k, v in filters.items())]
    comma = any("," in r["Value"] for r in selected)
    entity = series[0] if series else ""
    result = dict(
        year_column="Year",
        value_column="Value",
        entity_column=entity,
        entities=[labels[entity][c] for c in selection["filters"][entity]] if entity else [],
        unit=unit,
        output_unit=unit,
        label=measurement,
        filters=filters,
        missing_values=[""],
        decimal_separator="," if comma else ".",
    )
    geography = [
        d["Identifier"]
        for d in metadata["dimensions"]
        if d["Kind"] in {"GeoDimension", "GeoDetailDimension"}
    ]
    if len(geography) == 1:
        dimension = geography[0]
        codes = selection["filters"].get(dimension, [])
        if dimension not in series and len(codes) == 1:
            result["identity_geography"] = labels[dimension][codes[0]]
    return result
