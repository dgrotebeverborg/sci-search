"""Execute untrusted extraction code in a fresh, networkless Linux namespace."""

import ast
import hashlib
import importlib.metadata
import json
import os
import re
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


def replay_dependencies(directory, environment):
    """Identify bounded static replay dependencies and retain import uncertainty.

    Inspect retained scripts and their copied Python helpers, never installed
    library source. Pip resolves distribution dependencies. Known pandas Excel
    engines are optional extras, so retain installed engines explicitly.
    """
    installed = environment["dependencies"]
    providers = importlib.metadata.packages_distributions()
    dependencies, unresolved, dynamic = {}, set(), set()

    def canonical(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    inventory = {canonical(name): name for name in installed}

    def pin(name):
        retained = inventory.get(canonical(name))
        if retained is None:
            return False
        dependencies[retained] = installed[retained]
        return True

    # pandas documents these optional readers; pip installing pandas alone does
    # not install them: https://pandas.pydata.org/docs/reference/api/pandas.read_excel.html
    excel_engines = {
        "openpyxl": "openpyxl",
        "xlrd": "xlrd",
        "pyxlsb": "pyxlsb",
        "odf": "odfpy",
        "calamine": "python-calamine",
    }
    for script in sorted(Path(directory).rglob("script.py")):
        copied = set((script.parent / "input").glob("*.py"))
        copied.update(script.parent.glob("*.py"))
        local = {p.stem for p in copied}
        for helper in sorted(copied):
            if helper.is_symlink():
                dynamic.add(str(helper.relative_to(directory)) + ": symlink was not inspected")
                continue
            label = str(helper.relative_to(directory))
            try:
                tree = ast.parse(helper.read_text())
            except (OSError, SyntaxError, UnicodeError):
                dynamic.add(label + ": imports could not be inspected")
                continue
            modules, pandas_aliases, excel_aliases = set(), set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                    pandas_aliases.update(
                        alias.asname or alias.name for alias in node.names if alias.name == "pandas"
                    )
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules.add(node.module.split(".")[0])
                    if node.module == "pandas":
                        excel_aliases.update(
                            alias.asname or alias.name
                            for alias in node.names
                            if alias.name in {"read_excel", "ExcelFile"}
                        )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "__import__"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                ):
                    dynamic.add(label + ": dynamic import")
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id in excel_aliases
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"read_excel", "ExcelFile"}
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in pandas_aliases
                ):
                    for engine, distribution in excel_engines.items():
                        if not pin(distribution):
                            unresolved.add("pandas Excel engine: " + engine)
            for module in modules - sys.stdlib_module_names - local:
                names = {canonical(name) for name in providers.get(module, [])}
                if len(names) != 1 or not pin(next(iter(names))):
                    unresolved.add(module)
    return {
        "dependencies": dict(sorted(dependencies.items())),
        "unresolved_imports": sorted(unresolved),
        "dynamic_imports": sorted(dynamic),
        "scope": "Static imports in retained scripts and copied Python helpers, plus installed "
        "documented pandas Excel engines; pip resolves transitive dependencies. "
        "Missing optional Excel engines are reported conservatively. Dynamic and other "
        "indirect library imports may need additional packages.",
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
        # Managed interpreters (including GitHub's toolcache) can live outside /usr.
        # Expose only their installation, read-only, after the temporary mounts.
        installation = Path(sys.base_prefix).resolve()
        if not any(installation.is_relative_to(path) for path in ("/usr", "/lib", "/lib64")):
            position = command.index("--remount-ro")
            command[position:position] = ["--ro-bind", str(installation), str(installation)]
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
