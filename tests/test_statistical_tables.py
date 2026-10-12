import gzip

import pytest

from sci_search.data_research.packages import attach_provenance, prepare_table
from sci_search.data_research.statistical_tables import (
    decompress,
    inspect_statistics,
    prepare_statistics,
)
from sci_search.data_research.tabular import analyse_csv, read_csv
from tests.data_meaning_fixtures import with_positive_meaning_review

DATA = b"freq,unit,sex,age,geo\\TIME_PERIOD\t2000 \t2001 \t2002 \nA,YR,F,Y_LT1,NL\t80.1 \t: \t81.2 b\nA,YR,M,Y_LT1,NL\t75.2 p\t76.1 \t76.4 \nA,YR,F,Y1,NL\t82 \t83 \t84 \n"


def selection():
    return dict(
        reader="statistical_tsv",
        filters=[
            dict(dimension="freq", values=["A"]),
            dict(dimension="unit", values=["YR"]),
            dict(dimension="age", values=["Y_LT1"]),
            dict(dimension="sex", values=["M", "F"]),
            dict(dimension="geo", values=["NL"]),
        ],
        series_dimensions=["geo", "sex"],
        reason="At birth, separate sexes",
    )


def test_inspection_and_selected_series_keep_flags_dimensions_missing():
    body = gzip.compress(DATA)
    preview = inspect_statistics(body)
    assert preview["dimension_values"]["age"] == ["Y_LT1", "Y1"]
    table, prep = prepare_table(body, selection())
    headers, rows = read_csv(table)
    assert len(rows) == 6
    assert rows[1]["Value"] == ":"
    assert rows[2]["Status"] == "b"
    assert rows[0]["Series"] != rows[3]["Series"]
    assert prep["checks"]["selected_series"] == 2
    assert prep["row_provenance"]["4"]["source_reference"] == "line:2; period:2002"
    assert prepare_table(body, prep["selection"])[0] == table


def test_all_unplotted_dimensions_must_be_fixed():
    plan = selection()
    plan["filters"] = [f for f in plan["filters"] if f["dimension"] != "age"]
    with pytest.raises(ValueError, match="dimension"):
        prepare_statistics(DATA, plan)


def test_no_unknown_codes_or_duplicate_series_or_nonannual_periods():
    plan = selection()
    plan["filters"][0]["values"] = ["invented"]
    with pytest.raises(ValueError):
        prepare_statistics(DATA, plan)
    with pytest.raises(ValueError):
        inspect_statistics(DATA + DATA.splitlines(keepends=True)[1])
    with pytest.raises(ValueError):
        inspect_statistics(DATA.replace(b"2000 ", b"2000-Q1 "))


def test_gzip_expansion_is_bounded():
    with pytest.raises(ValueError, match="expanded"):
        decompress(gzip.compress(b"x" * 11000000))


def test_flags_and_units_survive_analysis_and_breaks_suppress_change():
    table, prep = prepare_table(gzip.compress(DATA), selection())
    rows = read_csv(table)[1]
    mapping = dict(
        year_column="Year",
        value_column="Value",
        entity_column="Series",
        entities=list(dict.fromkeys(r["Series"] for r in rows)),
        unit="YR",
        output_unit="YR",
        label="Life expectancy at birth",
        filters=[],
        missing_values=[":"],
        decimal_separator=".",
    )
    result = analyse_csv(table, mapping, dict(start_year=2000, end_year=2002))
    attach_provenance(result, prep)
    assert result["series"][0]["annual"][2]["source_status"] == "b"
    assert result["series"][0]["absolute_change"] is None
    assert result["series"][1]["annual"][0]["source_status"] == "p"
    assert result["series"][1]["absolute_change"] is not None
    bad = analyse_csv(
        table,
        {**mapping, "unit": "people", "output_unit": "people"},
        dict(start_year=2000, end_year=2002),
    )
    with pytest.raises(ValueError, match="unit"):
        attach_provenance(bad, prep)


def test_oversize_official_download_retries_scoped_compressed_request():
    from sci_search.data_research.retrieval import fetch_scoped

    calls = []
    attempts = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            raise ValueError("Dataset exceeds the 5 MB acquisition limit")
        return b"data", "text/plain", url

    fetch_scoped(
        "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_mlexpec/?format=TSV",
        {"start_year": 1926, "end_year": 2025},
        fetch,
        attempts,
    )
    assert (
        "compressed=true" in calls[1]
        and "startPeriod=1926" in calls[1]
        and "endPeriod=2025" in calls[1]
    )
    assert attempts[0]["status"] == "retried_with_requested_period"


def test_gzip_generic_csv_replay_keeps_original_container():
    body = gzip.compress(b"Year,Value\n2000,3\n")
    table, prep = prepare_table(body)
    assert prep["format"] != "csv"
    assert read_csv(table)[1][0]["Value"] == "3"


