"""Minimal local configuration loading without leaking secrets into artifacts."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(
    path: Path,
    *,
    override: bool = False,
    allowed_keys: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Load simple KEY=VALUE entries and return the names that were configured."""
    if not path.is_file():
        return ()
    configured: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            continue
        if allowed_keys is not None and key not in allowed_keys:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
        configured.append(key)
    return tuple(configured)


def load_legacy_mistral_key(project_directory: Path = Path(".")) -> bool:
    """Import only Mistral's key from the sibling sci-graph project when needed."""
    if os.environ.get("MISTRAL_API_KEY", "").strip():
        return False
    legacy_env = project_directory.resolve().parent / "sci-graph" / ".env.local"
    configured = load_env_file(legacy_env, allowed_keys=frozenset({"MISTRAL_API_KEY"}))
    return "MISTRAL_API_KEY" in configured and bool(os.environ.get("MISTRAL_API_KEY", "").strip())


def require_openalex_key() -> str:
    value = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not value:
        raise ValueError("OPENALEX_API_KEY is required for online literature discovery")
    return value
