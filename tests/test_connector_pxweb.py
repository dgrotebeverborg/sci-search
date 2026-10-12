import json
import re
from pathlib import Path

import pytest

from sci_search.data_research.connectors import base, pxweb
from sci_search.data_research.packages import prepare_table

FIX = Path(__file__).parent / "fixtures/data_research/connectors/pxweb"


def offline(url):
    if "/api/v2/tables?query=" in url:
        return (FIX / "scb-search.json").read_bytes(), "application/json", url
    if "/TAB4311/metadata" in url:
        return (FIX / "scb-TAB4311-metadata.json").read_bytes(), "application/json", url
    if "/TAB4311/data" in url:
        return (FIX / "scb-TAB4311-data.json").read_bytes(), "application/json", url
    if "data.ssb.no/api/v0/en/table/?query=" in url:
        return (FIX / "ssb-search.json").read_bytes(), "application/json", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": None, "end_year": None, "countries": []}


def ssb_description(**extra):
    return base.DatasetDescription(
        candidate=base.DatasetCandidate(
            "pxweb", "ssb:08307", "08307: Electricity balance", "unknown"
        ),
        dimensions=(base.Dimension("ContentsCode", "contents", {"Produksjon": "Production"}),),
        years=(2020, 2021),
        licence_url="https://data.norge.no/nlod/en/2.0",
        definitions="",
        publisher="Statistics Norway",
        extra={"time": "Tid", "time_codes": ["2020", "2021"], **extra},
    )


def test_search_covers_v1_and_v2_installations(tmp_path):
    candidates, _ = pxweb.search(["electricity"], SCOPE, fetch=offline, cache_dir=tmp_path)
    datasets = [c.dataset for c in candidates]
    assert "scb:TAB4311" in datasets  # table ids keep the source's casing
    assert any(re.fullmatch(r"ssb:\d{5}", d) for d in datasets)
    assert len(datasets) == len(set(datasets))
    scb = next(c for c in candidates if c.dataset == "scb:TAB4311")
    assert scb.frequency == "half-yearly"


def test_search_skips_installations_outside_the_requested_countries(tmp_path):
    scope = {**SCOPE, "countries": ["NOR"]}

    def only_ssb(url):
        assert "scb" not in url
        return offline(url)

    candidates, _ = pxweb.search(["electricity"], scope, fetch=only_ssb, cache_dir=tmp_path)
    assert candidates and all(c.dataset.startswith("ssb:") for c in candidates)


def test_v2_describe_and_fetch_read_through_jsonstat():
    candidate = base.DatasetCandidate("pxweb", "scb:TAB4311", "Electricity prices", "other")
    description = pxweb.describe(candidate, SCOPE, fetch=offline, require_annual=False)
    dims = {d.id: d for d in description.dimensions}
    assert "Tid" not in dims and {"Kategorimwh", "ContentsCode"} <= set(dims)
    first = {d: [next(iter(dims[d].codes))] for d in dims}
    selection = {"filters": first, "series_dimensions": [], "reason": "One series"}
    requested = []

    def recording(url):
        requested.append(url)
        return offline(url)

    fetched = pxweb.fetch(description, selection, SCOPE, fetch=recording, post=None)
    assert (
        "valueCodes%5BContentsCode%5D=" in requested[-1]
        or "valueCodes[ContentsCode]=" in requested[-1]
    )
    assert fetched.selection["reader"] == "jsonstat2" and fetched.artifact == "source.json"
    assert fetched.selection["code_labels"]["Kategorimwh"]["IA"] == "less than 20 MWh"
    with pytest.raises(ValueError, match="half-yearly; no aggregation was performed"):
        prepare_table(fetched.raw, fetched.selection)


