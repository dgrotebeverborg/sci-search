"""Execute untrusted extraction code in a fresh, networkless Linux namespace."""

import hashlib
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

OUTPUT_LIMIT = 16_000_000
BOOTSTRAP = """import resource, runpy, sys
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
resource.setrlimit(resource.RLIMIT_AS, (1536*1024*1024, 1536*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (16000000, 16000000))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
sys.path.insert(0, "/deps")
sys.path.insert(0, "/input")
runpy.run_path("/script.py", run_name="__main__")
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runtime():
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "dependencies": dict(
            sorted(
                (d.metadata["Name"], d.version)
                for d in importlib.metadata.distributions()
                if "Name" in d.metadata
            )
        ),
    }


def run_python(code, inputs, directory, *, timeout=45, check_cancelled=lambda: None):
    """Retain all attempts. Missing/failed isolation is a failure, never a host fallback."""
    if not isinstance(code, str) or len(code.encode()) > 100_000:
        raise ValueError("Python script exceeds size limit")
    for name, body in inputs.items():
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Invalid input name")
        if not isinstance(body, bytes):
            raise ValueError("Input must contain bytes")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    incoming, outgoing = directory / "input", directory / "output"
    incoming.mkdir()
    outgoing.mkdir()
    for name, body in inputs.items():
        (incoming / name).write_bytes(body)
    (directory / "script.py").write_text(code)
    (directory / "bootstrap.py").write_text(BOOTSTRAP)
    record = {
        "status": "failed",
        "script_sha256": digest(code.encode()),
        "inputs": {name: digest(body) for name, body in inputs.items()},
        "runtime": runtime(),
        "isolation": "bubblewrap-unshare-all-v1",
    }
    started = time.monotonic()
    process = None
    try:
        check_cancelled()
        binary = shutil.which("bwrap")
        if not binary or sys.platform != "linux" or os.geteuid() == 0:
            raise ValueError(
                "Python isolation unavailable: Linux bubblewrap and a non-root account are required"
            )
        command = [
            binary,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
        ]
        for path in ("/usr", "/lib", "/lib64"):
            if Path(path).exists():
                command += ["--ro-bind", path, path]
        command += [
            "--symlink",
            "usr/bin",
            "/bin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            "67108864",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            sysconfig.get_path("purelib"),
            "/deps",
            "--ro-bind",
            str(incoming),
            "/input",
            "--bind",
            str(outgoing),
            "/output",
            "--ro-bind",
            str(directory / "script.py"),
            "/script.py",
            "--ro-bind",
            str(directory / "bootstrap.py"),
            "/bootstrap.py",
            "--chdir",
            "/output",
            "--remount-ro",
            "/",
            "--remount-ro",
            "/dev",
            "--remount-ro",
            "/proc",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--setenv",
            "OPENBLAS_NUM_THREADS",
            "1",
            "--setenv",
            "OMP_NUM_THREADS",
            "1",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            str(Path(sys.executable).resolve()),
            "-I",
            "-B",
            "/bootstrap.py",
        ]
        with (
            (directory / "stdout.txt").open("wb") as stdout,
            (directory / "stderr.txt").open("wb") as stderr,
        ):
            process = subprocess.Popen(
                command, stdout=stdout, stderr=stderr, env={}, start_new_session=True
            )
            while process.poll() is None:
                check_cancelled()
                if time.monotonic() - started > timeout:
                    raise ValueError("Python execution time limit exceeded")
                size, count = 0, 0
                for path in outgoing.rglob("*"):
                    count += 1
                    if path.is_symlink():
                        raise ValueError("Invalid Python output: symlink")
                    size += path.lstat().st_size
                    if count > 100 or size > OUTPUT_LIMIT:
                        raise ValueError("Python output exceeds file-count or size limit")
                time.sleep(0.05)
        record["returncode"] = process.returncode
        if process.returncode:
            error = (directory / "stderr.txt").read_bytes()[-5000:].decode(errors="replace")
            raise ValueError("Isolated Python failed: " + error)
        outputs = list(outgoing.rglob("*"))
        if len(outputs) > 100 or any(
            p.is_symlink() or not (p.is_file() or p.is_dir()) for p in outputs
        ):
            raise ValueError("Invalid Python output: symlinks, special files or too many files")
        if sum(p.stat().st_size for p in outputs if p.is_file()) > OUTPUT_LIMIT:
            raise ValueError("Python output exceeds size limit")
        record.update(
            status="succeeded",
            outputs={
                str(p.relative_to(outgoing)): digest(p.read_bytes()) for p in outputs if p.is_file()
            },
        )
    except (OSError, ValueError) as exc:
        record["error"] = str(exc)[:6000]
    except BaseException:
        record.update(status="cancelled", error="Execution interrupted")
        raise
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (directory / "execution.json").write_text(json.dumps(record, indent=2))
    return record