@pytest.mark.parametrize(
    "source_url",
    [
        "https://example.org/data.tsv.gz",
        "https://ec.europa.eu/eurostat/databrowser/view/demo_mlexpec/default/table?lang=en",
    ],
)
def test_statistical_workflow_and_offline_export(tmp_path, source_url):
    import io
    import subprocess
    import sys
    import zipfile

    from sci_search.data_research.reporting import export
    from sci_search.data_research.tabular import read_csv
    from sci_search.data_research.workflow import execute

    body = gzip.compress(DATA)
    table, _ = prepare_table(body, selection())
    entities = list(dict.fromkeys(r["Series"] for r in read_csv(table)[1]))

    def complete(prompt, schema):
        keys = schema["properties"]
        if "adapter" in keys:
            return dict(
                adapter="csv",
                download_link_index=-1,
                reason="Annual life expectancy",
                definition_quote="",
                license_note="Unknown",
                covered_measurements=[],
            )
        if "series_dimensions" in keys:
            return {k: v for k, v in selection().items() if k != "reader"}
        if "suitable" in keys:
            return dict(
                suitable=True,
                reason="Available years only",
                measurement="life expectancy",
                unit_evidence="YR",
                mapping=dict(
                    year_column="Year",
                    value_column="Value",
                    entity_column="Series",
                    entities=entities,
                    unit="YR",
                    output_unit="YR",
                    label="Life expectancy",
                    filters=[],
                    missing_values=[":"],
                    decimal_separator=".",
                ),
            )
        return dict(action="stop", source_index=-1, link_index=-1, query="", reason="Done")

    result = execute(
        "Life expectancy by sex",
        dict(
            route="data",
            rationale="Annual",
            measurements=["life expectancy"],
            geography="Netherlands",
            start_year=1999,
            end_year=2003,
        ),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(
                    url=source_url,
                    title="Life expectancy",
                    publisher="Office",
                )
            ]
        },
        fetch=lambda url: (body, "application/gzip", url),
        complete=with_positive_meaning_review(complete),
    )
    assert len(result["analyses"]) == 1, result["assessments"]
    if "/databrowser/" in source_url:
        assert (
            result["assessments"][0]["api_resolution"]["method"]
            == "documented_eurostat_sdmx_endpoint"
        )
    a = result["analyses"][0]
    assert a["source"]["artifact"] == "source.tsv.gz"
    assert len(a["series"]) == 2 and a["series"][0]["annual"][0]["value"] is None
    _, _, bundle = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        assert b"<td>b</td>" in z.read("report.html")
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)


def test_combined_flags_remain_separate_from_values():
    body = DATA.replace(b"81.2 b", b"81.2 cp").replace(b"75.2 p", b"75.2 ep")
    table, prep = prepare_table(gzip.compress(body), selection())
    rows = read_csv(table)[1]
    assert rows[2]["Value"] == ":" and rows[2]["Status"] == "cp"
    mapping = dict(
        year_column="Year",
        value_column="Value",
        entity_column="Series",
        entities=list(dict.fromkeys(r["Series"] for r in rows)),
        unit="YR",
        output_unit="YR",
        label="Life expectancy",
        filters=[],
        missing_values=[":"],
        decimal_separator=".",
    )
    result = analyse_csv(table, mapping, dict(start_year=2000, end_year=2002))
    attach_provenance(result, prep)
    assert result["series"][1]["absolute_change"] is not None


def test_every_dimension_requires_explicit_selection_including_series():
    plan = selection()
    plan["filters"] = [f for f in plan["filters"] if f["dimension"] not in ["sex", "geo"]]
    with pytest.raises(ValueError, match="dimension"):
        prepare_statistics(DATA, plan)


def test_observed_eurostat_dataset_page_resolves_documented_api():
    from sci_search.data_research.retrieval import eurostat_download_url

    scope = {"start_year": 1926, "end_year": 2025}
    url = eurostat_download_url(
        "https://ec.europa.eu/eurostat/databrowser/view/demo_mlexpec/default/table?lang=en", scope
    )
    assert "/data/demo_mlexpec/" in url and "compressed=true" in url
    assert "startPeriod=1926" in url and "endPeriod=2025" in url
    assert (
        eurostat_download_url(
            "https://evil.example/eurostat/databrowser/view/demo_mlexpec/default/table", scope
        )
        is None
    )


def test_eurostat_queued_response_is_polled_then_downloaded(monkeypatch):
    from sci_search.data_research.retrieval import fetch_scoped

    key = "9a651ce4-34cb-4ed0-aa22-2a5a2fcf570b"
    calls = []
    attempts = []

    def fetch(url):
        calls.append(url)
        if "/async/status/" in url:
            return b"<root><status>AVAILABLE</status></root>", "application/xml", url
        if "/async/data/" in url:
            return gzip.compress(DATA), "application/gzip", url
        return (
            f"<root><queued><id>{key}</id><status>SUBMITTED</status></queued></root>".encode(),
            "application/xml",
            url,
        )

    body, _, url = fetch_scoped(
        "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_mlexpec/",
        {},
        fetch,
        attempts,
    )
    assert gzip.decompress(body) == DATA
    assert "/async/data/" + key in url
    assert len(calls) == 3
