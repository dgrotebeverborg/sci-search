import io
import zipfile

import pytest

from sci_search.data_research.reporting import export
from sci_search.data_research.workflow import execute


@pytest.fixture(autouse=True)
def web_path_only(monkeypatch):
    """These tests exercise the web path; the connector stage has its own workflow tests."""
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")


SCOPE = dict(
    route="data",
    rationale="Trend",
    geography="Netherlands",
    measurements=["storage use"],
    start_year=None,
    end_year=None,
)


def test_followup_search_retains_period_and_failure(tmp_path):
    calls = []

    def search(question, strategy, **kwargs):
        calls.append((question, strategy))
        if len(calls) == 2:
            raise ValueError("provider unavailable")
        return {"candidates": []}

    result = execute(
        "storage trend",
        SCOPE,
        tmp_path,
        search=search,
        complete=lambda *a: dict(
            action="search",
            query="earlier data",
            reason="Check history",
            source_index=-1,
            link_index=-1,
        ),
    )
    assert len(calls) == 2
    assert "earlier" in calls[1][0].lower()
    assert result["period"]["requested"] == "Longest comparable historical series"
    assert result["period"]["analysed"] == []
    assert result["research_process"]["steps"][0]["status"] == "failed"


def test_export_excludes_unused_engines_and_contains_report(tmp_path):
    for name in ("wildfire.py", "tabular.py", "packages.py"):
        (tmp_path / name).write_text("# retained engine")
    result = {"kind": "discovered", "analyses": [], "assessments": [], "limitations": []}
    _, _, data = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "report.html" in z.namelist()
        assert "wildfire.py" not in z.namelist()
        assert "tabular.py" not in z.namelist()
        assert "packages.py" not in z.namelist()


def test_followup_adds_new_sources_but_never_rechecks_same_url(tmp_path):
    from sci_search.data_research.period import candidates_with_followup, period_summary

    initial = {"url": "https://example.org/current"}
    earlier = {"url": "https://example.org/history"}
    result = {"analyses": [], "assessments": [], "limitations": []}
    observed = []

    def search(question, strategy, **kwargs):
        assert result["analyses"]  # runs after the first batch has been processed
        assert "2010" in question
        assert strategy["start_year"] == 2010
        return {"candidates": [initial, earlier]}

    scope = {**SCOPE, "start_year": 2010, "end_year": 2024}
    candidates = candidates_with_followup(
        "trend",
        scope,
        {"candidates": [initial]},
        result,
        search,
        None,
        observed.append,
        lambda _: None,
        lambda: None,
    )
    assert next(candidates) == initial
    result["analyses"].append(
        {
            "source": {"title": "Partial series"},
            "series": [
                {
                    "label": "use",
                    "entity": "large batteries",
                    "annual": [
                        {"year": 2022, "value": 10},
                        {"year": 2023, "value": None},
                        {"year": 2024, "value": 20},
                    ],
                }
            ],
            "limitations": ["Small batteries missing"],
        }
    )
    assert list(candidates) == [earlier]
    period = period_summary(scope, result["analyses"])
    assert period["requested"] == "2010–2024"
    assert period["analysed"][0]["first_year"] == 2022
    assert period["analysed"][0]["missing_years"] == [2023]
    assert observed


def test_empty_export_reproduces_without_unused_dependencies(tmp_path):
    import subprocess
    import sys

    result = {"kind": "discovered", "analyses": [], "assessments": [], "limitations": []}
    _, _, data = export(result, tmp_path, bundle=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp_path / "replay")
    subprocess.run([sys.executable, "reproduce.py"], cwd=tmp_path / "replay", check=True)
