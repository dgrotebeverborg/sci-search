import copy
import csv
import hashlib
import io
from datetime import date, timedelta

import pytest

from sci_search.data_research.daily import aggregate_daily
from sci_search.data_research.tabular import read_csv
from tests.data_meaning_fixtures import with_positive_meaning_review

PLAN = dict(
    operation="daily_mean",
    year_column="Date",
    value_column="Flow (m3/s)",
    entity_column="",
    date_format="%Y-%m-%d",
    decimal_separator=".",
    missing_values=["", "NA"],
)


def table(rows, headers=("Date", "Flow (m3/s)")):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    writer.writerows(rows)
    return out.getvalue().encode()


def days(year, value="2"):
    start = date(year, 1, 1)
    return [
        [str(start + timedelta(days=n)), value] for n in range((date(year + 1, 1, 1) - start).days)
    ]


def test_complete_leap_year_and_provenance_are_preserved_without_mutation():
    rows = days(2024)
    rows[-1][1] = "368"
    prep = {
        "row_provenance": {"2": {"source_reference": "source.csv:8"}},
        "limitations": ["original"],
    }
    original = copy.deepcopy(prep)
    body = table(rows)
    output, result = aggregate_daily(body, prep, PLAN)
    headers, actual = read_csv(output)
    assert headers == ["Year", "Flow (m3/s)", "Observed days", "Expected days"]
    assert float(actual[0]["Flow (m3/s)"]) == 3
    assert result["daily_coverage"] == [
        dict(entity="", year=2024, observed_days=366, expected_days=366, status="complete")
    ]
    assert "source.csv:8" in result["row_provenance"]["2"]["source_reference"]
    assert "line:367" in result["row_provenance"]["2"]["source_reference"]
    assert result["normalized_sha256"] == hashlib.sha256(output).hexdigest()
    result["transformations"][0]["missing_values"].append("changed")
    assert PLAN["missing_values"] == ["", "NA"]
    assert prep == original
    assert body == table(rows)


@pytest.mark.parametrize("rows,observed", [(days(2023)[:-1], 364), (days(2023, "NA"), 0)])
def test_incomplete_year_is_blank(rows, observed):
    output, prep = aggregate_daily(table(rows), {}, PLAN)
    assert read_csv(output)[1][0]["Flow (m3/s)"] == ""
    assert prep["daily_coverage"][0]["observed_days"] == observed
    assert prep["daily_coverage"][0]["status"] == "incomplete"


def test_entities_constants_and_missing_middle_year():
    rows = [["A", *r, "river"] for r in days(2022) + days(2024)]
    rows += [["B", *r, "lake"] for r in days(2023, "4")]
    output, prep = aggregate_daily(
        table(rows, ["Station", "Date", "Flow (m3/s)", "Type"]),
        {},
        {**PLAN, "entity_column": "Station"},
    )
    actual = read_csv(output)[1]
    a = [r for r in actual if r["Station"] == "A"]
    assert [r["Year"] for r in a] == ["2022", "2023", "2024"]
    assert a[1]["Flow (m3/s)"] == ""
    assert a[1]["Observed days"] == "0"
    assert all(r["Type"] == "river" for r in a)
    assert (
        float(next(r for r in actual if r["Station"] == "B" and r["Year"] == "2023")["Flow (m3/s)"])
        == 4
    )


@pytest.mark.parametrize(
    "rows",
    [
        [["2023-01-01", "2"], ["2023-01-01", "3"]],
        [["2023-02-29", "2"]],
        [["2023-01-01", "NaN"]],
        [["2023-01-01", "inf"]],
        [["2023-01-01", "1e999"]],
        [["2023-01-01", "hello"]],
        [["1800-01-01", "2"], ["2199-01-01", "3"]],
    ],
)
def test_invalid_data_rejected(rows):
    with pytest.raises(ValueError):
        aggregate_daily(table(rows), {}, PLAN)


def test_varying_unselected_dimension_rejected():
    with pytest.raises(ValueError, match="vary"):
        aggregate_daily(
            table(
                [["2023-01-01", "2", "good"], ["2023-01-02", "3", "bad"]],
                ["Date", "Flow (m3/s)", "Quality"],
            ),
            {},
            PLAN,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"year_column": "unknown"},
        {"date_format": "%Y"},
        {"decimal_separator": ";"},
        {"value_column": "Date"},
    ],
)
def test_invalid_plan_rejected(change):
    with pytest.raises(ValueError):
        aggregate_daily(table(days(2023)), {}, {**PLAN, **change})


