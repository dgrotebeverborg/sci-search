"""Project-scoped extraction recipes. Cached code is never cached scientific approval."""

import json
import os
import tempfile
from pathlib import Path

from sci_search.data_research.execution import digest


def recipe_key(body, scope, metadata, runtime):
    engines = {
        name: digest(Path(__file__).with_name(name).read_bytes())
        for name in (
            "python_rows.py",
            "tabular.py",
            "semantics.py",
            "verification.py",
            "python_recovery.py",
        )
    }
    return digest(
        json.dumps(
            {
                "version": 1,
                "source": digest(body),
                "scope": scope,
                "metadata": digest(metadata.encode()),
                "runtime": runtime,
                "engines": engines,
            },
            sort_keys=True,
        ).encode()
    )


def load(directory, key):
    if directory is None:
        return None
    path = Path(directory) / (key + ".json")
    try:
        if path.is_symlink() or path.stat().st_size > 110000:
            return None
        record = json.loads(path.read_text())
        code = record["code"]
        if (
            isinstance(code, str)
            and len(code.encode()) <= 100000
            and digest(code.encode()) == record["code_sha256"]
        ):
            return code
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save(directory, key, code):
    if directory is None:
        return
    directory = Path(directory)
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(
                {
                    "code": code,
                    "code_sha256": digest(code.encode()),
                    "qualification": "Recipe only; execute and review again before publication.",
                },
                stream,
            )
        os.replace(temporary, directory / (key + ".json"))
    except OSError:
        pass  # Optional reuse must not prevent publication of a freshly validated result.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
