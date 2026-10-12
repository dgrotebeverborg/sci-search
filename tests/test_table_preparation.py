import io
import zipfile

import pytest

from sci_search.data_research.preparation import inspect_table, prepare_delimited, transform_table
from sci_search.data_research.tabular import read_csv
from tests.data_meaning_fixtures import with_positive_meaning_review


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


def test_empty_trailing_columns_removed_only_if_empty_everywhere():
    body = b"id;year;value;;;\nA;2001;2;;;\nB;2003;0;;;\n"
    data, prep = prepare_delimited(body)
    assert read_csv(data)[0] == ["id", "year", "value"]
    assert prep["checks"]["input_rows"] == prep["checks"]["output_rows"] == 2
    assert prep["row_provenance"]["3"]["source_reference"] == "line:3"
    with pytest.raises(ValueError):
        prepare_delimited(body + b"C;2004;1;;important;\n")


def test_inspection_and_explicit_preamble_encoding_selection():
    body = "Population café\nYear;People\n2000;1\n2001;2\n".encode("cp1252")
    preview = inspect_table(body)
    assert any(c["encoding"] == "cp1252" for c in preview["candidates"])
    data, prep = prepare_delimited(
        body, {"encoding": "cp1252", "delimiter": ";", "header_row": 2, "entry": ""}
    )
    assert read_csv(data)[1][0]["Year"] == "2000"
    assert "Population café" in prep["metadata"]
    assert prep["row_provenance"]["2"]["source_reference"] == "line:3"


def test_zip_table_selection_and_documentation():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("values.csv", "year,value\n2000,1\n")
        z.writestr("codes.csv", "code,label\n1,Italy\n")
        z.writestr("README.txt", "Reported events, Italy only")
    preview = inspect_table(out.getvalue())
    assert "Italy only" in preview["metadata"]
    data, prep = prepare_delimited(
        out.getvalue(),
        {"entry": "values.csv", "encoding": "utf-8-sig", "delimiter": ",", "header_row": 1},
    )
    assert prep["row_provenance"]["2"]["source_reference"] == "values.csv:2"
    assert read_csv(data)[1][0]["value"] == "1"


def test_wide_to_long_preserves_values_and_coordinates():
    data, prep = prepare_delimited(b"Country,2000,2001\nItaly,3,:\nFrance,0,4\n")
    data, prep = transform_table(data, prep, {"operation": "unpivot", "columns": ["2000", "2001"]})
    assert read_csv(data)[1] == [
        {"Country": "Italy", "Year": "2000", "Value": "3"},
        {"Country": "Italy", "Year": "2001", "Value": ":"},
        {"Country": "France", "Year": "2000", "Value": "0"},
        {"Country": "France", "Year": "2001", "Value": "4"},
    ]
    assert prep["row_provenance"]["3"]["source_reference"] == "line:2; column:2001"


def test_count_events_rejects_duplicate_ids_and_keeps_absent_years_absent():
    data, prep = prepare_delimited(
        b"id,date,region\na,2000-02-01,A\nb,2000-03-01,A\nc,2002-01-01,A\n"
    )
    plan = {
        "operation": "count_events",
        "year_column": "date",
        "date_format": "%Y-%m-%d",
        "id_column": "id",
        "entity_column": "region",
    }
    result, info = transform_table(data, prep, plan)
    assert read_csv(result)[1] == [
        {"region": "A", "Year": "2000", "Recorded events": "2"},
        {"region": "A", "Year": "2002", "Recorded events": "1"},
    ]
    assert "line:2" in info["row_provenance"]["2"]["source_reference"]
    assert info["checks"]["counted_events"] == 3
    with pytest.raises(ValueError, match="unique"):
        transform_table(data.replace(b"b,2000", b"a,2000"), prep, plan)


def test_no_execution_unknown_operations_and_invalid_dates():
    data, prep = prepare_delimited(b"id,date\na,01/02/03\n")
    with pytest.raises(ValueError):
        transform_table(data, prep, {"operation": "python", "code": "print(1)"})
    with pytest.raises(ValueError):
        transform_table(
            data,
            prep,
            {
                "operation": "count_events",
                "year_column": "date",
                "date_format": "",
                "id_column": "id",
                "entity_column": "",
            },
        )


def test_workflow_recovers_wide_table_and_replays_offline(tmp_path):
    import subprocess
    import sys

    from sci_search.data_research.reporting import export
    from sci_search.data_research.workflow import execute

    scope = dict(
        route="data",
        rationale="Annual population",
        measurements=["population"],
        geography="Italy",
        start_year=None,
        end_year=None,
    )
    calls = []

    def complete(prompt, schema):
        calls.append(prompt)
        keys = schema["properties"]
        if "adapter" in keys:
            return dict(
                adapter="csv",
                download_link_index=-1,
                reason="Annual population",
                definition_quote="",
                license_note="Unknown",
                covered_measurements=[],
            )
        if "operation" in keys:
            return dict(
                operation="unpivot",
                columns=["2000", "2001"],
                year_column="",
                id_column="",
                entity_column="",
                date_format="",
                reason="Years are columns",
            )
        if "suitable" in keys:
            if "Transformation:" not in prompt:
                return dict(suitable=False, reason="Years are columns")
            return dict(
                suitable=True,
                reason="Italy only",
                measurement="population",
                unit_evidence="people",
                mapping=dict(
                    year_column="Year",
                    entity_column="Country",
                    entities=["Italy"],
                    value_column="Value",
                    unit="people",
                    output_unit="people",
                    label="Population",
                    filters=[],
                    missing_values=[":"],
                    decimal_separator=".",
                ),
            )
        return dict(action="stop", source_index=-1, link_index=-1, query="", reason="Done")

    result = execute(
        "Population over time",
        scope,
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.org/table.csv", title="People", publisher="Statistics")
            ]
        },
        fetch=lambda url: (b"# people\nCountry,2000,2001\nItaly,3,4\n", "text/csv", url),
        complete=with_positive_meaning_review(complete),
    )
    assert result["analyses"], result["assessments"]
    assert result["assessments"][0]["transformation_attempts"][0]["status"] == "validated"
    annual = result["analyses"][0]["series"][0]["annual"]
    assert [r["value"] for r in annual] == [3, 4]
    assert annual[0]["source_reference"] == "line:3; column:2000"
    _, _, bundle = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)


