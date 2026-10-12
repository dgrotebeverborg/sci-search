import io
import zipfile

import pytest

from sci_search.data_research.spreadsheets import inspect_workbook, workbook_table
from tests.data_meaning_fixtures import with_positive_meaning_review


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


def workbook():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Losses" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Annual losses, EUR</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Year</t></is></c><c r="B2" t="inlineStr"><is><t>Loss</t></is></c></row><row r="3"><c r="A3"><v>2020</v></c><c r="B3"><v>12</v></c></row></sheetData></worksheet>',
        )
    return out.getvalue()


def test_inspect_before_select_and_preserve_coordinates():
    body = workbook()
    preview = inspect_workbook(body)
    assert preview["sheets"][0]["name"] == "Losses"
    assert preview["sheets"][0]["sample_rows"][0]["cells"][0] == "Annual losses, EUR"
    csv, prep = workbook_table(body, {"sheet_index": 0, "header_row": 2})
    assert csv.decode().splitlines() == ["Year,Loss", "2020,12"]
    assert prep["row_provenance"]["2"]["source_reference"] == "Losses!3"
    with pytest.raises(ValueError):
        workbook_table(body, {"sheet_index": 5, "header_row": 2})


def test_nested_workbook_retains_readme_and_xml():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("data/table.xlsx", workbook())
        z.writestr("data/README.md", "Combined hazards; not a landslide-specific series.")
        z.writestr("data/metadata.xml", "<description>Coverage 1980–2024</description>")
    preview = inspect_workbook(out.getvalue())
    assert "not a landslide-specific" in preview["metadata"]
    assert "1980–2024" in preview["metadata"]
    assert preview["entry"] == "data/table.xlsx"


def test_conceptual_trends_route_to_both():
    from sci_search.data_research.strategy import validate_strategy

    result = validate_strategy(
        dict(
            route="data",
            rationale="Trends",
            measurements=["landslide hazard", "landslide risk"],
            geography="Europe",
            start_year=None,
            end_year=None,
        ),
        infer_route=True,
    )
    assert result["route"] == "both"


def test_excel_workflow_inspects_and_reproduces(tmp_path):
    import subprocess
    import sys

    from sci_search.data_research.reporting import export
    from sci_search.data_research.workflow import execute

    scope = dict(
        route="data",
        rationale="Trend",
        measurements=["losses"],
        geography="A",
        start_year=None,
        end_year=None,
    )
    replies = iter(
        [
            dict(
                adapter="csv",
                download_link_index=-1,
                reason="Inspect annual table",
                definition_quote="",
                license_note="Unknown",
                covered_measurements=[],
            ),
            dict(sheet_index=0, header_row=2, reason="Annual losses in EUR"),
            dict(
                suitable=True,
                measurement="losses",
                reason="Annual loss observations",
                unit_evidence="EUR",
                mapping=dict(
                    year_column="Year",
                    entity_column="",
                    entities=[],
                    value_column="Loss",
                    unit="EUR",
                    output_unit="EUR",
                    label="Loss",
                    filters=[],
                    missing_values=[""],
                    decimal_separator=".",
                ),
            ),
            dict(action="stop", source_index=-1, link_index=-1, query="", reason="No more sources"),
        ]
    )
    result = execute(
        "annual losses",
        scope,
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.org/data.xlsx", title="Data", publisher="Office")
            ]
        },
        fetch=lambda url: (
            workbook(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            url,
        ),
        complete=with_positive_meaning_review(lambda *a: next(replies)),
    )
    assert result["assessments"][0]["workbook_inspected"]
    assert result["analyses"], result["assessments"]
    assert result["analyses"][0]["series"][0]["annual"][0]["source_reference"] == "Losses!3"
    _, _, bundle = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        assert "spreadsheets.py" in z.namelist()
        assert "source-1/source.xlsx" in z.namelist()
        assert "wildfire.py" not in z.namelist()
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)


def test_package_inspection_rejects_unsafe_paths():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("../bad.xlsx", workbook())
    with pytest.raises(ValueError, match="Unsafe"):
        inspect_workbook(out.getvalue())


def test_formulas_are_inspected_but_not_silently_evaluated():
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(workbook())) as original,
        zipfile.ZipFile(output, "w") as changed,
    ):
        for name in original.namelist():
            body = original.read(name)
            if name.endswith("sheet1.xml"):
                body = body.replace(b"<v>12</v>", b"<f>6+6</f><v>12</v>")
            changed.writestr(name, body)
    preview = inspect_workbook(output.getvalue())
    assert preview["sheets"][0]["sample_rows"][-1]["cells"][-1] == {"formula": True, "cached": "12"}
    with pytest.raises(ValueError, match="formulas"):
        workbook_table(output.getvalue(), {"sheet_index": 0, "header_row": 2})


def amended_workbook(changes):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(workbook())) as original,
        zipfile.ZipFile(output, "w") as changed,
    ):
        for name in original.namelist():
            changed.writestr(name, changes.pop(name, original.read(name)))
        for name, body in changes.items():
            changed.writestr(name, body)
    return output.getvalue()


@pytest.mark.parametrize("location", ["cell", "row", "column"])
def test_percentage_formats_are_not_silently_read_as_raw_ratios(location):
    with zipfile.ZipFile(io.BytesIO(workbook())) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").replace(
            b'<c r="B3"><v>12</v>', b'<c r="B3" s="1"><v>0.12</v>'
        )
    if location != "cell":
        sheet = sheet.replace(b'<c r="B3" s="1">', b'<c r="B3">')
        if location == "row":
            sheet = sheet.replace(b'<row r="3">', b'<row r="3" s="1" customFormat="1">')
        else:
            sheet = sheet.replace(
                b"<sheetData>", b'<cols><col min="2" max="2" style="1"/></cols><sheetData>'
            )
    body = amended_workbook(
        {
            "xl/worksheets/sheet1.xml": sheet,
            "xl/styles.xml": '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="10"/></cellXfs></styleSheet>',
        }
    )
    inspection = inspect_workbook(body)
    assert "number_format" in str(inspection)
    with pytest.raises(ValueError, match="number format"):
        workbook_table(body, {"sheet_index": 0, "header_row": 2})


def test_corrupt_shared_string_is_a_handled_source_failure():
    with zipfile.ZipFile(io.BytesIO(workbook())) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").replace(
            b'<c r="B3"><v>12</v>', b'<c r="B3" t="s"><v>99</v>'
        )
    body = amended_workbook(
        {
            "xl/worksheets/sheet1.xml": sheet,
            "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Only string</t></si></sst>',
        }
    )
    with pytest.raises(ValueError, match="shared string"):
        inspect_workbook(body)


def test_combined_quality_keeps_literature_evidence_when_data_is_empty():
    from sci_search.result_quality import result_quality

    quality = result_quality(
        {
            "data_analysis": {"kind": "discovered", "strategy": {"route": "both"}, "analyses": []},
            "answer_adequacy": {
                "can_answer_overall_question": False,
                "qualifying_evidence_ids": ["e1"],
            },
            "evidence": [{"id": "e1"}],
        }
    )
    assert quality["status"] == "partial"
    assert quality["qualifying_passages"] == 1
    assert quality["label"] == "Partial combined evidence"
