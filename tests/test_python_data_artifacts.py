import hashlib
import json
import subprocess
import sys

import pytest

from sci_search.data_research import artifacts
from sci_search.data_research.tabular import analyse_csv


def fixture(tmp_path):
    body = b"Year,Value\n2001,10\n2003,12\n"
    source = {
        "title": "Values",
        "url": "https://example.test/data.csv",
        "artifact": "source.csv",
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    mapping = dict(
        year_column="Year",
        value_column="Value",
        entity_column="",
        label="population",
        unit="people",
        output_unit="people",
    )
    analysis = {
        **analyse_csv(body, mapping, dict(start_year=2001, end_year=2003)),
        "kind": "tabular",
        "source": source,
    }
    (tmp_path / "source.csv").write_bytes(body)
    return analysis


def test_existing_adapter_is_executed_before_publishing(tmp_path):
    result = artifacts.execute_analysis(fixture(tmp_path), tmp_path)
    assert result["execution"]["status"] == "verified"
    assert result["series"][0]["annual"][1]["value"] is None
    assert (tmp_path / "calculation/script.py").exists()
    assert (tmp_path / "calculation/output/result.json").exists()
    assert result["execution"]["script_sha256"]


def test_calculation_mismatch_is_not_published(tmp_path):
    analysis = fixture(tmp_path)
    analysis["series"][0]["annual"][0]["value"] = 999
    with pytest.raises(ValueError, match="differ"):
        artifacts.execute_analysis(analysis, tmp_path)


def test_source_hash_mismatch_is_not_published(tmp_path):
    analysis = fixture(tmp_path)
    (tmp_path / "source.csv").write_bytes(b"Year,Value\n2001,999\n")
    with pytest.raises(ValueError, match="hash"):
        artifacts.execute_analysis(analysis, tmp_path)


def test_offline_replay_verifies_executed_code_and_detects_tampering(tmp_path):
    folder = tmp_path / "source-1"
    folder.mkdir()
    result = artifacts.execute_analysis(fixture(folder), folder)
    (folder / "analysis.json").write_text(json.dumps(result))
    (tmp_path / "analysis.json").write_text(
        json.dumps({"kind": "discovered", "analyses": [result]})
    )
    artifacts.write_replay(tmp_path)
    run = subprocess.run(
        [sys.executable, "reproduce.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    assert "Verified source-1" in run.stdout
    (folder / "calculation/script.py").write_text("pass")
    run = subprocess.run(
        [sys.executable, "reproduce.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert run.returncode != 0
    assert "hash" in run.stderr


def test_replay_rejects_changed_aggregate_and_missing_sources(tmp_path):
    folder = tmp_path / "source-1"
    folder.mkdir()
    result = artifacts.execute_analysis(fixture(folder), folder)
    (folder / "analysis.json").write_text(json.dumps(result))
    result["series"][0]["annual"][0]["value"] = 999
    (tmp_path / "analysis.json").write_text(
        json.dumps({"kind": "discovered", "analyses": [result]})
    )
    artifacts.write_replay(tmp_path)
    run = subprocess.run(
        [sys.executable, "reproduce.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert run.returncode != 0
    assert "Published analysis" in run.stderr
    (folder / "analysis.json").unlink()
    run = subprocess.run(
        [sys.executable, "reproduce.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert run.returncode != 0