def test_v1_fetch_posts_a_jsonstat_query():
    sent = []

    def post(url, payload):
        sent.append((url, payload))
        return b'{"class": "dataset"}', "application/json", url

    selection = {"filters": {"ContentsCode": ["Produksjon"]}, "series_dimensions": [], "reason": ""}
    fetched = pxweb.fetch(
        ssb_description(), selection, {"start_year": 2021, "end_year": None}, fetch=None, post=post
    )
    url, payload = sent[0]
    assert url == "https://data.ssb.no/api/v0/en/table/08307"
    assert payload["response"] == {"format": "json-stat2"}
    assert {"code": "Tid", "selection": {"filter": "item", "values": ["2021"]}} in payload["query"]
    assert fetched.request["method"] == "POST"


def test_v1_describe_reads_variables_and_annual_years():
    meta = {
        "title": "08307: Electricity balance",
        "variables": [
            {
                "code": "ContentsCode",
                "text": "contents",
                "values": ["P"],
                "valueTexts": ["Production"],
            },
            {
                "code": "Tid",
                "text": "year",
                "values": ["2020", "2021"],
                "valueTexts": ["2020", "2021"],
                "time": True,
            },
        ],
    }
    seen = []

    def fetch(url):
        seen.append(url)
        return json.dumps(meta).encode(), "application/json", url

    candidate = base.DatasetCandidate("pxweb", "ssb:08307", "08307: Electricity balance", "unknown")
    description = pxweb.describe(candidate, SCOPE, fetch=fetch)
    assert seen == ["https://data.ssb.no/api/v0/en/table/08307"]
    assert description.years == (2020, 2021)
    assert description.extra["time"] == "Tid"
    with pytest.raises(base.DatasetRejected, match="no annual series in the requested period"):
        pxweb.describe(candidate, {**SCOPE, "start_year": 2030}, fetch=fetch)


def test_monthly_tables_are_rejected_in_describe():
    meta = json.loads((FIX / "scb-TAB4311-metadata.json").read_text())
    assert any(not c.isdigit() for c in next(iter(meta["dimension"]["Tid"]["category"]["index"])))
    candidate = base.DatasetCandidate(
        "pxweb", "scb:TAB4311", "Electricity prices, half-year", "other"
    )
    with pytest.raises(
        base.DatasetRejected, match="dataset is half-yearly; no aggregation was performed"
    ):
        pxweb.describe(candidate, SCOPE, fetch=offline, require_annual=True)


@pytest.mark.parametrize(
    "dataset",
    [
        "scb:TAB1/../x",
        "scb:tab4311x?a=1",
        "ssb:0830",
        "ssb:08307/x",
        "nope:TAB1",
        "scb:",
        "TAB4311",
    ],
)
def test_malformed_ids_are_rejected_before_any_request(dataset):
    def never(url):
        raise AssertionError("requested " + url)

    candidate = base.DatasetCandidate("pxweb", dataset, "x", "unknown")
    with pytest.raises(base.DatasetRejected):
        pxweb.describe(candidate, SCOPE, fetch=never)
    description = ssb_description()
    description = base.DatasetDescription(**{**description.__dict__, "candidate": candidate})
    selection = {"filters": {"ContentsCode": ["Produksjon"]}, "series_dimensions": [], "reason": ""}
    with pytest.raises(base.DatasetRejected):
        pxweb.fetch(description, selection, SCOPE, fetch=never, post=never)


def test_search_skips_catalogue_entries_with_unusable_ids(tmp_path):
    def fetch(url):
        if "tables?query=" in url:
            body = {"tables": [{"id": "../x", "label": "electricity", "firstPeriod": "2000"}]}
            return json.dumps(body).encode(), "application/json", url
        return (
            json.dumps([{"id": "a b", "path": "/x", "title": "electricity"}]).encode(),
            "application/json",
            url,
        )

    candidates, _ = pxweb.search(["electricity"], SCOPE, fetch=fetch, cache_dir=tmp_path)
    assert candidates == []


