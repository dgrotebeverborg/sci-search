# tests/test_connector_eurostat.py
from pathlib import Path

import pytest

from sci_search.data_research.connectors import base, eurostat
from sci_search.data_research.packages import prepare_table

FIX = Path(__file__).parent / "fixtures/data_research/connectors/eurostat"


def offline(url):
    if "/dataflow/ESTAT/all" in url:
        return (FIX / "dataflows.xml").read_bytes(), "application/xml", url
    if "/dataflow/ESTAT/demo_mlexpec" in url:
        return (FIX / "demo_mlexpec-structure.xml").read_bytes(), "application/xml", url
    if "detail=serieskeysonly" in url:
        return (FIX / "demo_mlexpec-keys.tsv").read_bytes(), "text/tab-separated-values", url
    if "/data/demo_mlexpec/" in url:
        return (FIX / "demo_mlexpec-slice.tsv.gz").read_bytes(), "application/octet-stream", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": 2000, "end_year": 2024, "countries": ["NLD", "DEU", "GRC"]}


def test_search_finds_life_expectancy_in_the_catalogue(tmp_path):
    candidates, digest = eurostat.search(
        ["life expectancy", "sex"], SCOPE, fetch=offline, cache_dir=tmp_path
    )
    assert "demo_mlexpec" in [c.dataset for c in candidates]
    assert len(digest) == 64


def test_describe_lists_only_observed_codes_and_maps_countries(tmp_path):
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    dims = {d.id: d for d in description.dimensions}
    assert set(dims) == {"freq", "unit", "sex", "age", "geo"}
    assert set(dims["geo"].codes) == {"NL", "DE", "EL"}  # restricted to the requested countries
    assert dims["freq"].codes == {"A": dims["freq"].codes["A"]}
    assert dims["sex"].codes["F"]  # labelled


def test_fetch_requests_a_key_filtered_slice_and_reads_it():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    requested = []

    def recording(url):
        requested.append(url)
        return offline(url)

    selection = {
        "filters": {
            "freq": ["A"],
            "unit": ["YR"],
            "sex": ["F", "M"],
            "age": ["Y_LT1"],
            "geo": ["NL", "DE", "EL"],
        },
        "series_dimensions": ["sex", "geo"],
        "reason": "Requested",
    }
    fetched = eurostat.fetch(description, selection, SCOPE, fetch=recording, post=None)
    assert "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/" in requested[-1]
    assert "startPeriod=2000" in requested[-1] and "endPeriod=2024" in requested[-1]
    table, prep = prepare_table(fetched.raw, fetched.selection)
    mapping = eurostat.mapping(table, prep, selection, "life expectancy")
    assert mapping["unit"] == "YR" and len(mapping["entities"]) == 6


def test_countries_without_data_are_dropped_with_a_note():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    selection = {
        "filters": {
            "freq": ["A"],
            "unit": ["YR"],
            "sex": ["F"],
            "age": ["Y_LT1"],
            "geo": ["NL", "DE", "EL"],
        },
        "series_dimensions": ["geo"],
        "reason": "Requested",
    }

    def slice_without_greece(url):
        body, kind, final = offline(url)
        if "/data/demo_mlexpec/" in url and "serieskeysonly" not in url:
            import gzip

            lines = gzip.decompress(body).decode().splitlines(keepends=True)
            body = gzip.compress("".join(line for line in lines if ",EL\t" not in line).encode())
        return body, kind, final

    fetched = eurostat.fetch(description, selection, SCOPE, fetch=slice_without_greece, post=None)
    assert {"dimension": "geo", "values": ["NL", "DE"]} in fetched.selection["filters"]
    assert any("EL" in note for note in fetched.notes)


def test_dataset_from_url():
    assert (
        eurostat.dataset_from_url(
            "https://ec.europa.eu/eurostat/databrowser/view/NRG_IND_REN__custom_9909313/default/bar"
        )
        == "nrg_ind_ren"
    )
    assert (
        eurostat.dataset_from_url(
            "https://ec.europa.eu/eurostat/web/products-datasets/-/demo_mlexpec"
        )
        == "demo_mlexpec"
    )
    assert (
        eurostat.dataset_from_url("https://example.org/eurostat/databrowser/view/demo_mlexpec")
        is None
    )


def test_iso3_mapping_uses_eurostat_codes():
    assert eurostat.ISO3_TO_GEO["GRC"] == "EL" and eurostat.ISO3_TO_GEO["GBR"] == "UK"
    assert eurostat.ISO3_TO_GEO["NLD"] == "NL"


def test_requested_country_without_data_is_not_a_failed_dataset():
    # Review focus (a): a missing country yields a partial result naming it.
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    selection = {
        "filters": {
            "freq": ["A"],
            "unit": ["YR"],
            "sex": ["F"],
            "age": ["Y_LT1"],
            "geo": ["NL", "DE", "EL"],
        },
        "series_dimensions": ["geo"],
        "reason": "Requested",
    }

    def without_greece(url):
        body, kind, final = offline(url)
        if "/data/demo_mlexpec/" in url and "serieskeysonly" not in url:
            import gzip

            lines = gzip.decompress(body).decode().splitlines(keepends=True)
            body = gzip.compress("".join(line for line in lines if ",EL\t" not in line).encode())
        return body, kind, final

    fetched = eurostat.fetch(description, selection, SCOPE, fetch=without_greece, post=None)
    assert fetched.notes == ("No data published for geo: EL",)
    table, prep = prepare_table(fetched.raw, fetched.selection)
    assert len(eurostat.mapping(table, prep, selection, "life expectancy")["entities"]) == 2


def test_non_annual_dataset_is_rejected_naming_the_frequency():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")

    def monthly(url):
        if "detail=serieskeysonly" in url:
            if "/data/demo_mlexpec/A." in url:
                return b"freq,unit,sex,age,geo\n", "text/tab-separated-values", url
            return b"freq,unit,sex,age,geo\nM,YR,F,Y_LT1,DE\n", "text/tab-separated-values", url
        return offline(url)

    with pytest.raises(base.DatasetRejected, match="dataset is M; no aggregation was performed"):
        eurostat.describe(candidate, SCOPE, fetch=monthly)
