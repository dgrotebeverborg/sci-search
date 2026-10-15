"""Reaching the data files behind repository pages: sizes, file lists, documentation, NetCDF."""

import json
import shutil

import pytest

from tests.test_autonomous_data import strategy

ZENODO = "https://zenodo.org/records/8418278"
RECORD = {
    "files": [
        {
            "key": "runoff_SSP245_2018-2100.nc",
            "size": 66_900_000,
            "links": {
                "self": "https://zenodo.org/api/records/8418278/files/runoff_SSP245_2018-2100.nc/content"
            },
        },
        {
            "key": "everything.zip",
            "size": 900_000_000,
            "links": {
                "self": "https://zenodo.org/api/records/8418278/files/everything.zip/content"
            },
        },
    ]
}


def test_data_downloads_may_be_250_mb(monkeypatch):
    from sci_search.data_research import workflow

    assert workflow.DATA_LIMIT == 250_000_000


def test_a_zenodo_record_lists_its_files_with_sizes():
    from sci_search.data_research.retrieval import repository_files

    asked = []

    def fetch(url):
        asked.append(url)
        return json.dumps(RECORD).encode(), "application/json", url

    page = repository_files(ZENODO, fetch, limit=250_000_000)
    assert asked == ["https://zenodo.org/api/records/8418278"]
    assert page["links"] == [RECORD["files"][0]["links"]["self"]]
    assert "runoff_SSP245_2018-2100.nc (66.9 MB)" in page["text"]
    assert "everything.zip (900.0 MB, too large to download)" in page["text"]


def test_other_pages_have_no_repository_listing():
    from sci_search.data_research.retrieval import repository_files

    assert repository_files("https://example.org/records/1", lambda url: None) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://nsidc.org/sites/default/files/documents/user-guide/hma2_wbp-v001-userguide.pdf",
        "https://example.org/data/README.md",
        "https://example.org/files/Technical_Documentation.pdf",
        "https://example.org/manual.pdf",
    ],
)
def test_documentation_is_recognised(url):
    from sci_search.data_research.retrieval import is_documentation

    assert is_documentation(url)


@pytest.mark.parametrize(
    "url",
    ["https://example.org/runoff_SSP245.nc", "https://example.org/tables/population.csv"],
)
def test_data_files_are_not_documentation(url):
    from sci_search.data_research.retrieval import is_documentation

    assert not is_documentation(url)


def landing(links):
    anchors = "".join(f'<a href="{link}">file</a>' for link in links)
    return f"<html>Projected runoff under SSP scenarios. {anchors}</html>".encode()


def test_choosing_a_user_guide_as_the_data_file_is_refused(tmp_path):
    from sci_search.data_research.workflow import execute

    url = "https://nsidc.example/data/hma2_wbp"
    guide = "https://nsidc.example/documents/hma2_wbp-userguide.pdf"
    downloaded = []

    def fetch(u):
        downloaded.append(u)
        return (
            (landing([guide]), "text/html", u) if u == url else (b"%PDF-1.6", "application/pdf", u)
        )

    def complete(prompt, schema):
        if "action" in schema["properties"]:
            return dict(
                action="stop",
                source_index=0,
                link_index=-1,
                query="",
                reason="done",
                measurements=[],
            )
        return dict(
            adapter="python",
            download_link_index=0,
            reason="The user guide explains the variables.",
            definition_quote="",
            license_note="Not established",
            covered_measurements=["population"],
        )

    result = execute(
        "Projected runoff",
        strategy(),
        tmp_path,
        search=lambda *a, **k: dict(
            candidates=[
                dict(url=url, title="HMA water balance", publisher="NSIDC", rationale="Projections")
            ]
        ),
        fetch=fetch,
        complete=complete,
        connectors={},
    )
    assessment = result["assessments"][0]
    assert guide not in downloaded
    assert "documentation, not a data file" in assessment["reason"]


def test_a_zenodo_record_is_assessed_with_its_file_list(tmp_path):
    from sci_search.data_research.workflow import execute

    prompts = []

    def fetch(u):
        if u == ZENODO:
            return b"<html>Zenodo record page</html>", "text/html", u
        if u == "https://zenodo.org/api/records/8418278":
            return json.dumps(RECORD).encode(), "application/json", u
        raise ValueError("unexpected download " + u)

    def complete(prompt, schema):
        prompts.append(prompt)
        if "action" in schema["properties"]:
            return dict(
                action="stop",
                source_index=0,
                link_index=-1,
                query="",
                reason="done",
                measurements=[],
            )
        return dict(
            adapter="unsupported",
            download_link_index=-1,
            reason="Fixture stops here.",
            definition_quote="",
            license_note="Not established",
            covered_measurements=[],
        )

    execute(
        "Projected runoff",
        strategy(),
        tmp_path,
        search=lambda *a, **k: dict(
            candidates=[
                dict(
                    url=ZENODO,
                    title="Runoff projections",
                    publisher="Zenodo",
                    rationale="Projections",
                )
            ]
        ),
        fetch=fetch,
        complete=complete,
        connectors={},
    )
    assessed = prompts[0]
    assert "runoff_SSP245_2018-2100.nc (66.9 MB)" in assessed
    assert RECORD["files"][0]["links"]["self"] in assessed


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs the Python sandbox")
def test_netcdf_variables_are_inspected(tmp_path):
    netCDF4 = pytest.importorskip("netCDF4")
    from sci_search.data_research.execution import run_python
    from sci_search.data_research.python_recovery import INSPECT_CODE

    path = tmp_path / "runoff.nc"
    with netCDF4.Dataset(path, "w") as data:
        data.title = "Glacier runoff projections"
        data.createDimension("year", 3)
        runoff = data.createVariable("glacier_runoff", "f4", ("year",))
        runoff.units = "m3 s-1"
        runoff.long_name = "Annual glacier runoff"
        runoff[:] = [1.0, 2.0, 3.0]
    record = run_python(INSPECT_CODE, {"source.bin": path.read_bytes()}, tmp_path / "inspect")
    assert record["status"] == "succeeded", record.get("error")
    inspection = json.loads((tmp_path / "inspect/output/inspection.json").read_text())
    variable = inspection["netcdf"]["variables"]["glacier_runoff"]
    assert variable["dimensions"] == ["year"]
    assert variable["attributes"]["units"] == "m3 s-1"
    assert inspection["netcdf"]["attributes"]["title"] == "Glacier runoff projections"
    assert inspection["netcdf"]["dimensions"] == {"year": 3}


def test_netcdf_metadata_is_evidence_for_the_meaning_review():
    from sci_search.data_research.semantics import source_documents

    netcdf = {
        "attributes": {"title": "Runoff"},
        "variables": {"q": {"attributes": {"units": "m3 s-1"}}},
    }
    documents = source_documents("landing page", {"bytes": 10, "netcdf": netcdf})
    assert '"units": "m3 s-1"' in documents["netcdf_metadata"]


def test_the_extraction_prompt_names_netcdf():
    import inspect

    from sci_search.data_research import python_recovery

    assert "netCDF4.Dataset" in inspect.getsource(python_recovery.recover)