def test_workflow_repairs_header_after_failed_plan(tmp_path):
    from sci_search.data_research.workflow import execute

    plans = iter([1, 2])

    def complete(prompt, schema):
        keys = schema["properties"]
        if "adapter" in keys:
            return dict(
                adapter="csv",
                download_link_index=-1,
                reason="Values",
                definition_quote="",
                license_note="",
                covered_measurements=[],
            )
        if "header_row" in keys:
            return dict(
                entry="",
                encoding="cp1252",
                delimiter=";",
                header_row=next(plans),
                reason="Observed header",
            )
        if "suitable" in keys:
            return dict(
                suitable=True,
                reason="Annual values",
                measurement="population",
                unit_evidence="people",
                mapping=dict(
                    year_column="Year",
                    entity_column="",
                    entities=[],
                    value_column="people",
                    unit="people",
                    output_unit="people",
                    label="Italy",
                    filters=[],
                    missing_values=[],
                    decimal_separator=".",
                ),
            )
        return dict(action="stop", source_index=-1, link_index=-1, query="", reason="Done")

    result = execute(
        "Population",
        dict(
            route="data",
            rationale="Trend",
            measurements=["population"],
            geography="Italy",
            start_year=None,
            end_year=None,
        ),
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.org/t.csv", title="Population", publisher="Office")
            ]
        },
        fetch=lambda url: (
            "Café population\nYear;people\n2000;2\n".encode("cp1252"),
            "text/csv",
            url,
        ),
        complete=with_positive_meaning_review(complete),
    )
    assert result["analyses"], result["assessments"]
    assert [a["status"] for a in result["assessments"][0]["preparation_attempts"]] == [
        "failed",
        "failed",
        "validated",
    ]
    assert (tmp_path / "source-1/source-original.csv").read_bytes().startswith(b"Caf\xe9")


def test_pipe_delimiter_is_not_misread_as_one_column():
    from sci_search.data_research.packages import prepare_table

    data, _ = prepare_table(b"Year|people\n2000|3\n2001|4\n")
    assert read_csv(data)[0] == ["Year", "people"]


def test_multiline_header_keeps_physical_source_rows():
    data, prep = prepare_delimited(b'# note\n"Country\nname",2000,2001\nItaly,3,4\nFrance,5,6\n')
    _, _, lines = read_csv(data, with_line_numbers=True)
    assert [prep["row_provenance"][str(n)]["source_reference"] for n in lines] == [
        "line:4",
        "line:5",
    ]
    data, prep = transform_table(data, prep, {"operation": "unpivot", "columns": ["2000", "2001"]})
    _, _, lines = read_csv(data, with_line_numbers=True)
    assert prep["row_provenance"][str(lines[0])]["source_reference"] == "line:4; column:2000"


def test_cbs_transform_cannot_discard_authoritative_units():
    data = b"Year,Value\n2000,3\n"
    prep = {
        "format": "cbs_csv_zip_v1",
        "row_provenance": {"2": {"unit": "MW", "entry": "Observations.csv", "source_row": 3}},
    }
    with pytest.raises(ValueError, match="CBS"):
        transform_table(
            data, prep, {"operation": "year_from_date", "year_column": "Year", "date_format": ""}
        )


def test_single_column_false_parse_triggers_header_inspection():
    from sci_search.data_research.packages import prepare_table

    body = b"Population table\nYear;people\n2000;3\n"
    with pytest.raises(ValueError):
        prepare_table(body)
    data, _ = prepare_table(
        body,
        {
            "reader": "delimited",
            "entry": "",
            "encoding": "utf-8-sig",
            "delimiter": ";",
            "header_row": 2,
        },
    )
    assert read_csv(data)[0] == ["Year", "people"]


def test_stacked_annual_section_keeps_source_lines_and_excluded_sections():
    from sci_search.data_research.preparation import prepare_delimited
    from sci_search.data_research.tabular import read_csv

    body = (
        b"N;gem\n731;1900\njr;N;gem\n2019;365;1950\n2020;366;1869\nmaandjr;N;gem\n01-2020;31;1897\n"
    )
    selection = dict(
        entry="",
        encoding="utf-8-sig",
        delimiter=";",
        header_row=3,
        end_row=5,
        reason="Annual section between overview and monthly table",
    )
    table, prep = prepare_delimited(body, selection)
    headers, rows = read_csv(table)
    assert headers == ["jr", "N", "gem"]
    assert rows == [
        {"jr": "2019", "N": "365", "gem": "1950"},
        {"jr": "2020", "N": "366", "gem": "1869"},
    ]
    assert prep["row_provenance"]["2"]["source_reference"] == "line:4"
    assert "maandjr" in prep["metadata"]
    assert prep["checks"]["selected_end_row"] == 5


def test_section_boundary_cannot_truncate_numeric_observations():
    from sci_search.data_research.preparation import prepare_delimited

    with pytest.raises(ValueError, match="section boundary"):
        prepare_delimited(
            b"Year;Value\n2000;1\n2001;2\n2002;3\n",
            dict(entry="", encoding="utf-8-sig", delimiter=";", header_row=1, end_row=3),
        )