def test_decimal_comma():
    output, _ = aggregate_daily(table(days(2023, "2,5")), {}, {**PLAN, "decimal_separator": ","})
    assert float(read_csv(output)[1][0]["Flow (m3/s)"]) == 2.5


@pytest.mark.parametrize("column", ["Year", "Observed days", "Expected days"])
def test_output_column_collision(column):
    with pytest.raises(ValueError, match="collision"):
        aggregate_daily(
            table([["2023-01-01", "2", "x"]], ["Date", "Flow (m3/s)", column]), {}, PLAN
        )


def test_missing_middle_year_attaches_coverage_without_fabricated_provenance():
    import csv
    import io
    from datetime import date, timedelta

    from sci_search.data_research.packages import attach_provenance
    from sci_search.data_research.tabular import analyse_csv

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Flow m3/s"])
    for year in (2018, 2020):
        day = date(year, 1, 1)
        while day.year == year:
            writer.writerow([day.isoformat(), 2])
            day += timedelta(days=1)
    plan = dict(
        operation="daily_mean",
        year_column="Date",
        value_column="Flow m3/s",
        entity_column="",
        date_format="%Y-%m-%d",
        decimal_separator=".",
        missing_values=[],
    )
    data, prep = aggregate_daily(out.getvalue().encode(), {}, plan)
    analysis = analyse_csv(
        data,
        dict(
            year_column="Year",
            value_column="Flow m3/s",
            entity_column="",
            unit="m3/s",
            output_unit="m3/s",
            label="Flow",
        ),
        {},
    )
    attach_provenance(analysis, prep)
    missing = analysis["series"][0]["annual"][1]
    assert missing["value"] is None
    assert missing["source_reference"] == ""
    assert missing["source_status"] == "incomplete: 0/365 valid daily means"


@pytest.mark.parametrize("documented", [True, False])
def test_workflow_daily_definition_and_offline_replay(tmp_path, documented):
    import io
    import subprocess
    import sys
    import zipfile
    from datetime import date, timedelta

    from sci_search.data_research.reporting import export
    from sci_search.data_research.workflow import execute

    definition = "Daily means" if documented else "Daily snapshots at 08:00"
    body = (
        "# "
        + definition
        + " in m3/s\nDate,Flow\n"
        + "".join(f"{date(2020, 1, 1) + timedelta(days=i)},10\n" for i in range(366))
    ).encode()

    def complete(prompt, schema):
        keys = schema["properties"]
        if "adapter" in keys:
            return dict(
                adapter="csv",
                download_link_index=-1,
                reason="River flow",
                definition_quote=definition,
                license_note="Unknown",
                covered_measurements=["flow"],
            )
        if "operation" in keys:
            return dict(
                operation="daily_mean",
                year_column="Date",
                value_column="Flow",
                entity_column="",
                date_format="%Y-%m-%d",
                decimal_separator=".",
                missing_values=[""],
                aggregation_evidence="Daily means",
                reason="Annual means",
            )
        if "suitable" in keys:
            if "Transformation:" not in prompt:
                return dict(suitable=False, reason="Daily rows need annual aggregation")
            return dict(
                suitable=True,
                reason="Annual flow",
                measurement="flow",
                unit_evidence="m3/s",
                mapping=dict(
                    year_column="Year",
                    value_column="Flow",
                    entity_column="",
                    entities=[],
                    unit="m3/s",
                    output_unit="m3/s",
                    label="Flow",
                    filters=[],
                    missing_values=[""],
                    decimal_separator=".",
                ),
            )
        return dict(action="stop", source_index=-1, link_index=-1, query="", reason="Done")

    result = execute(
        "Annual mean river flow",
        dict(
            route="data",
            rationale="Trend",
            measurements=["flow"],
            geography="Lobith",
            start_year=2020,
            end_year=2020,
        ),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.org/data.csv", title="Flow", publisher="Agency")
            ]
        },
        fetch=lambda url: (body, "text/csv", url),
        complete=with_positive_meaning_review(complete),
    )
    if not documented:
        assert not result["analyses"]
        attempt = result["assessments"][0]["transformation_attempts"][0]
        assert attempt["status"] == "failed"
        assert "exact source definition" in attempt["reason"]
        return
    assert result["analyses"], result["assessments"]
    analysis = result["analyses"][0]
    assert analysis["series"][0]["annual"][0]["value"] == 10
    assert analysis["daily_coverage"][0]["observed_days"] == 366
    _, _, bundle = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        archive.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)
