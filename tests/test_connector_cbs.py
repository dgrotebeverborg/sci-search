from pathlib import Path

import pytest

from sci_search.data_research.connectors import base, cbs
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import analyse_csv

FIX = Path(__file__).parent / "fixtures/data_research/connectors/cbs"


def offline(url):
    if "ODataCatalog/Tables" in url:
        return (FIX / "catalogue.json").read_bytes(), "application/json", url
    if url == "https://datasets.cbs.nl/CSV/CBS/nl/82610NED":
        return (FIX / "82610NED.zip").read_bytes(), "application/zip", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": 2000, "end_year": 2024, "countries": ["NLD"]}
CANDIDATE = base.DatasetCandidate("cbs", "82610NED", "Hernieuwbare elektriciteit", "annual")


def selection_for(description):
    dims = {d.id: d for d in description.dimensions}
    total = next(
        c
        for c, label in dims["BronTechniek"].codes.items()
        if label.strip() == "Totaal hernieuwbare energiebronnen"
    )
    return {
        "filters": {"Measure": ["M002416_2"], "BronTechniek": [total]},
        "series_dimensions": [],
        "reason": "Share",
    }


def test_search_matches_dutch_titles(tmp_path):
    candidates, digest = cbs.search(
        ["hernieuwbare elektriciteit"], SCOPE, fetch=offline, cache_dir=tmp_path
    )
    assert "82610NED" in [c.dataset for c in candidates]
    assert all(
        c.frequency in {"annual", "monthly", "quarterly", "half-yearly", "other", "unknown"}
        for c in candidates
    )
    assert next(c for c in candidates if c.dataset == "82610NED").frequency == "annual"
    assert len(digest) == 64


def test_describe_and_mapping_select_one_measure_in_one_unit():
    description = cbs.describe(CANDIDATE, SCOPE, fetch=offline)
    dims = {d.id: d for d in description.dimensions}
    assert (
        dims["Measure"].codes["M002416_2"]
        == "Genormaliseerde bruto productie (in % van het verbruik)"
    )
    assert "Perioden" not in dims
    assert 2000 in description.years and 2024 in description.years
    selection = selection_for(description)
    fetched = cbs.fetch(description, selection, SCOPE, fetch=offline, post=None)
    assert fetched.artifact == "source.zip"
    assert fetched.request == {
        "method": "GET",
        "url": "https://datasets.cbs.nl/CSV/CBS/nl/82610NED",
    }
    table, prep = prepare_table(fetched.raw, fetched.selection)
    mapping = cbs.mapping(table, prep, selection, "renewable electricity share")
    analysis = analyse_csv(table, mapping, {"start_year": 2000, "end_year": 2024})
    values = {row["year"]: row["value"] for row in analysis["series"][0]["annual"]}
    assert values[2000] == pytest.approx(2.64) and values[2024] == pytest.approx(50.54)


def test_more_than_one_series_dimension_is_refused():
    description = cbs.describe(CANDIDATE, SCOPE, fetch=offline)
    codes = list({d.id: d for d in description.dimensions}["Measure"].codes)[:2]
    selection = {
        "filters": {"Measure": codes},
        "series_dimensions": ["Measure", "BronTechniek"],
        "reason": "",
    }
    with pytest.raises(base.SelectionError, match="one series dimension"):
        cbs.mapping(b"", {}, selection, "x")


def test_series_dimension_entities_are_labels():
    description = cbs.describe(CANDIDATE, SCOPE, fetch=offline)
    selection = selection_for(description)
    codes = list({d.id: d for d in description.dimensions}["BronTechniek"].codes)[:2]
    selection["filters"]["BronTechniek"] = codes
    selection["series_dimensions"] = ["BronTechniek"]
    table, prep = prepare_table(description.payload)
    mapping = cbs.mapping(table, prep, selection, "x")
    assert mapping["entity_column"] == "BronTechniek" and len(mapping["entities"]) == 2


def test_countries_without_the_netherlands_are_rejected():
    scope = {**SCOPE, "countries": ["DEU", "FRA"]}
    with pytest.raises(base.DatasetRejected, match="only the Netherlands"):
        cbs.describe(CANDIDATE, scope, fetch=offline)


