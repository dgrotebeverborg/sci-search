import hashlib
import json
from pathlib import Path

import pytest

from sci_search.data_research.connectors import base, owid
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv

FIX = Path(__file__).parent / "fixtures/data_research/connectors/owid"


def offline(url):
    if "/api/search?" in url:
        return (FIX / "search.json").read_bytes(), "application/json", url
    if url.startswith("https://ourworldindata.org/grapher/life-expectancy.csv"):
        return (FIX / "life-expectancy.csv").read_bytes(), "text/csv", url
    if url.startswith("https://ourworldindata.org/grapher/life-expectancy.metadata.json"):
        return (FIX / "life-expectancy.metadata.json").read_bytes(), "application/json", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": 2000, "end_year": 2023, "countries": ["NLD", "DEU"]}
CANDIDATE = base.DatasetCandidate("owid", "life-expectancy", "Life expectancy", "annual")


def test_search_returns_chart_slugs(tmp_path):
    candidates, _ = owid.search(["life expectancy"], SCOPE, fetch=offline, cache_dir=tmp_path)
    assert "life-expectancy" in [c.dataset for c in candidates]


def test_describe_restricts_entities_and_fetch_reads_through_reader():
    description = owid.describe(CANDIDATE, SCOPE, fetch=offline)
    dims = {d.id: d for d in description.dimensions}
    assert set(dims["entity"].codes) == {"Germany", "Netherlands"}
    indicator = next(iter(dims["indicator"].codes))
    selection = {
        "filters": {"indicator": [indicator], "entity": ["Germany", "Netherlands"]},
        "series_dimensions": ["entity"],
        "reason": "Requested",
    }
    fetched = owid.fetch(description, selection, SCOPE, fetch=offline, post=None)
    table, prep = prepare_table(fetched.raw, fetched.selection)
    mapping = owid.mapping(table, prep, selection, "life expectancy")
    assert mapping["unit"] == "years" and set(mapping["entities"]) == {"Germany", "Netherlands"}
    assert len(fetched.request["csv_sha256"]) == 64


def test_fetch_records_hashes_of_the_original_responses():
    description = owid.describe(CANDIDATE, SCOPE, fetch=offline)
    selection = {
        "filters": {"indicator": ["life_expectancy_0"], "entity": ["Germany"]},
        "series_dimensions": ["entity"],
        "reason": "Requested",
    }
    request = owid.fetch(description, selection, SCOPE, fetch=offline, post=None).request
    assert (
        request["csv_sha256"]
        == hashlib.sha256((FIX / "life-expectancy.csv").read_bytes()).hexdigest()
    )
    meta = (FIX / "life-expectancy.metadata.json").read_bytes()
    assert request["metadata_sha256"] == hashlib.sha256(meta).hexdigest()
    envelope = json.loads(fetched_raw(description, selection))
    assert hashlib.sha256(envelope["csv"].encode()).hexdigest() == request["csv_sha256"]
    assert hashlib.sha256(envelope["metadata"].encode()).hexdigest() == request["metadata_sha256"]


def fetched_raw(description, selection):
    return owid.fetch(description, selection, SCOPE, fetch=offline, post=None).raw


def test_bom_csv_hash_is_recomputable_and_rows_parse():
    def bom(url):
        body, kind, final = offline(url)
        return (b"\xef\xbb\xbf" + body if ".csv" in url else body), kind, final

    description = owid.describe(CANDIDATE, SCOPE, fetch=bom)
    selection = {
        "filters": {"indicator": ["life_expectancy_0"], "entity": ["Germany"]},
        "series_dimensions": ["entity"],
        "reason": "x",
    }
    fetched = owid.fetch(description, selection, SCOPE, fetch=bom, post=None)
    envelope = json.loads(fetched.raw)
    assert hashlib.sha256(envelope["csv"].encode()).hexdigest() == fetched.request["csv_sha256"]
    _, rows = read_csv(prepare_table(fetched.raw, fetched.selection)[0])
    assert {r["Series"] for r in rows} == {"Germany"}


@pytest.mark.parametrize("which", [".csv", ".metadata.json"])
def test_oversized_response_is_rejected(which):
    def big(url):
        if which in url:
            return b"x" * 5_000_001, "text/plain", url
        return offline(url)

    with pytest.raises(base.DatasetRejected, match="5 MB"):
        owid.describe(CANDIDATE, SCOPE, fetch=big)


def test_missing_countries_are_named_and_all_missing_is_rejected():
    scope = {**SCOPE, "countries": ["NLD", "ZZZ"]}
    description = owid.describe(CANDIDATE, scope, fetch=offline)
    selection = {
        "filters": {"indicator": ["life_expectancy_0"], "entity": ["Netherlands"]},
        "series_dimensions": ["entity"],
        "reason": "Requested",
    }
    fetched = owid.fetch(description, selection, scope, fetch=offline, post=None)
    assert any("ZZZ" in note for note in fetched.notes)
    with pytest.raises(base.DatasetRejected, match="ZZZ"):
        owid.describe(CANDIDATE, {**SCOPE, "countries": ["ZZZ"]}, fetch=offline)


def test_aggregates_are_not_countries():
    with pytest.raises(base.DatasetRejected, match="OWID_WRL"):
        owid.describe(CANDIDATE, {**SCOPE, "countries": ["OWID_WRL"]}, fetch=offline)


def test_period_without_data_is_rejected():
    with pytest.raises(base.DatasetRejected, match="no annual series in the requested period"):
        owid.describe(CANDIDATE, {"start_year": 2500, "end_year": 2600}, fetch=offline)


def test_non_annual_chart_is_rejected():
    def monthly(url):
        if ".csv" in url:
            return b"entity,code,year,x\nGermany,DEU,2020-01,1\n", "text/csv", url
        return b"{}", "application/json", url

    with pytest.raises(base.DatasetRejected, match="dataset is monthly; no aggregation"):
        owid.describe(CANDIDATE, {}, fetch=monthly)


@pytest.mark.parametrize("slug", ["../x", "a/b", "a?b", "Life-Expectancy", ""])
def test_injection_shaped_slugs_are_rejected(slug):
    bad = base.DatasetCandidate("owid", slug, "x", "annual")
    with pytest.raises(base.DatasetRejected):
        owid.describe(bad, SCOPE, fetch=offline)


def test_fetch_rejects_unobserved_entity():
    description = owid.describe(CANDIDATE, SCOPE, fetch=offline)
    selection = {
        "filters": {"indicator": ["life_expectancy_0"], "entity": ["France"]},
        "series_dimensions": ["entity"],
        "reason": "x",
    }
    with pytest.raises(base.SelectionError):
        owid.fetch(description, selection, SCOPE, fetch=offline, post=None)


def test_dataset_from_url():
    assert (
        owid.dataset_from_url("https://ourworldindata.org/grapher/life-expectancy?tab=chart")
        == "life-expectancy"
    )
    assert owid.dataset_from_url("https://ourworldindata.org/life-expectancy") is None
