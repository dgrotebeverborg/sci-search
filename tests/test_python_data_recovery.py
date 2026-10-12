import pytest

from sci_search.data_research import python_recovery
from tests.data_meaning_fixtures import with_positive_meaning_review


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


SCOPE = dict(measurements=["population"], geography="Netherlands", start_year=2001, end_year=2003)
SOURCE = dict(
    title="Population",
    url="https://example.test/population.json",
    sha256="unused",
    license_note="unknown",
)
CODE = """import json
from pathlib import Path
data=json.loads(Path("/input/source.bin").read_text())
rows=[dict(entity="Netherlands",year=int(year),value=value,unit="people",measurement="population",source_reference="/values/"+year) for year,value in data["values"].items()]
Path("/output/observations.json").write_text(json.dumps({"observations":rows,"assumptions":["Annual population"],"checks":["One observation per year"]}))
"""


def complete(prompt, schema):
    if "code" in schema["properties"]:
        return dict(code=CODE, explanation="Read nested year/value mapping")
    return dict(
        accepted=True,
        reason="Annual population, units people, source keys preserved",
        limitations=[],
    )


def test_generated_python_extracts_nested_json_and_records_code(tmp_path):
    result = python_recovery.recover(
        "Population",
        SCOPE,
        b'{"values":{"2001":0,"2003":12},"unit":"people"}',
        SOURCE,
        tmp_path,
        complete=with_positive_meaning_review(complete),
        reason="Not CSV",
    )
    series = result["series"][0]
    assert [row["value"] for row in series["annual"]] == [0, None, 12]
    assert series["annual"][2]["source_reference"] == "/values/2003"
    assert result["python_extraction"]["attempts"] == 1
    assert (tmp_path / "python/attempt-1/script.py").read_text() == CODE


def test_failed_script_is_repaired_with_real_error(tmp_path):
    attempts = []

    def repair(prompt, schema):
        if "code" in schema["properties"]:
            attempts.append(prompt)
            return dict(
                code='raise ValueError("bad field")' if len(attempts) == 1 else CODE,
                explanation="Try",
            )
        return complete(prompt, schema)

    result = python_recovery.recover(
        "Population",
        SCOPE,
        b'{"values":{"2001":9}}',
        SOURCE,
        tmp_path,
        complete=with_positive_meaning_review(repair),
        reason="Not CSV",
    )
    assert result["python_extraction"]["attempts"] == 2
    assert "bad field" in attempts[1]


def test_rejected_semantics_never_publish(tmp_path):
    def reject(prompt, schema):
        if "code" in schema["properties"]:
            return complete(prompt, schema)
        return dict(accepted=False, reason="Capacity is not actual use", limitations=[])

    with pytest.raises(ValueError, match="Capacity"):
        python_recovery.recover(
            "Population",
            SCOPE,
            b'{"values":{"2001":9}}',
            SOURCE,
            tmp_path,
            complete=reject,
            reason="Not CSV",
        )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"value": float("nan")}, "finite"),
        ({"value": True}, "numeric"),
        ({"source_reference": ""}, "reference"),
        ({"measurement": "capacity"}, "measurement"),
        ({"unit": ""}, "unit"),
    ],
)
def test_invalid_generated_observations_are_rejected(change, match):
    from sci_search.data_research.python_rows import analyse_observations

    row = dict(
        entity="Netherlands",
        year=2001,
        value=12,
        unit="people",
        measurement="population",
        source_reference="/values/2001",
    )
    with pytest.raises(ValueError, match=match):
        analyse_observations({"observations": [{**row, **change}]}, SCOPE)


def test_duplicate_rows_cannot_silently_aggregate():
    from sci_search.data_research.python_rows import analyse_observations

    row = dict(
        entity="Netherlands",
        year=2001,
        value=12,
        unit="people",
        measurement="population",
        source_reference="/values/2001",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        analyse_observations({"observations": [row, row]}, SCOPE)


def test_generated_notes_must_be_lists_for_report_and_dashboard():
    from sci_search.data_research.python_rows import analyse_observations

    row = dict(
        entity="Netherlands",
        year=2001,
        value=12,
        unit="people",
        measurement="population",
        source_reference="/values/2001",
    )
    for key in ("assumptions", "checks"):
        with pytest.raises(ValueError, match=key):
            analyse_observations({"observations": [row], key: {"rows": 1}}, SCOPE)


def test_workflow_uses_python_for_json_and_exports_executed_package(tmp_path):
    import io
    import subprocess
    import sys
    import zipfile

    from sci_search.data_research.reporting import export
    from sci_search.data_research.workflow import execute

    def model(prompt, schema):
        if "adapter" in schema["properties"]:
            return dict(
                adapter="python",
                download_link_index=-1,
                reason="Nested JSON population",
                definition_quote="",
                license_note="unknown",
                covered_measurements=["population"],
            )
        if "action" in schema["properties"]:
            return dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                reason="All requested years checked",
            )
        return complete(prompt, schema)

    scope = {**SCOPE, "route": "data", "rationale": "Population trend", "country_scope": "other"}
    result = execute(
        "Population",
        scope,
        tmp_path,
        complete=with_positive_meaning_review(model),
        search=lambda *a, **k: {"candidates": [{**SOURCE, "publisher": "Statistics"}]},
        fetch=lambda u: (b'{"values":{"2001":0,"2003":12},"unit":"people"}', "application/json", u),
    )
    assert len(result["analyses"]) == 1, result
    assert result["analyses"][0]["execution"]["status"] == "verified"
    name, _, body = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        archive.extractall(tmp_path / "replay")
    replay = subprocess.run(
        [sys.executable, "reproduce.py"], cwd=tmp_path / "replay", capture_output=True, text=True
    )
    assert replay.returncode == 0, replay.stderr
