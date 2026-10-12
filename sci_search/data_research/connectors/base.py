# sci_search/data_research/connectors/base.py
"""Shared connector types and checks. Connectors never request model-supplied URLs."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sci_search.data_research.tabular import read_csv


class SelectionError(ValueError):
    def __init__(self, message, facts=None):
        super().__init__(message)
        self.facts = facts or {}


class ReaderError(ValueError):
    pass


class DatasetRejected(ValueError):
    pass


@dataclass(frozen=True)
class DatasetCandidate:
    connector: str
    dataset: str
    title: str
    frequency: str
    first_period: str = ""
    last_period: str = ""
    landing_url: str = ""


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    codes: dict


@dataclass(frozen=True)
class DatasetDescription:
    candidate: DatasetCandidate
    dimensions: tuple
    years: tuple
    licence_url: str
    definitions: str
    publisher: str
    payload: bytes = b""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Fetched:
    raw: bytes
    request: dict
    selection: dict | None
    artifact: str
    notes: tuple = ()


def annual(code):
    match = re.fullmatch(r"\s*((?:18|19|20|21)\d{2})(?:JJ00)?\s*", code)
    return int(match[1]) if match else None


def score(title, terms):
    text = title.casefold()
    total = 0
    for term in terms:
        words = [w for w in re.findall(r"\w+", term.casefold()) if len(w) > 2]
        if term.casefold() in text:
            total += 3
        total += sum(1 for w in words if w in text)
    return total


def validate_selection(description, selection, *, max_entities=60):
    dims = {d.id: d for d in description.dimensions}
    filters = selection.get("filters") or {}
    if set(filters) != set(dims):
        raise SelectionError(
            "Selection must give codes for every dimension",
            {"dimensions": sorted(dims)},
        )
    valid = {d: sorted(dims[d].codes) for d in dims}
    for d, codes in filters.items():
        if not codes or len(set(codes)) != len(codes) or not set(codes) <= set(dims[d].codes):
            raise SelectionError(
                f"Selection contains unobserved or duplicate codes for {d}",
                {"valid_codes": valid},
            )
    series = selection.get("series_dimensions") or []
    if len(set(series)) != len(series) or not set(series) <= set(dims):
        raise SelectionError(
            "Series dimensions must be observed dimensions", {"dimensions": sorted(dims)}
        )
    for d, codes in filters.items():
        if d not in series and len(codes) != 1:
            raise SelectionError(
                f"Dimension {d} is not a series dimension and needs exactly one code",
                {"valid_codes": valid},
            )
    combinations = 1
    for d in series:
        combinations *= len(filters[d])
    if combinations > max_entities:
        raise SelectionError(f"Selection exceeds {max_entities} series; narrow the codes")
    return {
        "filters": {d: list(codes) for d, codes in filters.items()},
        "series_dimensions": list(series),
        "reason": str(selection.get("reason", ""))[:1000],
    }


def series_mapping(table, label):
    _, rows = read_csv(table)
    units = {r["Unit"] for r in rows}
    if len(units) != 1:
        raise SelectionError("Select one unit; the slice contains " + ", ".join(sorted(units)))
    unit = units.pop()
    return dict(
        year_column="Year",
        value_column="Value",
        entity_column="Series",
        entities=list(dict.fromkeys(r["Series"] for r in rows)),
        unit=unit,
        output_unit=unit,
        label=label,
        filters=[],
        missing_values=[":"],
        decimal_separator=".",
    )


def catalogue(name, url, fetch, cache_dir, today: date | None = None):
    today = today or datetime.now(UTC).date()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{name}-{today.isoformat()}.bin"
    digest_path = path.with_suffix(".sha256")
    if path.exists() and digest_path.exists():
        body = path.read_bytes()
        if body and hashlib.sha256(body).hexdigest() == digest_path.read_text().strip():
            return body, digest_path.read_text().strip()
    body, _, _ = fetch(url)
    digest = hashlib.sha256(body).hexdigest()
    path.write_bytes(body)
    digest_path.write_text(digest)
    return body, digest
