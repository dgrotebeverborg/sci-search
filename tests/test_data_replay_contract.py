"""Offline bundles and retained artifacts share one portable trust boundary."""

import hashlib
import io
import json
import subprocess
import sys
import zipfile

import pytest

from sci_search.data_research.reporting import export
from sci_search.data_research.tabular import analyse_csv


def test_legacy_tabular_bundle_replays_without_installed_repository(tmp_path):
    body = b"Year,Value\n2020,10\n2021,12\n"
    analysis = {
        **analyse_csv(
            body,
            dict(
                year_column="Year",
                value_column="Value",
                entity_column="",
                label="population",
                unit="people",
                output_unit="people",
            ),
            dict(start_year=2020, end_year=2021),
        ),
        "kind": "tabular",
        "source": {
            "title": "Example",
            "url": "https://example.test/data.csv",
            "artifact": "source.csv",
            "sha256": hashlib.sha256(body).hexdigest(),
        },
    }
    source = tmp_path / "source-1"
    source.mkdir()
    (source / "source.csv").write_bytes(body)
    (source / "analysis.json").write_text(json.dumps(analysis))
    _, _, bundle = export({"kind": "discovered", "analyses": [analysis]}, tmp_path, bundle=True)
    target = tmp_path / "exported"
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        archive.extractall(target)
    replay = subprocess.run(
        [sys.executable, "-S", "reproduce.py"], cwd=target, capture_output=True, text=True
    )
    assert replay.returncode == 0, replay.stderr
    assert "Verified source-1" in replay.stdout


@pytest.mark.parametrize(
    "case", ["escape", "absolute", "missing", "directory", "hash", "symlink", "symlink-parent"]
)
def test_validator_rejects_invalid_artifacts_consistently(tmp_path, case):
    from sci_search.data_research.artifact_validation import validate_artifacts

    root = tmp_path / "retained"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_bytes(b"original")
    (root / "data").write_bytes(b"original")
    checksum = hashlib.sha256(b"original").hexdigest()
    name = "data"
    if case == "escape":
        name = "../outside/data"
    elif case == "absolute":
        name = str(outside / "data")
    elif case == "missing":
        name = "missing"
    elif case == "directory":
        name = "folder"
        (root / name).mkdir()
    elif case == "hash":
        checksum = "0" * 64
    elif case == "symlink":
        (root / "data").unlink()
        (root / "data").symlink_to(outside / "data")
    else:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        name = "linked/data"
    with pytest.raises(ValueError, match="[Aa]rtifact"):
        validate_artifacts(root, {name: checksum})


@pytest.mark.parametrize("consumer", ["source-replay", "derived-input", "resume"])
@pytest.mark.parametrize("case", ["escape", "missing", "symlink-parent"])
def test_retained_consumers_use_artifact_validation(tmp_path, consumer, case):
    from sci_search.data_research import artifacts, derived_artifacts, resume
    from sci_search.data_research.strategy import validate_strategy

    root = tmp_path / "run"
    folder = root / "source-1"
    folder.mkdir(parents=True)
    body = b"sealed"
    (root / "outside").write_bytes(body)
    (folder / "linked").symlink_to(root, target_is_directory=True)
    name = {"escape": "../outside", "missing": "missing", "symlink-parent": "linked/outside"}[case]
    analysis = {
        "kind": "tabular",
        "execution": {"status": "verified", "artifacts": {name: hashlib.sha256(body).hexdigest()}},
    }
    (folder / "analysis.json").write_text(json.dumps(analysis))
    strategy = validate_strategy(
        dict(
            route="data",
            rationale="Trend",
            geography="Netherlands",
            measurements=["population"],
            start_year=2020,
            end_year=2021,
        )
    )
    state = {
        "kind": "discovered",
        "question": "Trend",
        "strategy": strategy,
        "analyses": [analysis],
        "assessments": [],
    }
    (root / "analysis.json").write_text(json.dumps(state))
    if consumer == "source-replay":
        artifacts.write_replay(root)
        replay = subprocess.run(
            [sys.executable, "-S", "reproduce.py"], cwd=root, capture_output=True, text=True
        )
        assert replay.returncode != 0
        assert "ValueError: Artifact" in replay.stderr
    elif consumer == "derived-input":
        with pytest.raises(ValueError, match="Artifact"):
            derived_artifacts._retained(root, [analysis])
    else:
        # Resume rejects any symlink in the snapshot, even one not in the manifest.
        if case != "symlink-parent":
            (folder / "linked").unlink()
        with pytest.raises(ValueError, match="[Aa]rtifact|symlink"):
            resume.prepare(root, tmp_path / "resumed", "Trend", strategy)


