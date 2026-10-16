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


def _described(scope=SCOPE, fetch=offline):
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    return candidate, eurostat.describe(candidate, scope, fetch=fetch)


def test_injection_shaped_dataset_ids_are_refused():
    bad = base.DatasetCandidate("eurostat", "demo_mlexpec/../x?y=1", "x", "unknown")
    with pytest.raises(base.DatasetRejected):
        eurostat.describe(bad, SCOPE, fetch=offline)
    candidate, description = _described()
    forged = base.DatasetDescription(
        bad, description.dimensions, (), "", "", "Eurostat", extra=description.extra
    )
    selection = {
        "filters": {"freq": ["A"], "unit": ["YR"], "sex": ["F"], "age": ["Y_LT1"], "geo": ["NL"]},
        "series_dimensions": ["geo"],
        "reason": "x",
    }
    with pytest.raises(base.DatasetRejected):
        eurostat.fetch(forged, selection, SCOPE, fetch=offline, post=None)


def test_search_skips_flows_with_unsafe_ids(tmp_path):
    body = (FIX / "dataflows.xml").read_bytes().replace(b'id="DEMO_MLEXPEC"', b'id="DEMO/../X?Y=1"')

    def poisoned(url):
        return (body, "application/xml", url) if "/dataflow/ESTAT/all" in url else offline(url)

    candidates, _ = eurostat.search(["life expectancy"], SCOPE, fetch=poisoned, cache_dir=tmp_path)
    assert all(eurostat.DATASET.fullmatch(c.dataset) for c in candidates)
    assert "demo_mlexpec" not in [c.dataset for c in candidates]


def test_requested_country_missing_from_key_listing_is_noted_by_fetch():
    def without_greece(url):
        body, kind, final = offline(url)
        if "serieskeysonly" in url:
            lines = body.decode().splitlines(keepends=True)
            body = "".join(line for line in lines if not line.rstrip().endswith(",EL")).encode()
        return body, kind, final

    _, description = _described(fetch=without_greece)
    assert set(description.extra["missing_geo"]) == {"EL"}
    assert "EL" not in description.dimensions[-1].codes
    selection = {
        "filters": {
            "freq": ["A"],
            "unit": ["YR"],
            "sex": ["F"],
            "age": ["Y_LT1"],
            "geo": ["NL", "DE"],
        },
        "series_dimensions": ["geo"],
        "reason": "Requested",
    }
    fetched = eurostat.fetch(description, selection, SCOPE, fetch=offline, post=None)
    assert "No data published for geo: EL" in fetched.notes


def test_transport_errors_are_not_mistaken_for_missing_series():
    def broken(url):
        if "serieskeysonly" in url:
            raise ValueError("Dataset server returned HTTP 503")
        return offline(url)

    with pytest.raises(ValueError, match="HTTP 503"):
        _described(fetch=broken)


def test_not_found_key_listing_is_a_missing_annual_series_not_a_transport_error():
    def not_found(url):
        if "serieskeysonly" in url:
            raise ValueError("Dataset server returned HTTP 404")
        return offline(url)

    with pytest.raises(base.DatasetRejected, match="no annual series in the requested period"):
        _described(fetch=not_found)


def test_non_annual_dataset_names_the_frequency_in_words():
    def monthly(url):
        if "detail=serieskeysonly" in url:
            if "/data/demo_mlexpec/A." in url:
                return b"freq,unit,sex,age,geo\n", "text/tab-separated-values", url
            return b"freq,unit,sex,age,geo\nM,YR,F,Y_LT1,DE\n", "text/tab-separated-values", url
        return offline(url)

    with pytest.raises(base.DatasetRejected, match="dataset is monthly; no aggregation"):
        _described(fetch=monthly)


def test_countries_without_eurostat_codes_are_named():
    with pytest.raises(base.DatasetRejected, match="USA"):
        _described({"start_year": 2000, "end_year": 2024, "countries": ["USA"]})
    _, description = _described({**SCOPE, "countries": ["NLD", "USA"]})
    assert description.extra["unmapped"] == ["USA"]


