# sci_search/data_research/connectors/base.py
"""Shared connector types and checks. Connectors never request model-supplied URLs."""

import hashlib
import os
import re
import tempfile
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


# Common English and Dutch words that say nothing about a dataset.
STOP_WORDS = frozenset(
    "and the for with from per all its their into over "
    "van het een naar voor met bij door uit".split()
)


def _words(text):
    return [w for w in re.findall(r"\w+", text.casefold()) if len(w) >= 3 and w not in STOP_WORDS]


def _matches(word, title_words):
    """Whole-word match. A word of 5 or more characters also matches a title word that starts
    or ends with it (a Dutch compound puts its head last: "opslag" in "batterijopslag"), or an
    inflected form sharing all but its last two characters ("expectancy", "expectancies")."""
    if word in title_words:
        return True
    if len(word) < 5:
        return False
    for other in title_words:
        if other.startswith(word) or other.endswith(word):
            return True
        if len(other) < 5:
            continue
        shared = len(os.path.commonprefix([word, other]))
        if shared >= max(5, min(len(word), len(other)) - 2):
            return True
    return False


def score(title, terms):
    title_words = set(_words(title))
    phrase = " ".join(_words(title))
    total = 0
    for term in terms:
        words = _words(term)
        if not words:
            continue
        if f" {' '.join(words)} " in f" {phrase} ":
            total += 3
        total += sum(1 for w in words if _matches(w, title_words))
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
    try:
        body = path.read_bytes()
        stored = digest_path.read_text().strip()
        if body and hashlib.sha256(body).hexdigest() == stored:
            return body, stored
    except (OSError, UnicodeDecodeError):
        pass
    body, _, _ = fetch(url)
    digest = hashlib.sha256(body).hexdigest()
    try:
        # Runs can share the cache: readers see a whole old file or a whole new one.
        _replace_atomically(path, body)
        _replace_atomically(digest_path, digest.encode())
    except OSError:
        pass  # an unwritable cache must not fail a successful fetch
    return body, digest


def _replace_atomically(path, contents):
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(contents)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
