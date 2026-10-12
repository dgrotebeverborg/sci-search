import json

import pytest

from sci_search.data_research import execution


def test_real_script_reads_only_inputs_and_retains_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TEST_TOKEN", "must-not-inherit")
    secret = tmp_path / "private.txt"
    secret.write_text("private")
    result = execution.run_python(
        "import os, json, socket\nfrom pathlib import Path\n"
        'assert "SECRET_TEST_TOKEN" not in os.environ\n'
        "try: child=os.fork()\n"
        "except OSError: pass\n"
        "else:\n"
        " if child==0: os._exit(0)\n"
        " os.waitpid(child,0)\n"
        ' raise AssertionError("child processes allowed")\n'
        'for name in ("/extra", "/dev/shm/extra"):\n'
        ' try: Path(name).write_text("bad")\n'
        " except OSError: pass\n"
        ' else: raise AssertionError("unbounded writable filesystem")\n'
        f"assert not Path({str(secret)!r}).exists()\n"
        'try:\n socket.create_connection(("1.1.1.1", 443), timeout=.2)\n'
        'except OSError: pass\nelse: raise AssertionError("network available")\n'
        'try:\n Path("/input/raw.txt").write_text("changed")\n'
        'except OSError: pass\nelse: raise AssertionError("input writable")\n'
        'Path("/output/result.json").write_text(json.dumps({"value":int(Path("/input/raw.txt").read_text())*2}))\n',
        {"raw.txt": b"21"},
        tmp_path / "attempt",
    )
    assert result["status"] == "succeeded", result
    assert json.loads((tmp_path / "attempt/output/result.json").read_text()) == {"value": 42}
    assert (tmp_path / "attempt/script.py").exists()
    assert result["script_sha256"]
    assert result["runtime"]["python"]


def test_timeout_stops_code_and_records_failure(tmp_path):
    result = execution.run_python("while True: pass", {}, tmp_path / "attempt", timeout=0.3)
    assert result["status"] == "failed"
    assert "time" in result["error"].lower()


def test_cancellation_stops_running_script(tmp_path):
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks > 2:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        execution.run_python("while True: pass", {}, tmp_path / "attempt", check_cancelled=cancel)
    assert json.loads((tmp_path / "attempt/execution.json").read_text())["status"] == "cancelled"


def test_missing_isolation_never_executes_host_code(tmp_path, monkeypatch):
    monkeypatch.setattr(execution.shutil, "which", lambda name: None)
    marker = tmp_path / "executed"
    result = execution.run_python(
        f'open({str(marker)!r}, "w").write("bad")', {}, tmp_path / "attempt"
    )
    assert result["status"] == "failed"
    assert "isolation" in result["error"].lower()
    assert not marker.exists()


def test_output_symlinks_are_not_read(tmp_path):
    result = execution.run_python(
        'import os\nos.symlink("/input/raw.txt", "/output/result.json")',
        {"raw.txt": b"{}"},
        tmp_path / "attempt",
    )
    assert result["status"] == "failed"
    assert "symlink" in result["error"].lower()


def test_input_paths_cannot_escape(tmp_path):
    with pytest.raises(ValueError, match="name"):
        execution.run_python("pass", {"../outside": b"x"}, tmp_path / "attempt")
    assert not (tmp_path / "outside").exists()


def test_many_output_files_are_stopped_during_execution(tmp_path):
    result = execution.run_python(
        'from pathlib import Path\nfor i in range(110): Path(f"/output/{i}").write_text("x")\nwhile True: pass',
        {},
        tmp_path / "attempt",
        timeout=5,
    )
    assert result["status"] == "failed"
    assert "output" in result["error"].lower()
    assert result["elapsed_seconds"] < 5


def test_temporary_files_have_a_total_storage_limit(tmp_path):
    result = execution.run_python(
        "from pathlib import Path\n"
        'for i in range(5): Path(f"/tmp/{i}").write_bytes(b"x"*15000000)\n',
        {},
        tmp_path / "attempt",
    )
    assert result["status"] == "failed"
    assert "No space left" in result["error"]