def test_requirements_include_only_identified_replay_dependencies(tmp_path, monkeypatch):
    from sci_search.data_research import artifacts, execution

    attempt = tmp_path / "source-1/python/attempt-1"
    attempt.mkdir(parents=True)
    (attempt / "script.py").write_text(
        "import json\nimport replaylib\nimport unknownlib\n__import__('dynamiclib')\n"
    )
    inventory = {"Replay-Lib": "1.2", "Unrelated-Server": "4.5"}
    monkeypatch.setattr(execution, "runtime", lambda: {"dependencies": inventory})
    monkeypatch.setattr(
        execution.importlib.metadata,
        "packages_distributions",
        lambda: {"replaylib": ["Replay-Lib"]},
    )
    artifacts.write_replay(tmp_path)
    assert (tmp_path / "requirements.txt").read_text() == "Replay-Lib==1.2\n"
    environment = json.loads((tmp_path / "environment.json").read_text())
    assert environment["dependencies"] == inventory
    assert environment["replay"]["unresolved_imports"] == ["unknownlib"]
    assert environment["replay"]["dynamic_imports"]


@pytest.mark.parametrize("consumer", ["replay", "resume"])
@pytest.mark.parametrize("case", ["escape", "missing", "hash", "symlink-parent"])
def test_derived_seal_validation_uses_same_boundary(tmp_path, consumer, case):
    from sci_search.data_research import artifacts, resume
    from sci_search.data_research.strategy import validate_strategy

    root = tmp_path / "run"
    root.mkdir()
    derived = root / "derived-1"
    derived.mkdir()
    (root / "outside").write_bytes(b"sealed")
    (derived / "data").write_bytes(b"sealed")
    name = "data"
    checksum = hashlib.sha256(b"sealed").hexdigest()
    if case == "escape":
        name = "../outside"
    elif case == "missing":
        name = "missing"
    elif case == "hash":
        checksum = "0" * 64
    else:
        (derived / "linked").symlink_to(root, target_is_directory=True)
        name = "linked/outside"
    strategy = validate_strategy(
        dict(
            route="data",
            rationale="Trend",
            geography="Netherlands",
            measurements=["population"],
            start_year=2020,
            end_year=2021,
        )
    )
    state = {
        "kind": "discovered",
        "question": "Trend",
        "strategy": strategy,
        "analyses": [],
        "assessments": [],
        "derived_outputs": {
            "execution": {
                "status": "verified",
                "directory": "derived-1",
                "artifacts": {name: checksum},
            }
        },
    }
    (root / "analysis.json").write_text(json.dumps(state))
    if consumer == "replay":
        artifacts.write_replay(root)
        replay = subprocess.run(
            [sys.executable, "-S", "reproduce.py"], cwd=root, capture_output=True, text=True
        )
        assert replay.returncode != 0
        assert "ValueError: Artifact" in replay.stderr
    else:
        with pytest.raises(ValueError, match="[Aa]rtifact|symlink"):
            resume.prepare(root, tmp_path / "resumed", "Trend", strategy)


def test_duplicate_distribution_providers_are_one_dependency(tmp_path, monkeypatch):
    from sci_search.data_research import execution

    (tmp_path / "script.py").write_text("import replaylib\n")
    monkeypatch.setattr(
        execution.importlib.metadata,
        "packages_distributions",
        lambda: {"replaylib": ["Replay_Lib", "replay-lib", "Replay_Lib"]},
    )
    report = execution.replay_dependencies(tmp_path, {"dependencies": {"Replay-Lib": "1.2"}})
    assert report["dependencies"] == {"Replay-Lib": "1.2"}
    assert report["unresolved_imports"] == []


def test_retained_helper_dependencies_are_included(tmp_path, monkeypatch):
    from sci_search.data_research import execution

    (tmp_path / "script.py").write_text("from helper import extract\n")
    incoming = tmp_path / "input"
    incoming.mkdir()
    (incoming / "helper.py").write_text("import replaylib\nfrom nested import transform\n")
    (incoming / "nested.py").write_text("import unknownlib\n")
    monkeypatch.setattr(
        execution.importlib.metadata,
        "packages_distributions",
        lambda: {"replaylib": ["Replay-Lib"]},
    )
    report = execution.replay_dependencies(tmp_path, {"dependencies": {"Replay-Lib": "1.2"}})
    assert report["dependencies"] == {"Replay-Lib": "1.2"}
    assert report["unresolved_imports"] == ["unknownlib"]


@pytest.mark.parametrize(
    "expression",
    ["pd.read_excel('source.xlsx')", "pd.ExcelFile('source.xlsx')", "read_excel('source.xlsx')"],
)
def test_pandas_excel_optional_engines_are_recorded(tmp_path, monkeypatch, expression):
    from sci_search.data_research import execution

    (tmp_path / "script.py").write_text(
        "import pandas as pd\nfrom pandas import read_excel\n" + expression + "\n"
    )
    monkeypatch.setattr(
        execution.importlib.metadata, "packages_distributions", lambda: {"pandas": ["pandas"]}
    )
    inventory = {"pandas": "2.3", "openpyxl": "3.1", "Unrelated-Server": "4.5"}
    report = execution.replay_dependencies(tmp_path, {"dependencies": inventory})
    assert report["dependencies"] == {"openpyxl": "3.1", "pandas": "2.3"}
    assert "pandas Excel engine: xlrd" in report["unresolved_imports"]
    assert "pandas Excel engine: openpyxl" not in report["unresolved_imports"]