def test_all_requested_countries_missing_is_rejected_naming_them():
    def only_germany(url):
        body, kind, final = offline(url)
        if "serieskeysonly" in url:
            lines = body.decode().splitlines(keepends=True)
            body = "".join(ln for ln in lines if not ln.rstrip().endswith(",DE")).encode()
        return body, kind, final

    with pytest.raises(base.DatasetRejected, match="DE"):
        _described({**SCOPE, "countries": ["DEU"]}, fetch=only_germany)


def test_a_key_combination_without_series_is_a_selection_error_with_published_combinations():
    # Live nrg_ind_ured: codes observed one by one, but not together. Eurostat answers
    # with a header-only table rather than HTTP 404.
    import gzip

    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    empty = gzip.compress(b"freq,unit,sex,age,geo\\TIME_PERIOD\t2000 \t2001 \r\n")
    requested = []

    def header_only(url):
        requested.append(url)
        if "/data/demo_mlexpec/" in url and "serieskeysonly" not in url:
            return empty, "text/tab-separated-values", url
        return offline(url)

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
    with pytest.raises(base.SelectionError, match="No published series") as raised:
        eurostat.fetch(description, selection, SCOPE, fetch=header_only, post=None)
    combinations = raised.value.facts["published_combinations"]
    assert combinations and len(combinations) <= 30
    assert {"freq": "A", "unit": "YR", "sex": "F", "age": "Y_LT1"} in combinations
    # The listing is narrowed to the selected series-dimension codes.
    assert "/data/demo_mlexpec/....NL+DE+EL/" in requested[-1]


def test_an_empty_slice_without_published_combinations_rejects_the_dataset():
    import gzip

    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    empty = gzip.compress(b"freq,unit,sex,age,geo\\TIME_PERIOD\t2000 \t2001 \r\n")

    def nothing_published(url):
        if "serieskeysonly" in url:
            raise ValueError("Dataset server returned HTTP 404")
        if "/data/demo_mlexpec/" in url:
            return empty, "text/tab-separated-values", url
        return offline(url)

    selection = {
        "filters": {"freq": ["A"], "unit": ["YR"], "sex": ["F"], "age": ["Y_LT1"], "geo": ["NL"]},
        "series_dimensions": ["geo"],
        "reason": "Requested",
    }
    with pytest.raises(base.DatasetRejected, match="no published series"):
        eurostat.fetch(description, selection, SCOPE, fetch=nothing_published, post=None)


def html(url):
    return b"<html><body>Service unavailable<br></body></html>", "text/html", url


def test_a_catalogue_that_is_not_xml_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="Eurostat catalogue is not XML"):
        eurostat.search(["life expectancy"], SCOPE, fetch=html, cache_dir=tmp_path)


def test_a_structure_that_is_not_xml_rejects_the_dataset():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    with pytest.raises(
        base.DatasetRejected, match="Eurostat structure for demo_mlexpec is not XML"
    ):
        eurostat.describe(candidate, SCOPE, fetch=html)


def test_describe_labels_dimensions_with_their_concept_names():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    labels = {d.id: d.label for d in description.dimensions}
    assert labels["age"] == "Age class"
    assert labels["geo"] == "Geopolitical entity (reporting)"
    assert "Age class: Y_LT1 = Less than 1 year" in description.definitions
    assert "Age class (age): This code list contains periods of time" in description.definitions


def test_series_discovery_is_filtered_to_requested_countries_and_period():
    from urllib.parse import parse_qs, urlsplit

    urls = []

    def fetch(url):
        urls.append(url)
        return offline(url)

    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    eurostat.describe(candidate, SCOPE, fetch=fetch)
    request = next(u for u in urls if "serieskeysonly" in u)
    assert "/A....DE+EL+NL/" in request
    assert parse_qs(urlsplit(request).query)["endPeriod"] == ["2024"]


def test_series_discovery_rejects_malformed_response_instead_of_claiming_missing_countries():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")

    def fetch(url):
        if "serieskeysonly" in url:
            return b"<html>Service temporarily unavailable</html>", "text/html", url
        return offline(url)

    with pytest.raises(base.DatasetRejected, match="series-key response"):
        eurostat.describe(candidate, SCOPE, fetch=fetch)
