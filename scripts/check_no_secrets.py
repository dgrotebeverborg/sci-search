#!/usr/bin/env python3
"""Reject committed credentials without printing their values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

SECRET_VARIABLES = (
    "MISTRAL_API_KEY",
    "OPENALEX_API_KEY",
    "SESSION_SECRET",
    "OIDC_CLIENT_SECRET",
    "POSTGRES_PASSWORD",
    "MINIO_ROOT_PASSWORD",
)
_ASSIGNMENT = re.compile(
    rf"(?m)^[ \t]*(?:export[ \t]+)?(?P<name>{'|'.join(SECRET_VARIABLES)})"
    r"[ \t]*=[ \t]*(?P<value>[^\r\n#]+)"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_TEXT_SUFFIXES = frozenset(
    {".cfg", ".env", ".ini", ".json", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
)
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "data",
        "dist",
        "superpowers",
    }
)
_EXCLUDED_PATHS = frozenset(
    {
        Path("tests/contracts/test_no_secrets.py"),
    }
)
_EXCLUDED_NAMES = frozenset({".env.local"})


def scan_text(text: str) -> list[str]:
    """Return secret labels found in text; never return captured values."""

    findings = [
        match.group("name")
        for match in _ASSIGNMENT.finditer(text)
        if _has_value(match.group("value"))
    ]
    if _PRIVATE_KEY.search(text):
        findings.append("PRIVATE_KEY")
    return list(dict.fromkeys(findings))


def scan_files(paths: Iterable[Path], root: Path) -> list[tuple[Path, str]]:
    findings: list[tuple[Path, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        display_path = _relative_to(path, root)
        findings.extend((display_path, label) for label in scan_text(text))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    root = Path.cwd().resolve()
    requested = tuple(Path(value).resolve() for value in (argv or ()))
    paths = requested or tuple(_tracked_text_files(root))
    findings = scan_files(paths, root)
    for path, label in findings:
        print(f"{path}: possible {label}")
    return 1 if findings else 0


def _tracked_text_files(root: Path) -> Iterable[Path]:
    tracked = _git_tracked_files(root)
    candidates = tracked if tracked is not None else root.rglob("*")
    for path in candidates:
        relative = _relative_to(path, root)
        if (
            relative in _EXCLUDED_PATHS
            or path.name in _EXCLUDED_NAMES
            or any(part in _EXCLUDED_PARTS for part in relative.parts)
        ):
            continue
        if path.is_file() and (
            path.suffix.lower() in _TEXT_SUFFIXES or path.name.startswith(".env")
        ):
            yield path


def _git_tracked_files(root: Path) -> tuple[Path, ...] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return tuple(root / name.decode("utf-8") for name in result.stdout.split(b"\0") if name)


def _has_value(raw: str) -> bool:
    return bool(raw.strip().strip("'\""))


def _relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


if __name__ == "__main__":
    raise SystemExit(main())