def test_other_countries_are_named_not_dropped():
    candidate = base.DatasetCandidate("pxweb", "ssb:08307", "x", "unknown")
    with pytest.raises(base.DatasetRejected, match="Statistics Norway covers only NOR"):
        pxweb.describe(candidate, {**SCOPE, "countries": ["SWE"]}, fetch=lambda u: 1 / 0)
    sent = []

    def post(url, payload):
        sent.append(payload)
        return b"{}", "application/json", url

    selection = {"filters": {"ContentsCode": ["Produksjon"]}, "series_dimensions": [], "reason": ""}
    description = ssb_description(other_countries=["SWE"])
    fetched = pxweb.fetch(description, selection, SCOPE, fetch=None, post=post)
    assert any("SWE" in note for note in fetched.notes)


def test_not_found_is_not_swallowed():
    def missing(url):
        raise ValueError("HTTP 404 for " + url)

    candidate = base.DatasetCandidate("pxweb", "scb:TAB4311", "x", "other")
    with pytest.raises(ValueError, match="HTTP 404"):
        pxweb.describe(candidate, SCOPE, fetch=missing)


def test_dataset_from_url():
    assert (
        pxweb.dataset_from_url("https://statistikdatabasen.scb.se/api/v2/tables/TAB4311/data")
        == "scb:TAB4311"
    )
    assert pxweb.dataset_from_url("https://data.ssb.no/api/v0/en/table/08307") == "ssb:08307"
    assert pxweb.dataset_from_url("https://example.com/api/v2/tables/TAB4311") is None


def test_mapping_uses_series_mapping():
    table = b"Year,Series,Value,Unit,Status\n2020,value,1.5,CSEK,\n2021,value,:,CSEK,\n"
    result = pxweb.mapping(table, {}, {}, "price")
    assert result["unit"] == "CSEK" and result["missing_values"] == [":"]


def test_a_v1_table_is_analysed_end_to_end_from_a_posted_jsonstat_query(tmp_path):
    from sci_search.data_research.connectors import stage
    from tests.data_meaning_fixtures import with_positive_meaning_review
    from tests.test_jsonstat import dataset

    meta = {
        "title": "08307: Electricity",
        "variables": [
            {"code": "Region", "text": "region", "values": ["SE1", "SE2"], "valueTexts": ["North", "South"]},
            {"code": "ContentsCode", "text": "contents", "values": ["EL01"], "valueTexts": ["Electricity use"]},
            {"code": "Tid", "text": "year", "values": ["2020", "2021"], "time": True},
        ],
    }  # fmt: skip
    posted = []

    def fetch(url):
        assert url == "https://data.ssb.no/api/v0/en/table/08307"
        return json.dumps(meta).encode(), "application/json", url

    def post(url, payload):
        posted.append((url, payload))
        return dataset(), "application/json", url

    selection = {
        "filters": {"Region": ["SE1", "SE2"], "ContentsCode": ["EL01"]},
        "series_dimensions": ["Region"],
        "reason": "Both regions",
    }
    candidate = base.DatasetCandidate("pxweb", "ssb:08307", "08307: Electricity", "unknown")
    scope = {
        "measurements": ["electricity use"],
        "geography": "Norway",
        "countries": ["NOR"],
        "start_year": 2020,
        "end_year": 2021,
    }
    analysis, assessment = stage.analyse_dataset(
        "Electricity use in Norway",
        scope,
        tmp_path,
        pxweb,
        candidate,
        "electricity use",
        complete=with_positive_meaning_review(lambda prompt, schema: selection),
        fetch=fetch,
        post=post,
        check_cancelled=lambda: None,
        progress=lambda message: None,
    )
    assert assessment["decision"] == "analysed", assessment.get("reason")
    assert analysis is not None
    url, payload = posted[0]
    assert url == "https://data.ssb.no/api/v0/en/table/08307"
    assert {"code": "Tid", "selection": {"filter": "item", "values": ["2020", "2021"]}} in payload[
        "query"
    ]
    assert analysis["execution"]["status"] == "verified"
    assert analysis["source"]["connector"]["request"]["method"] == "POST"
    assert analysis["source"]["download"]["reproducible"] is False
    assert "POST" in analysis["source"]["download"]["reason"]
    assert len(analysis["series"]) == 2
