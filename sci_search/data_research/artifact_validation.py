"""Portable validation of retained artifacts; safe to copy into offline bundles."""

import hashlib
from collections.abc import Mapping
from pathlib import Path


def validate_artifacts(root, artifacts):
    """Raise ValueError for unsealed, missing, changed or unsafe retained files."""
    root = Path(root).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("Artifact root contains a symlink")
    if not root.is_dir() or not isinstance(artifacts, Mapping) or not artifacts:
        raise ValueError("Artifact manifest or root is missing")
    for name, expected in artifacts.items():
        if not isinstance(name, str) or not name or "\\" in name:
            raise ValueError(f"Artifact path is invalid: {name!r}")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise ValueError(f"Artifact path is invalid: {name}")
        path = root / relative
        if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
            raise ValueError(f"Artifact path contains a symlink: {name}")
        try:
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(f"Artifact file is missing or invalid: {name}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f"Artifact file cannot be read: {name}") from exc
        if actual != expected:
            raise ValueError(f"Artifact hash mismatch: {name}")