def test_other_countries_are_named_in_notes():
    scope = {**SCOPE, "countries": ["NLD", "DEU"]}
    description = cbs.describe(CANDIDATE, scope, fetch=offline)
    fetched = cbs.fetch(description, selection_for(description), scope, fetch=offline, post=None)
    assert any("DEU" in n for n in fetched.notes)


def test_non_annual_candidates_are_rejected_by_name():
    monthly = base.DatasetCandidate("cbs", "82610NED", "x", "monthly")
    with pytest.raises(base.DatasetRejected, match="dataset is monthly; no aggregation"):
        cbs.describe(monthly, SCOPE, fetch=offline)


def test_period_outside_the_package_is_rejected():
    scope = {"start_year": 1900, "end_year": 1950}
    with pytest.raises(base.DatasetRejected, match="no annual series in the requested period"):
        cbs.describe(CANDIDATE, scope, fetch=offline)


@pytest.mark.parametrize("dataset", ["../x", "82610NED/../a", "82610NED?x=1", "1"])
def test_injection_shaped_ids_are_rejected_before_any_request(dataset):
    def never(url):
        raise AssertionError("request made " + url)

    bad = base.DatasetCandidate("cbs", dataset, "x", "annual")
    with pytest.raises(base.DatasetRejected):
        cbs.describe(bad, SCOPE, fetch=never)
    description = cbs.describe(CANDIDATE, SCOPE, fetch=offline)
    import dataclasses

    with pytest.raises(base.DatasetRejected):
        cbs.fetch(
            dataclasses.replace(description, candidate=bad),
            selection_for(description),
            SCOPE,
            fetch=never,
            post=None,
        )


def test_http_errors_propagate():
    def failing(url):
        raise ValueError("HTTP 404")

    with pytest.raises(ValueError, match="HTTP 404"):
        cbs.describe(CANDIDATE, SCOPE, fetch=failing)


def test_dataset_from_url():
    assert cbs.dataset_from_url("https://www.cbs.nl/nl-nl/cijfers/detail/82610NED") == "82610NED"
    assert cbs.dataset_from_url("https://opendata.cbs.nl/ODataApi/OData/85929NED") == "85929NED"
    assert cbs.dataset_from_url("https://datasets.cbs.nl/CSV/CBS/nl/85929NED") == "85929NED"
    assert cbs.dataset_from_url("https://www.cbs.nl/nl-nl/longread/2025/iets") is None
    assert cbs.dataset_from_url("http://www.cbs.nl/nl-nl/cijfers/detail/82610NED") is None


def test_catalogue_ids_keep_their_case_and_five_digit_ids_are_accepted(tmp_path):
    catalogue = {
        "value": [
            {"Identifier": "80472ned", "Title": "Energie tabel", "Frequency": "Perjaar"},
            {"Identifier": "03763", "Title": "Energie oud", "Frequency": "Stopgezet"},
            {"Identifier": "../x", "Title": "Energie fout", "Frequency": "Perjaar"},
        ]
    }

    def fetch(url):
        import json

        return json.dumps(catalogue).encode(), "application/json", url

    candidates, _ = cbs.search(["energie"], SCOPE, fetch=fetch, cache_dir=tmp_path)
    assert sorted(c.dataset for c in candidates) == ["03763", "80472ned"]
    assert next(c for c in candidates if c.dataset == "03763").frequency == "unknown"
    assert cbs.package_url("80472ned") == "https://datasets.cbs.nl/CSV/CBS/nl/80472ned"
    assert cbs.package_url("03763").endswith("/03763")
    assert cbs.dataset_from_url("https://opendata.cbs.nl/ODataApi/OData/80472ned") == "80472ned"


def test_unknown_frequency_package_that_is_not_annual_is_rejected(monkeypatch):
    def refuse(raw):
        raise ValueError("CBS package contains non-annual or unknown periods")

    monkeypatch.setattr(cbs, "prepare_table", refuse)
    unknown = base.DatasetCandidate("cbs", "82610NED", "x", "unknown")
    with pytest.raises(base.DatasetRejected, match="dataset is not annual; no aggregation"):
        cbs.describe(unknown, SCOPE, fetch=offline)
