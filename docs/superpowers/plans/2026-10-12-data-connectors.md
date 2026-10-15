# Statistical Data Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let data research find and read official statistics through the Eurostat, CBS, PxWeb and Our World in Data APIs, with automatic recovery, before falling back to web search and scraping.

**Architecture:** A `sci_search/data_research/connectors/` package holds the network side of each connector (search, describe, fetch). The raw API response is stored as the source artifact and read by a pure reader registered in `packages.prepare_table`, so the existing sandbox calculation (`artifacts.execute_analysis`) reproduces every published value. A connector stage in `connectors/stage.py` runs at the start of `workflow.execute`; measurements it does not cover continue to the existing web-search path.

**Tech Stack:** Python 3.11+ standard library only (`http.client`, `xml.etree`, `json`, `csv`), pytest, Playwright for the browser test. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-data-connectors-design.md`

## Global Constraints

- Only annual data is analysed. Other frequencies are rejected with "dataset is <frequency>; no aggregation was performed".
- Recovery never relaxes a check: a wrong unit, an unobserved code or a non-annual series is never accepted on a later attempt.
- Every value traces to a stored raw response with its SHA-256; the sandbox calculation must reproduce the analysis exactly.
- A connector never requests a URL supplied by the model. Each connector has a fixed host set; dataset IDs are matched against a per-connector pattern.
- All traffic goes through `retrieval.fetch_public` or the new `retrieval.post_public` (public addresses, DNS pinning, redirect validation). No credentials are sent.
- Limits: 5 MB per raw response; 60 entities per selection; 50,000 rows (existing); 2 selection repairs per dataset; 1 extra search round per measurement; 1 retry on timeout or HTTP 5xx.
- Missing values stay missing, never zero. Source status flags (Eurostat `p`, `e`; CBS provisional) are kept in the Status column.
- `SCI_SEARCH_DATA_CONNECTORS` (default on; `0`, `false` or `no` disables) controls the connector stage.
- Tests run offline. Network access only in the opt-in `--run-live-data` acceptance test and the fixture recorder script.
- Run tests with `uv run python -m pytest` (plain `pytest` cannot import `scripts`).

## Review Focus

- A requested country with no published data in the chosen dataset (e.g. Eurostat has no series for `AL`) should give a partial result that names the missing country, not fail the dataset. Test in Task 6.
- Eurostat uses `EL` for Greece and `UK` for the United Kingdom; `strategy["countries"]` uses ISO-3 (`GRC`, `GBR`). A Greece question must select `EL`. Test in Task 6.
- A selection whose series carry different units (two measures in one slice) should be rejected before analysis with "Select one unit", never summed or mixed. Test in Task 2.
- A catalogue cache file from an earlier day, or a corrupt one, should be refetched, never searched. Test in Task 2.
- Searches that return no candidates for every term should trigger one reformulated search round and then hand the measurement to web search with a recorded reason. Test in Task 11.

## File Structure

| File | Responsibility |
|---|---|
| `sci_search/data_research/retrieval.py` (modify) | add `post_public` beside `fetch_public` |
| `sci_search/data_research/connectors/__init__.py` (create) | registry: `CONNECTORS`, `enabled()` |
| `sci_search/data_research/connectors/base.py` (create) | dataclasses, errors, selection validation, catalogue cache, `series_mapping`, `dataset_from_url` |
| `sci_search/data_research/jsonstat.py` (create) | pure annual JSON-stat 2 reader (sandbox engine) |
| `sci_search/data_research/owid_tables.py` (create) | pure OWID grapher CSV reader (sandbox engine) |
| `sci_search/data_research/packages.py` (modify) | dispatch `jsonstat2` and `owid_csv` readers |
| `sci_search/data_research/artifacts.py` (modify) | add the two engines to `ENGINES` |
| `sci_search/data_research/connectors/eurostat.py` (create) | Eurostat SDMX connector |
| `sci_search/data_research/connectors/cbs.py` (create) | CBS connector |
| `sci_search/data_research/connectors/pxweb.py` (create) | PxWeb connector |
| `sci_search/data_research/connectors/owid.py` (create) | Our World in Data connector |
| `sci_search/data_research/connectors/stage.py` (create) | connector stage: terms, choice, selection, analysis, recovery |
| `sci_search/data_research/workflow.py` (modify) | call the stage, hand off, reroute, record connector gaps |
| `sci_search/frontend/static/data_research.js` (modify) | show connector provenance and gaps |
| `sci_search/data_research/reporting.py` (modify) | include connector gaps in the report appendix |
| `scripts/record_connector_fixtures.py` (create) | records real API responses as test fixtures |
| `tests/fixtures/data_research/connectors/` (create) | recorded responses |
| `tests/test_connector_*.py`, `tests/test_post_public.py` (create) | offline tests |
| `tests/live/test_data_connectors_live.py` (create) | opt-in acceptance run |

---

### Task 1: POST fetcher and spec refinements

**Files:**
- Modify: `sci_search/data_research/retrieval.py:38-80`
- Modify: `docs/superpowers/specs/2026-10-12-data-connectors-design.md`
- Test: `tests/test_post_public.py`

**Interfaces:**
- Produces: `post_public(url: str, payload: dict, *, limit: int = 5_000_000) -> tuple[bytes, str, str]` returning `(body, content_type, final_url)`. Same validation as `fetch_public`. Redirects are not followed for POST (a redirect raises `ValueError("POST redirect refused")`).
- Produces: `fetch_public` unchanged in behaviour; both share `_request(method, url, body, limit, follow)`.

- [ ] **Step 1: Amend the spec to match what the APIs and sandbox allow**

In `docs/superpowers/specs/2026-10-12-data-connectors-design.md`:
- In "API behaviour probed", add: "Eurostat answers `availableconstraint` with HTTP 405. `data/<id>/<key>/?format=TSV&detail=serieskeysonly` lists the existing series keys (2,990 bytes for `demo_mlexpec`, annual, age `Y_LT1`)."
- In "Data flow" step 3, replace "(Eurostat and CBS availability queries)" with "(Eurostat series-keys-only query; CBS, PxWeb and OWID metadata list only observed codes)".
- In "Components", replace the paragraph starting "`normalize` is a pure function registered" with: "The sandbox accepts only flat file names, so readers are flat engine modules: Eurostat reuses `statistical_tables.prepare_statistics`, CBS reuses `packages._cbs`, and the new `jsonstat.py` (PxWeb) and `owid_tables.py` (OWID) are added to `artifacts.ENGINES`. Connectors in `connectors/` hold only the network side."
- Replace the "Moved into connectors" list with: "`packages._cbs`, `statistical_tables` and `retrieval.eurostat_download_url` stay where they are and are reused by the connectors; no parallel copy is made."
- CBS: in "Components" add "The CBS connector downloads the CSV package (`datasets.cbs.nl/CSV/CBS/nl/<id>`), which contains every code table; filtering happens in the column mapping."

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_post_public.py
import json

import pytest

from sci_search.data_research import retrieval


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status, self._body, self._headers = status, body, headers or {}

    def read(self, n):
        return self._body[:n]

    def getheader(self, name, default=None):
        return self._headers.get(name, default)


class FakeConnection:
    calls = []
    response = FakeResponse(200, b'{"ok": true}', {"Content-Type": "application/json"})

    def __init__(self, host, port, timeout):
        self.host = host

    def request(self, method, path, body=None, headers=None):
        FakeConnection.calls.append((method, self.host, path, body, headers))

    def getresponse(self):
        return FakeConnection.response

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    FakeConnection.calls = []
    FakeConnection.response = FakeResponse(200, b'{"ok": true}', {"Content-Type": "application/json"})
    monkeypatch.setattr(retrieval, "public_addresses", lambda url: ["203.0.113.5"])
    monkeypatch.setattr(retrieval.http.client, "HTTPSConnection", FakeConnection)
    return FakeConnection


def test_post_sends_json_body_to_validated_host(fake):
    body, content_type, url = retrieval.post_public(
        "https://data.ssb.no/api/v0/en/table/07459", {"query": [], "response": {"format": "json-stat2"}}
    )
    method, host, path, sent, headers = fake.calls[0]
    assert (method, host, path) == ("POST", "data.ssb.no", "/api/v0/en/table/07459")
    assert json.loads(sent) == {"query": [], "response": {"format": "json-stat2"}}
    assert headers["Content-Type"] == "application/json"
    assert body == b'{"ok": true}' and content_type == "application/json"


def test_post_refuses_redirects(fake):
    fake.response = FakeResponse(302, headers={"Location": "https://elsewhere.example/"})
    with pytest.raises(ValueError, match="POST redirect refused"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {})


def test_post_enforces_size_limits(fake):
    fake.response = FakeResponse(200, b"x" * 11)
    with pytest.raises(ValueError, match="acquisition limit"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {}, limit=10)
    with pytest.raises(ValueError, match="64 KB"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {"x": "y" * 70_000})


def test_post_rejects_private_targets(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_post_public.py -q`
Expected: FAIL with `AttributeError: module 'sci_search.data_research.retrieval' has no attribute 'post_public'`

- [ ] **Step 4: Implement `_request` and `post_public`**

Replace `fetch_public` in `sci_search/data_research/retrieval.py` with:

```python
def _request(method, url, body, limit, follow):
    for _ in range(5 if follow else 1):
        addresses = public_addresses(url)
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = cls(parts.hostname, port, timeout=35)
        # Connect to the validated address, retaining hostname for TLS/SNI verification.
        connection._create_connection = (
            lambda address, timeout, *args, addresses=addresses, port=port: (
                socket.create_connection((addresses[0], port), timeout)
            )
        )
        headers = {
            "User-Agent": "Sci-Search/0.2 (public research data)",
            "Accept-Encoding": "identity",
            "Accept": "*/*",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                if not follow:
                    raise ValueError("POST redirect refused")
                target = response.getheader("Location")
                if not target:
                    raise ValueError("Dataset redirect lacks a location")
                url = urljoin(url, target)
                continue
            if response.status != 200:
                raise ValueError(f"Dataset server returned HTTP {response.status}")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError(f"Dataset exceeds the {limit // 1_000_000} MB acquisition limit")
            return data, response.getheader("Content-Type", ""), url
        finally:
            connection.close()
    raise ValueError("Dataset exceeded the redirect limit")


def fetch_public(url, *, limit=50_000_000):
    return _request("GET", url, None, limit, True)


def post_public(url, payload, *, limit=5_000_000):
    """JSON POST for statistical APIs (PxWeb v1). Redirects are refused."""
    import json

    body = json.dumps(payload, separators=(",", ":")).encode()
    if len(body) > 64_000:
        raise ValueError("POST body exceeds the 64 KB limit")
    return _request("POST", url, body, limit, False)
```

Note the 5 MB acquisition-limit test uses `limit=10`, so the message reads "exceeds the 0 MB acquisition limit"; the regex matches "acquisition limit".

- [ ] **Step 5: Run the tests to verify they pass, plus the existing retrieval users**

Run: `uv run python -m pytest tests/test_post_public.py tests/test_autonomous_data.py tests/test_statistical_tables.py tests/test_download_navigation.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add sci_search/data_research/retrieval.py tests/test_post_public.py docs/superpowers/specs/2026-10-12-data-connectors-design.md
git commit -m "Add a bounded JSON POST fetcher for statistical APIs"
```

---

### Task 2: Connector base types, selection validation and catalogue cache

**Files:**
- Create: `sci_search/data_research/connectors/__init__.py`
- Create: `sci_search/data_research/connectors/base.py`
- Test: `tests/test_connector_base.py`

**Interfaces:**
- Produces (in `base.py`):
  - `class SelectionError(ValueError)` with attribute `facts: dict` (information a model needs to repair its selection).
  - `class ReaderError(ValueError)`: our reader could not read the response.
  - `class DatasetRejected(ValueError)`: the dataset is unsuitable (frequency, coverage).
  - `@dataclass(frozen=True) DatasetCandidate(connector: str, dataset: str, title: str, frequency: str, first_period: str = "", last_period: str = "", landing_url: str = "")`; `frequency` is one of `"annual"`, `"monthly"`, `"quarterly"`, `"other"`, `"unknown"`.
  - `@dataclass(frozen=True) Dimension(id: str, label: str, codes: dict[str, str])` (code to label).
  - `@dataclass(frozen=True) DatasetDescription(candidate: DatasetCandidate, dimensions: tuple[Dimension, ...], years: tuple[int, ...], licence_url: str, definitions: str, publisher: str, payload: bytes = b"", extra: dict = field(default_factory=dict))`. `dimensions` excludes the time dimension. `years` may be empty when coverage is only known after fetching. `payload` holds bytes already downloaded during `describe` (CBS, OWID).
  - `@dataclass(frozen=True) Fetched(raw: bytes, request: dict, selection: dict | None, artifact: str, notes: tuple[str, ...] = ())`. `selection` is passed to `packages.prepare_table`.
  - `validate_selection(description, selection, *, max_entities=60) -> dict` returning a normalised copy. `selection` shape: `{"filters": {dimension_id: [codes]}, "series_dimensions": [dimension_id], "reason": str}`.
  - `series_mapping(table: bytes, label: str) -> dict` for tables with columns `Year, Series, ..., Value, Unit, Status`.
  - `catalogue(name: str, url: str, fetch, cache_dir: Path, today: date | None = None) -> tuple[bytes, str]` returning `(body, sha256)`.
  - `score(title: str, terms: list[str]) -> int`.
  - `annual(code: str) -> int | None` (accepts `2024`, `2024 `, `2024JJ00`).
- Produces (in `__init__.py`): `enabled() -> bool`; `CONNECTORS: dict[str, module]` filled in Tasks 6 to 9; `dataset_from_url(url: str) -> tuple[str, str] | None` returning `(connector_name, dataset_id)` by asking each connector's `dataset_from_url`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_base.py
from datetime import date

import pytest

from sci_search.data_research.connectors import base


def description():
    return base.DatasetDescription(
        candidate=base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual"),
        dimensions=(
            base.Dimension("sex", "Sex", {"F": "Females", "M": "Males", "T": "Total"}),
            base.Dimension("geo", "Country", {"NL": "Netherlands", "DE": "Germany"}),
            base.Dimension("unit", "Unit", {"YR": "Year"}),
        ),
        years=(2000, 2024),
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        definitions="Life expectancy at birth",
        publisher="Eurostat",
    )


def selection(**updates):
    value = {
        "filters": {"sex": ["F", "M"], "geo": ["NL", "DE"], "unit": ["YR"]},
        "series_dimensions": ["sex", "geo"],
        "reason": "Requested",
    }
    return value | updates


def test_valid_selection_is_normalised():
    assert base.validate_selection(description(), selection())["filters"]["geo"] == ["NL", "DE"]


def test_unobserved_code_is_a_repairable_selection_error():
    with pytest.raises(base.SelectionError) as info:
        base.validate_selection(
            description(), selection(filters={"sex": ["X"], "geo": ["NL"], "unit": ["YR"]})
        )
    assert info.value.facts["valid_codes"]["sex"] == ["F", "M", "T"]


def test_every_dimension_needs_a_filter_and_fixed_dimensions_one_code():
    with pytest.raises(base.SelectionError, match="every dimension"):
        base.validate_selection(description(), selection(filters={"sex": ["F"], "geo": ["NL"]}))
    with pytest.raises(base.SelectionError, match="one code"):
        base.validate_selection(description(), selection(series_dimensions=["geo"]))


def test_entity_limit():
    many = base.DatasetDescription(
        **{
            **description().__dict__,
            "dimensions": (base.Dimension("geo", "Country", {f"C{i}": str(i) for i in range(61)}),),
        }
    )
    with pytest.raises(base.SelectionError, match="60"):
        base.validate_selection(
            many, {"filters": {"geo": [f"C{i}" for i in range(61)]}, "series_dimensions": ["geo"], "reason": ""}
        )


def test_series_mapping_requires_one_unit():
    table = b"Year,Series,Value,Unit,Status\n2000,a,1,YR,\n2001,a,2,YR,\n"
    mapping = base.series_mapping(table, "life expectancy")
    assert mapping["entities"] == ["a"] and mapping["unit"] == "YR"
    mixed = b"Year,Series,Value,Unit,Status\n2000,a,1,YR,\n2000,b,2,PC,\n"
    with pytest.raises(base.SelectionError, match="Select one unit"):
        base.series_mapping(mixed, "x")


def test_catalogue_cache_is_daily_and_refetches_corrupt_files(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return b"<catalogue/>", "application/xml", url

    body, digest = base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12))
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12))
    assert len(calls) == 1 and body == b"<catalogue/>" and len(digest) == 64
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 13))
    assert len(calls) == 2
    (tmp_path / "eurostat-2026-10-13.bin").write_bytes(b"")
    (tmp_path / "eurostat-2026-10-13.sha256").write_text("0" * 64)
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 13))
    assert len(calls) == 3


def test_annual_codes_and_scoring():
    assert [base.annual(c) for c in ("2024", "2024 ", "2024JJ00", "2024M01", "2024Q1")] == [2024, 2024, 2024, None, None]
    assert base.score("Life expectancy by age and sex", ["life expectancy", "sex"]) > base.score("Population", ["life expectancy"])


def test_connectors_can_be_disabled(monkeypatch):
    from sci_search.data_research import connectors

    monkeypatch.delenv("SCI_SEARCH_DATA_CONNECTORS", raising=False)
    assert connectors.enabled()
    for value in ("0", "false", "no"):
        monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", value)
        assert not connectors.enabled()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_base.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sci_search.data_research.connectors'`

- [ ] **Step 3: Implement `base.py`**

```python
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
        raise SelectionError("Series dimensions must be observed dimensions", {"dimensions": sorted(dims)})
    for d, codes in filters.items():
        if d not in series and len(codes) != 1:
            raise SelectionError(f"Dimension {d} is not a series dimension and needs exactly one code", {"valid_codes": valid})
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


def catalogue(name, url, fetch, cache_dir, today=None):
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
```

- [ ] **Step 4: Implement the registry**

```python
# sci_search/data_research/connectors/__init__.py
"""Statistical API connectors. Network side only; readers are flat sandbox engines."""

import os

CONNECTORS = {}


def enabled():
    return os.environ.get("SCI_SEARCH_DATA_CONNECTORS", "1").strip().lower() not in {"0", "false", "no"}


def dataset_from_url(url):
    for name, connector in CONNECTORS.items():
        dataset = connector.dataset_from_url(url)
        if dataset:
            return name, dataset
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_connector_base.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add sci_search/data_research/connectors tests/test_connector_base.py
git commit -m "Add connector types, selection validation and catalogue cache"
```

---

### Task 3: JSON-stat 2 reader

**Files:**
- Create: `sci_search/data_research/jsonstat.py`
- Modify: `sci_search/data_research/packages.py:17` (dispatch), `sci_search/data_research/artifacts.py:9-18` (`ENGINES`)
- Test: `tests/test_jsonstat.py`

**Interfaces:**
- Produces: `prepare_jsonstat(body: bytes, selection: dict) -> tuple[bytes, dict]`. `selection = {"reader": "jsonstat2", "series_dimensions": [ids], "code_labels": {dim: {code: label}}, "reason": str}`. Output columns: `Year, Series, <each non-time dimension id>, Value, Unit, Status`. Preparation dict: `format="jsonstat2_v1"`, `selection`, `row_provenance`, `normalized_sha256`, `checks`, `metadata`, `limitations`.
- `prepare_table(body, {"reader": "jsonstat2", ...})` dispatches to it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jsonstat.py
import json

import pytest

from sci_search.data_research.jsonstat import prepare_jsonstat
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv


def dataset(time_codes=("2020", "2021"), values=(1.5, None, 2.5, 3.0), units=None):
    return json.dumps(
        {
            "class": "dataset",
            "version": "2.0",
            "id": ["Region", "ContentsCode", "Tid"],
            "size": [2, 1, len(time_codes)],
            "role": {"time": ["Tid"], "metric": ["ContentsCode"]},
            "dimension": {
                "Region": {"label": "region", "category": {"index": {"SE1": 0, "SE2": 1}, "label": {"SE1": "North", "SE2": "South"}}},
                "ContentsCode": {
                    "label": "observations",
                    "category": {
                        "index": {"EL01": 0},
                        "label": {"EL01": "Electricity use"},
                        "unit": units or {"EL01": {"base": "GWh", "decimals": 1}},
                    },
                },
                "Tid": {"label": "year", "category": {"index": {c: i for i, c in enumerate(time_codes)}}},
            },
            "value": list(values),
            "status": {"3": "p"},
        }
    ).encode()


SELECTION = {"reader": "jsonstat2", "series_dimensions": ["Region"], "reason": "Regions"}


def test_reads_annual_values_units_status_and_missing():
    table, prep = prepare_table(dataset(), SELECTION)
    headers, rows = read_csv(table)
    assert headers == ["Year", "Series", "Region", "ContentsCode", "Value", "Unit", "Status"]
    assert [(r["Year"], r["Series"], r["Value"], r["Unit"], r["Status"]) for r in rows] == [
        ("2020", "Region=SE1 (North)", "1.5", "GWh", ""),
        ("2021", "Region=SE1 (North)", ":", "GWh", ""),
        ("2020", "Region=SE2 (South)", "2.5", "GWh", ""),
        ("2021", "Region=SE2 (South)", "3.0", "GWh", "p"),
    ]
    assert prep["format"] == "jsonstat2_v1"
    assert prep["row_provenance"]["2"]["source_reference"] == "index:0; period:2020"


def test_rejects_non_annual_time():
    with pytest.raises(ValueError, match="no aggregation was performed"):
        prepare_jsonstat(dataset(time_codes=("2020M01", "2020M02")), SELECTION)


def test_fixed_dimensions_must_have_one_code_and_unit_is_required():
    with pytest.raises(ValueError, match="one code"):
        prepare_jsonstat(dataset(), {**SELECTION, "series_dimensions": ["ContentsCode"]})
    with pytest.raises(ValueError, match="unit"):
        prepare_jsonstat(dataset(units={"EL01": {}}), SELECTION)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_jsonstat.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sci_search.data_research.jsonstat'`

- [ ] **Step 3: Implement the reader**

```python
# sci_search/data_research/jsonstat.py
"""Annual JSON-stat 2 reader for PxWeb responses. Pure; also runs in the sandbox."""

import csv
import hashlib
import io
import json
import re


def _order(category):
    index = category.get("index")
    if isinstance(index, dict):
        return sorted(index, key=index.get)
    if isinstance(index, list):
        return list(index)
    return list(category.get("label", {}))


def prepare_jsonstat(body, selection):
    if len(body) > 5_000_000:
        raise ValueError("JSON-stat response exceeds the 5 MB analysis limit")
    data = json.loads(body.decode("utf-8-sig"))
    if data.get("class") != "dataset":
        raise ValueError("Response is not a JSON-stat dataset")
    ids, sizes, dims = data["id"], data["size"], data["dimension"]
    if len(ids) != len(sizes) or set(ids) != set(dims):
        raise ValueError("Inconsistent JSON-stat dimensions")
    time = (data.get("role") or {}).get("time") or []
    if len(time) != 1:
        raise ValueError("JSON-stat dataset needs exactly one time dimension")
    time_id = time[0]
    order = {d: _order(dims[d]["category"]) for d in ids}
    if [len(order[d]) for d in ids] != sizes:
        raise ValueError("JSON-stat category counts do not match sizes")
    years = []
    for code in order[time_id]:
        if not re.fullmatch(r"(?:18|19|20|21)\d{2}", code.strip()):
            raise ValueError(f"dataset period {code!r} is not annual; no aggregation was performed")
        years.append(code.strip())
    others = [d for d in ids if d != time_id]
    series = selection.get("series_dimensions") or []
    if not set(series) <= set(others):
        raise ValueError("Series dimensions must be JSON-stat dimensions")
    for d in others:
        if d not in series and len(order[d]) != 1:
            raise ValueError(f"Dimension {d} is not a series dimension and needs exactly one code")
    metric = ((data.get("role") or {}).get("metric") or [None])[0]
    units = dims[metric]["category"].get("unit", {}) if metric else {}
    values = data["value"]
    if isinstance(values, list):
        values = dict(enumerate(values))
    else:
        values = {int(k): v for k, v in values.items()}
    status = data.get("status") or {}
    if isinstance(status, list):
        status = dict(enumerate(status))
    elif isinstance(status, str):
        status = {i: status for i in values}
    else:
        status = {int(k): v for k, v in status.items()}
    labels = {d: dims[d]["category"].get("label", {}) for d in others}
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Year", "Series", *others, "Value", "Unit", "Status"])
    provenance, numeric, line = {}, 0, 2
    strides = []
    stride = 1
    for size in reversed(sizes):
        strides.insert(0, stride)
        stride *= size
    import itertools

    for combination in itertools.product(*[range(len(order[d])) for d in others]):
        codes = {d: order[d][i] for d, i in zip(others, combination, strict=True)}
        unit_code = codes.get(metric) if metric else None
        unit = (units.get(unit_code) or {}).get("base", "") if unit_code else ""
        if not unit:
            raise ValueError("JSON-stat measure has no documented unit")
        entity = " | ".join(
            d + "=" + codes[d] + (f" ({labels[d][codes[d]]})" if codes[d] in labels[d] else "")
            for d in series
        ) or "value"
        for t, year in enumerate(years):
            position = {**dict(zip(others, combination, strict=True)), time_id: t}
            flat = sum(position[d] * strides[i] for i, d in enumerate(ids))
            value = values.get(flat)
            text = ":" if value is None else repr(float(value)) if isinstance(value, float) else str(value)
            if value is not None:
                numeric += 1
            flag = str(status.get(flat, "") or "")
            writer.writerow([year, entity, *[codes[d] for d in others], text, unit, flag])
            provenance[str(line)] = {
                "source_reference": f"index:{flat}; period:{year}",
                "unit": unit,
                "status": flag,
                "source_value": "" if value is None else str(value),
                "dimensions": codes,
            }
            line += 1
    table = output.getvalue().encode()
    return table, dict(
        format="jsonstat2_v1",
        selection={"reader": "jsonstat2", **{k: v for k, v in selection.items() if k != "reader"}},
        row_provenance=provenance,
        normalized_sha256=hashlib.sha256(table).hexdigest(),
        checks={"output_rows": line - 2, "numeric_observations": numeric},
        metadata=json.dumps(
            {"dimension_labels": {d: dims[d].get("label", d) for d in ids}, "code_labels": labels, "units": units},
            ensure_ascii=False,
        ),
        limitations=[
            "Values were requested from the statistical API for the selected codes only; no aggregation was performed.",
            "Original status codes are retained; ':' means not published.",
        ],
    )
```

The `repr(float(...))` keeps `1.5` as `1.5` and `3.0` as `3.0`; integers stay as written.

- [ ] **Step 4: Register the reader and the engine**

In `sci_search/data_research/packages.py`, at the top of `prepare_table` before the `statistical_tsv` branch, add:

```python
    if selection is not None and selection.get("reader") == "jsonstat2":
        try:
            from .jsonstat import prepare_jsonstat
        except ImportError:
            from jsonstat import prepare_jsonstat
        return prepare_jsonstat(body, selection)
```

In `sci_search/data_research/artifacts.py`, add `"jsonstat.py",` to `ENGINES`. In `sci_search/data_research/workflow.py:105-112`, add `"jsonstat.py",` to the tuple of engines copied into the run directory.

- [ ] **Step 5: Run the tests**

Run: `uv run python -m pytest tests/test_jsonstat.py tests/test_data_packages.py tests/test_python_data_artifacts.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add sci_search/data_research/jsonstat.py sci_search/data_research/packages.py sci_search/data_research/artifacts.py sci_search/data_research/workflow.py tests/test_jsonstat.py
git commit -m "Add an annual JSON-stat 2 reader for PxWeb responses"
```

---

### Task 4: OWID grapher reader

**Files:**
- Create: `sci_search/data_research/owid_tables.py`
- Modify: `sci_search/data_research/packages.py` (dispatch), `sci_search/data_research/artifacts.py` (`ENGINES`), `sci_search/data_research/workflow.py:105-112` (engine copy)
- Test: `tests/test_owid_tables.py`

**Interfaces:**
- Raw artifact: a JSON envelope `{"csv": <grapher CSV text, verbatim>, "metadata": <metadata JSON object, verbatim>}` encoded as UTF-8. The connector records the SHA-256 of each original response in the request provenance.
- Produces: `prepare_owid(body: bytes, selection: dict) -> tuple[bytes, dict]` with `selection = {"reader": "owid_csv", "indicator": <column short name>, "entities": [entity names], "reason": str}`. Output columns `Year, Series, Code, Value, Unit, Status`; `format="owid_csv_v1"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_owid_tables.py
import json

import pytest

from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv

CSV = "entity,code,year,life_expectancy_0\nGermany,DEU,2000,77.9\nGermany,DEU,2001,78.2\nNetherlands,NLD,2000,78.0\nWorld,OWID_WRL,2000,66.5\n"
METADATA = {"columns": {"life_expectancy_0": {"titleShort": "Life expectancy", "unit": "years", "shortName": "life_expectancy_0", "descriptionShort": "Period life expectancy at birth"}}}


def envelope(csv_text=CSV, metadata=METADATA):
    return json.dumps({"csv": csv_text, "metadata": metadata}).encode()


SELECTION = {"reader": "owid_csv", "indicator": "life_expectancy_0", "entities": ["Germany", "Netherlands"], "reason": "Requested"}


def test_reads_selected_entities_with_unit():
    table, prep = prepare_table(envelope(), SELECTION)
    headers, rows = read_csv(table)
    assert headers == ["Year", "Series", "Code", "Value", "Unit", "Status"]
    assert [(r["Year"], r["Series"], r["Value"], r["Unit"]) for r in rows] == [
        ("2000", "Germany", "77.9", "years"),
        ("2001", "Germany", "78.2", "years"),
        ("2000", "Netherlands", "78.0", "years"),
    ]
    assert prep["format"] == "owid_csv_v1"
    assert prep["row_provenance"]["2"]["source_reference"] == "csv-line:2"


def test_unknown_entity_or_indicator_or_missing_unit_is_rejected():
    with pytest.raises(ValueError, match="entities"):
        prepare_table(envelope(), {**SELECTION, "entities": ["Atlantis"]})
    with pytest.raises(ValueError, match="indicator"):
        prepare_table(envelope(), {**SELECTION, "indicator": "gdp"})
    no_unit = {"columns": {"life_expectancy_0": {"titleShort": "x", "unit": ""}}}
    with pytest.raises(ValueError, match="unit"):
        prepare_table(envelope(metadata=no_unit), SELECTION)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_owid_tables.py -q`
Expected: FAIL (the selection falls through to the generic reader and raises an unrelated error, or `ModuleNotFoundError` once dispatch is added)

- [ ] **Step 3: Implement the reader**

```python
# sci_search/data_research/owid_tables.py
"""Our World in Data grapher CSV reader. Pure; also runs in the sandbox."""

import csv
import hashlib
import io
import json
import re


def prepare_owid(body, selection):
    if len(body) > 5_000_000:
        raise ValueError("OWID response exceeds the 5 MB analysis limit")
    envelope = json.loads(body.decode("utf-8"))
    columns = envelope["metadata"].get("columns", {})
    indicator = selection.get("indicator")
    if indicator not in columns:
        raise ValueError("Selected OWID indicator is not in the chart metadata")
    unit = (columns[indicator].get("unit") or columns[indicator].get("shortUnit") or "").strip()
    if not unit:
        raise ValueError("OWID indicator has no documented unit")
    reader = csv.DictReader(io.StringIO(envelope["csv"]))
    if not {"entity", "year", indicator} <= set(reader.fieldnames or []):
        raise ValueError("OWID CSV lacks entity, year or the selected indicator column")
    wanted = selection.get("entities") or []
    rows = list(reader)
    observed = {r["entity"] for r in rows}
    if not wanted or not set(wanted) <= observed:
        raise ValueError("Selected OWID entities are not in the chart data")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Year", "Series", "Code", "Value", "Unit", "Status"])
    provenance, line = {}, 2
    for number, row in enumerate(rows, 2):
        if row["entity"] not in wanted:
            continue
        if not re.fullmatch(r"-?\d{1,4}", row["year"]):
            raise ValueError("OWID year is not annual; no aggregation was performed")
        value = row[indicator].strip() or ":"
        writer.writerow([row["year"], row["entity"], row.get("code", ""), value, unit, ""])
        provenance[str(line)] = {"source_reference": f"csv-line:{number}", "unit": unit, "status": "", "source_value": row[indicator]}
        line += 1
    table = output.getvalue().encode()
    return table, dict(
        format="owid_csv_v1",
        selection={"reader": "owid_csv", **{k: v for k, v in selection.items() if k != "reader"}},
        row_provenance=provenance,
        normalized_sha256=hashlib.sha256(table).hexdigest(),
        checks={"output_rows": line - 2},
        metadata=json.dumps(columns[indicator], ensure_ascii=False)[:30000],
        limitations=[
            "Our World in Data republishes data from the sources named in its metadata; check the original source definitions.",
        ],
    )
```

Note: the test's source-reference expectation `csv-line:2` refers to the first data line (`Germany,DEU,2000`), which is physical line 2 of the CSV.

- [ ] **Step 4: Register the reader and the engine**

In `packages.prepare_table`, next to the `jsonstat2` branch:

```python
    if selection is not None and selection.get("reader") == "owid_csv":
        try:
            from .owid_tables import prepare_owid
        except ImportError:
            from owid_tables import prepare_owid
        return prepare_owid(body, selection)
```

Add `"owid_tables.py",` to `artifacts.ENGINES` and to the engine tuple in `workflow.py:105-112`.

- [ ] **Step 5: Run the tests**

Run: `uv run python -m pytest tests/test_owid_tables.py tests/test_jsonstat.py tests/test_data_packages.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add sci_search/data_research/owid_tables.py sci_search/data_research/packages.py sci_search/data_research/artifacts.py sci_search/data_research/workflow.py tests/test_owid_tables.py
git commit -m "Add an Our World in Data grapher reader"
```

---

### Task 5: Record real API fixtures

**Files:**
- Create: `scripts/record_connector_fixtures.py`
- Create: `tests/fixtures/data_research/connectors/` (recorded files and `README.md`)

**Interfaces:**
- Produces these fixture files, used by Tasks 6 to 9:
  - `eurostat/dataflows.xml` (trimmed to the first 200 dataflows plus `demo_mlexpec` and `nrg_ind_ren`), `eurostat/demo_mlexpec-structure.xml`, `eurostat/demo_mlexpec-keys.tsv`, `eurostat/demo_mlexpec-slice.tsv.gz`
  - `cbs/catalogue.json` (trimmed to 200 tables including `82610NED` and `85929NED`), `cbs/82610NED.zip`
  - `pxweb/scb-search.json`, `pxweb/scb-TAB4311-metadata.json`, `pxweb/scb-TAB4311-data.json`, `pxweb/ssb-search.json`
  - `owid/search.json`, `owid/life-expectancy.csv`, `owid/life-expectancy.metadata.json`

- [ ] **Step 1: Write the recorder**

```python
# scripts/record_connector_fixtures.py
"""Record real statistical API responses as offline test fixtures. Needs network access."""

import json
import re
from pathlib import Path

from sci_search.data_research.retrieval import fetch_public

ROOT = Path(__file__).resolve().parents[1] / "tests/fixtures/data_research/connectors"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
RECORDINGS = {
    "eurostat/demo_mlexpec-structure.xml": EUROSTAT + "/dataflow/ESTAT/demo_mlexpec?references=descendants&detail=referencepartial",
    "eurostat/demo_mlexpec-keys.tsv": EUROSTAT + "/data/demo_mlexpec/A.YR..Y_LT1./?format=TSV&detail=serieskeysonly&startPeriod=2000",
    "eurostat/demo_mlexpec-slice.tsv.gz": EUROSTAT + "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/?format=TSV&compressed=true&startPeriod=2000&endPeriod=2024",
    "cbs/82610NED.zip": "https://datasets.cbs.nl/CSV/CBS/nl/82610NED",
    "pxweb/scb-search.json": "https://statistikdatabasen.scb.se/api/v2/tables?query=electricity&lang=en&pageSize=10",
    "pxweb/scb-TAB4311-metadata.json": "https://statistikdatabasen.scb.se/api/v2/tables/TAB4311/metadata?lang=en&outputFormat=json-stat2",
    "pxweb/scb-TAB4311-data.json": "https://statistikdatabasen.scb.se/api/v2/tables/TAB4311/data?lang=en&outputFormat=json-stat2",
    "pxweb/ssb-search.json": "https://data.ssb.no/api/v0/en/table/?query=electricity",
    "owid/search.json": "https://ourworldindata.org/api/search?q=life%20expectancy",
    "owid/life-expectancy.csv": "https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=true",
    "owid/life-expectancy.metadata.json": "https://ourworldindata.org/grapher/life-expectancy.metadata.json?v=1",
}


def trim_dataflows(xml):
    flows = re.findall(r"<s:Dataflow .*?</s:Dataflow>", xml, re.S)
    keep = flows[:200] + [f for f in flows if 'id="DEMO_MLEXPEC"' in f.upper() or 'id="NRG_IND_REN"' in f.upper()]
    start = xml.index("<s:Dataflows>") + len("<s:Dataflows>")
    end = xml.index("</s:Dataflows>")
    return xml[:start] + "".join(dict.fromkeys(keep)) + xml[end:]


def main():
    for name, url in RECORDINGS.items():
        body, _, _ = fetch_public(url)
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        print(name, len(body))
    flows, _, _ = fetch_public(EUROSTAT + "/dataflow/ESTAT/all?detail=allstubs")
    (ROOT / "eurostat/dataflows.xml").write_text(trim_dataflows(flows.decode()))
    catalogue, _, _ = fetch_public(
        "https://opendata.cbs.nl/ODataCatalog/Tables?$format=json&$select=Identifier,Title,Frequency,Language,Period,ShortDescription"
    )
    tables = json.loads(catalogue)["value"]
    keep = tables[:200] + [t for t in tables if t["Identifier"] in {"82610NED", "85929NED"}]
    (ROOT / "cbs/catalogue.json").write_text(json.dumps({"value": list({t["Identifier"]: t for t in keep}.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the recorder**

Run: `uv run python scripts/record_connector_fixtures.py`
Expected: one line per fixture with a non-zero size. If an endpoint returns non-200, stop and report the endpoint and status to your human partner; do not invent a fixture.

- [ ] **Step 3: Verify the recordings answer the design's assumptions**

Run:
```bash
cd tests/fixtures/data_research/connectors
zcat eurostat/demo_mlexpec-slice.tsv.gz | head -3
head -3 eurostat/demo_mlexpec-keys.tsv
python3 -c "import json;d=json.load(open('pxweb/scb-TAB4311-data.json'));print(d['class'],d['id'],d['role'])"
head -2 owid/life-expectancy.csv
```
Expected: the TSV header starts `freq,unit,sex,age,geo\TIME_PERIOD`; the keys file lists `A,YR,F,Y_LT1,...` lines; the SCB data is `dataset` with a `time` role; the OWID CSV starts `entity,code,year,`.

- [ ] **Step 4: Add the fixture README**

```markdown
# Connector fixtures

Real API responses recorded on <date of recording> by `scripts/record_connector_fixtures.py`.
The Eurostat dataflow list and CBS catalogue are trimmed to keep the repository small; every other
file is the verbatim response. Licences: Eurostat, CBS and Our World in Data publish under CC BY
4.0; Statistics Sweden and Statistics Norway under CC BY 4.0. Re-record with the script when an API
changes, and review the diff.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/record_connector_fixtures.py tests/fixtures/data_research/connectors
git commit -m "Record real statistical API responses as connector fixtures"
```

---

### Task 6: Eurostat connector

**Files:**
- Create: `sci_search/data_research/connectors/eurostat.py`
- Modify: `sci_search/data_research/connectors/__init__.py` (register)
- Test: `tests/test_connector_eurostat.py`

**Interfaces:**
- Consumes: `base.*` (Task 2), `retrieval.fetch_scoped`, `retrieval._await_eurostat`, `statistical_tables.inspect_statistics`.
- Produces module attributes and functions used by the stage (Task 10): `NAME = "eurostat"`, `PUBLISHER = "Eurostat"`, `LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"`, `HOSTS = {"ec.europa.eu"}`;
  - `search(terms: list[str], scope: dict, *, fetch, cache_dir: Path) -> tuple[list[DatasetCandidate], str]` (candidates, catalogue SHA-256);
  - `describe(candidate, scope: dict, *, fetch) -> DatasetDescription`;
  - `fetch(description, selection: dict, scope: dict, *, fetch, post) -> Fetched`;
  - `mapping(table: bytes, preparation: dict, selection: dict, measurement: str) -> dict`;
  - `dataset_from_url(url: str) -> str | None`.
- `ISO3_TO_GEO: dict[str, str]` mapping ISO-3 country codes to Eurostat geo codes (`GRC -> EL`, `GBR -> UK`, otherwise the ISO-2 code).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_eurostat.py
from pathlib import Path

import pytest

from sci_search.data_research.connectors import base, eurostat
from sci_search.data_research.packages import prepare_table

FIX = Path(__file__).parent / "fixtures/data_research/connectors/eurostat"


def offline(url):
    if "/dataflow/ESTAT/all" in url:
        return (FIX / "dataflows.xml").read_bytes(), "application/xml", url
    if "/dataflow/ESTAT/demo_mlexpec" in url:
        return (FIX / "demo_mlexpec-structure.xml").read_bytes(), "application/xml", url
    if "detail=serieskeysonly" in url:
        return (FIX / "demo_mlexpec-keys.tsv").read_bytes(), "text/tab-separated-values", url
    if "/data/demo_mlexpec/" in url:
        return (FIX / "demo_mlexpec-slice.tsv.gz").read_bytes(), "application/octet-stream", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": 2000, "end_year": 2024, "countries": ["NLD", "DEU", "GRC"]}


def test_search_finds_life_expectancy_in_the_catalogue(tmp_path):
    candidates, digest = eurostat.search(["life expectancy", "sex"], SCOPE, fetch=offline, cache_dir=tmp_path)
    assert "demo_mlexpec" in [c.dataset for c in candidates]
    assert len(digest) == 64


def test_describe_lists_only_observed_codes_and_maps_countries(tmp_path):
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    dims = {d.id: d for d in description.dimensions}
    assert set(dims) == {"freq", "unit", "sex", "age", "geo"}
    assert set(dims["geo"].codes) == {"NL", "DE", "EL"}  # restricted to the requested countries
    assert dims["freq"].codes == {"A": dims["freq"].codes["A"]}
    assert dims["sex"].codes["F"]  # labelled


def test_fetch_requests_a_key_filtered_slice_and_reads_it():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    requested = []

    def recording(url):
        requested.append(url)
        return offline(url)

    selection = {
        "filters": {"freq": ["A"], "unit": ["YR"], "sex": ["F", "M"], "age": ["Y_LT1"], "geo": ["NL", "DE", "EL"]},
        "series_dimensions": ["sex", "geo"],
        "reason": "Requested",
    }
    fetched = eurostat.fetch(description, selection, SCOPE, fetch=recording, post=None)
    assert "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/" in requested[-1]
    assert "startPeriod=2000" in requested[-1] and "endPeriod=2024" in requested[-1]
    table, prep = prepare_table(fetched.raw, fetched.selection)
    mapping = eurostat.mapping(table, prep, selection, "life expectancy")
    assert mapping["unit"] == "YR" and len(mapping["entities"]) == 6


def test_countries_without_data_are_dropped_with_a_note():
    candidate = base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "unknown")
    description = eurostat.describe(candidate, SCOPE, fetch=offline)
    selection = {
        "filters": {"freq": ["A"], "unit": ["YR"], "sex": ["F"], "age": ["Y_LT1"], "geo": ["NL", "DE", "EL"]},
        "series_dimensions": ["geo"],
        "reason": "Requested",
    }

    def slice_without_greece(url):
        body, kind, final = offline(url)
        if "/data/demo_mlexpec/" in url and "serieskeysonly" not in url:
            import gzip

            lines = gzip.decompress(body).decode().splitlines(keepends=True)
            body = gzip.compress("".join(l for l in lines if ",EL\t" not in l).encode())
        return body, kind, final

    fetched = eurostat.fetch(description, selection, SCOPE, fetch=slice_without_greece, post=None)
    assert {"dimension": "geo", "values": ["NL", "DE"]} in fetched.selection["filters"]
    assert any("EL" in note for note in fetched.notes)


def test_dataset_from_url():
    assert eurostat.dataset_from_url("https://ec.europa.eu/eurostat/databrowser/view/NRG_IND_REN__custom_9909313/default/bar") == "nrg_ind_ren"
    assert eurostat.dataset_from_url("https://ec.europa.eu/eurostat/web/products-datasets/-/demo_mlexpec") == "demo_mlexpec"
    assert eurostat.dataset_from_url("https://example.org/eurostat/databrowser/view/demo_mlexpec") is None


def test_iso3_mapping_uses_eurostat_codes():
    assert eurostat.ISO3_TO_GEO["GRC"] == "EL" and eurostat.ISO3_TO_GEO["GBR"] == "UK"
    assert eurostat.ISO3_TO_GEO["NLD"] == "NL"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_eurostat.py -q`
Expected: FAIL with `ImportError: cannot import name 'eurostat'`

- [ ] **Step 3: Implement the connector**

```python
# sci_search/data_research/connectors/eurostat.py
"""Eurostat SDMX 2.1 connector: dataset list, structure, series keys and key-filtered TSV."""

import re
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

from sci_search.data_research.connectors import base
from sci_search.data_research.retrieval import fetch_scoped

NAME = "eurostat"
PUBLISHER = "Eurostat"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
HOSTS = {"ec.europa.eu"}
API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
NS = {
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_ISO = (
    "AUT AT BEL BE BGR BG HRV HR CYP CY CZE CZ DNK DK EST EE FIN FI FRA FR DEU DE GRC EL HUN HU "
    "IRL IE ITA IT LVA LV LTU LT LUX LU MLT MT NLD NL POL PL PRT PT ROU RO SVK SK SVN SI ESP ES "
    "SWE SE ALB AL AND AD BLR BY BIH BA GBR UK ISL IS LIE LI MCO MC MDA MD MNE ME MKD MK NOR NO "
    "RUS RU SMR SM SRB RS CHE CH TUR TR UKR UA ARM AM AZE AZ GEO GE XKX XK"
).split()
ISO3_TO_GEO = dict(zip(_ISO[0::2], _ISO[1::2], strict=True))


def _name(node):
    names = node.findall("c:Name", NS)
    for name in names:
        if name.get(XML_LANG) == "en":
            return name.text or ""
    return names[0].text if names else ""


def dataset_from_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        return None
    match = re.match(r"^/eurostat/(?:databrowser/view|web/products-datasets/-)/([A-Za-z0-9_]+)(?:/|$)", parts.path)
    if not match:
        return None
    return re.sub(r"__custom_\d+$", "", match[1], flags=re.I).lower()


def search(terms, scope, *, fetch, cache_dir):
    body, digest = base.catalogue(NAME, API + "/dataflow/ESTAT/all?detail=allstubs", fetch, cache_dir)
    root = ElementTree.fromstring(body)
    found = []
    for flow in root.iter("{%s}Dataflow" % NS["s"]):
        title = _name(flow)
        points = base.score(title, terms)
        if points:
            found.append((points, flow.get("id", "").lower(), title))
    found.sort(key=lambda item: -item[0])
    candidates = [
        base.DatasetCandidate(NAME, dataset, title, "unknown", landing_url=f"https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table")
        for _, dataset, title in found[:10]
    ]
    return candidates, digest


def _structure(dataset, fetch):
    body, _, _ = fetch(f"{API}/dataflow/ESTAT/{dataset}?references=descendants&detail=referencepartial")
    root = ElementTree.fromstring(body)
    codelists = {
        cl.get("id"): {code.get("id"): _name(code) for code in cl.findall("s:Code", NS)}
        for cl in root.iter("{%s}Codelist" % NS["s"])
    }
    dimensions = []
    for dim in root.iter("{%s}Dimension" % NS["s"]):
        ref = dim.find("s:LocalRepresentation/s:Enumeration/Ref", NS)
        codelist = ref.get("id") if ref is not None else dim.get("id", "").upper()
        dimensions.append((int(dim.get("position", "0")), dim.get("id"), codelists.get(codelist, {})))
    dimensions.sort()
    flow = next(root.iter("{%s}Dataflow" % NS["s"]), None)
    return [(d, codes) for _, d, codes in dimensions], _name(flow) if flow is not None else dataset


def _key(order, filters):
    return ".".join("+".join(filters.get(d, [])) for d in order)


def describe(candidate, scope, *, fetch):
    order, title = _structure(candidate.dataset, fetch)
    wildcard = {d: (["A"] if d == "freq" else []) for d, _ in order}
    query = {"format": "TSV", "detail": "serieskeysonly"}
    if scope.get("start_year"):
        query["startPeriod"] = str(scope["start_year"])
    body, _, _ = fetch(f"{API}/data/{candidate.dataset}/{_key([d for d, _ in order], wildcard)}/?{urlencode(query)}")
    lines = body.decode("utf-8-sig").splitlines()
    header = lines[0].split(",") if lines else []
    observed = {d: set() for d in header}
    for line in lines[1:]:
        for d, code in zip(header, line.split(","), strict=False):
            observed[d].add(code.strip())
    if not lines[1:]:
        raise base.DatasetRejected("dataset is not annual or has no series in the requested period; no aggregation was performed")
    wanted_geo = {ISO3_TO_GEO[c] for c in scope.get("countries") or [] if c in ISO3_TO_GEO}
    dimensions = []
    for d, codes in order:
        present = observed.get(d, set())
        if d == "geo" and wanted_geo:
            present = present & wanted_geo
        dimensions.append(base.Dimension(d, d, {c: codes.get(c, c) for c in sorted(present)}))
    definitions = title + "\n" + "\n".join(f"{d.id}: " + "; ".join(f"{c}={l}" for c, l in d.codes.items()) for d in dimensions)
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dimensions),
        years=(),
        licence_url=LICENCE_URL,
        definitions=definitions[:30000],
        publisher=PUBLISHER,
        extra={"order": [d for d, _ in order]},
    )


def fetch(description, selection, scope, *, fetch, post):
    from sci_search.data_research.statistical_tables import inspect_statistics

    order = description.extra["order"]
    filters = selection["filters"]
    query = {"format": "TSV", "compressed": "true"}
    if scope.get("start_year"):
        query["startPeriod"] = str(scope["start_year"])
    if scope.get("end_year"):
        query["endPeriod"] = str(scope["end_year"])
    url = f"{API}/data/{description.candidate.dataset}/{_key(order, filters)}/?{urlencode(query)}"
    raw, _, final = fetch_scoped(url, scope, fetch, [])
    preview = inspect_statistics(raw)
    notes = []
    kept = {}
    for d in order:
        present = [c for c in filters[d] if c in preview["dimension_values"].get(d, [])]
        missing = [c for c in filters[d] if c not in present]
        if not present:
            raise base.SelectionError(
                f"No published series for the selected {d} codes",
                {"published_codes": preview["dimension_values"]},
            )
        if missing:
            if d not in selection["series_dimensions"]:
                raise base.SelectionError(f"Fixed code for {d} has no published series", {"published_codes": preview["dimension_values"]})
            notes.append(f"No data published for {d}: " + ", ".join(missing))
        kept[d] = present
    labels = {d.id: d.codes for d in description.dimensions}
    return base.Fetched(
        raw=raw,
        request={"method": "GET", "url": final},
        selection={
            "reader": "statistical_tsv",
            "filters": [{"dimension": d, "values": kept[d]} for d in order],
            "series_dimensions": selection["series_dimensions"],
            "code_labels": labels,
            "reason": selection["reason"],
        },
        artifact="source.tsv.gz",
        notes=tuple(notes),
    )


def mapping(table, preparation, selection, measurement):
    return base.series_mapping(table, measurement)
```

Register in `connectors/__init__.py` (below `CONNECTORS = {}`):

```python
def _register():
    from sci_search.data_research.connectors import eurostat

    CONNECTORS.update({eurostat.NAME: eurostat})


_register()
```

Note: `fetch_scoped` already follows Eurostat's asynchronous delivery protocol. If the structure fixture uses a different element path for codelist references (check `grep -o "<Ref [^>]*" demo_mlexpec-structure.xml | head`), adjust the `find` path in `_structure` and keep the test unchanged.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_eurostat.py tests/test_connector_base.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sci_search/data_research/connectors tests/test_connector_eurostat.py
git commit -m "Add the Eurostat SDMX connector"
```

---

### Task 7: CBS connector

**Files:**
- Create: `sci_search/data_research/connectors/cbs.py`
- Modify: `sci_search/data_research/connectors/__init__.py` (register)
- Test: `tests/test_connector_cbs.py`

**Interfaces:**
- Same module contract as Task 6, with `NAME = "cbs"`, `PUBLISHER = "CBS (Statistics Netherlands)"`, `HOSTS = {"www.cbs.nl", "opendata.cbs.nl", "datasets.cbs.nl"}`.
- `describe` downloads the CSV package into `description.payload`. Dimension ids: `"Measure"` (codes are measure identifiers, labels are `"<title> (<unit>)"`) plus each CBS dimension except the time dimension. `years` comes from the period codes.
- `fetch` returns `Fetched(raw=description.payload, request={"method": "GET", "url": package_url}, selection=None, artifact="source.zip")`. Filtering happens in `mapping`.
- `mapping` builds an `analyse_csv` mapping on the normalised CBS table: filters `Measure`, `Unit` and every fixed dimension by label; at most one series dimension (its labels become `entities`); `decimal_separator` is `","` when any selected value contains a comma.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_cbs.py
from pathlib import Path

import pytest

from sci_search.data_research.connectors import base, cbs
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import analyse_csv

FIX = Path(__file__).parent / "fixtures/data_research/connectors/cbs"


def offline(url):
    if "ODataCatalog/Tables" in url:
        return (FIX / "catalogue.json").read_bytes(), "application/json", url
    if url == "https://datasets.cbs.nl/CSV/CBS/nl/82610NED":
        return (FIX / "82610NED.zip").read_bytes(), "application/zip", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": 2000, "end_year": 2024, "countries": ["NLD"]}


def test_search_matches_dutch_titles(tmp_path):
    candidates, digest = cbs.search(["hernieuwbare elektriciteit"], SCOPE, fetch=offline, cache_dir=tmp_path)
    assert "82610NED" in [c.dataset for c in candidates]
    assert all(c.frequency in {"annual", "monthly", "quarterly", "other", "unknown"} for c in candidates)


def test_describe_and_mapping_select_one_measure_in_one_unit():
    candidate = base.DatasetCandidate("cbs", "82610NED", "Hernieuwbare elektriciteit", "annual")
    description = cbs.describe(candidate, SCOPE, fetch=offline)
    dims = {d.id: d for d in description.dimensions}
    assert dims["Measure"].codes["M002416_2"] == "Genormaliseerde bruto productie (in % van het verbruik)"
    assert 2000 in description.years and 2024 in description.years
    total = next(c for c, label in dims["BronTechniek"].codes.items() if label == "Totaal hernieuwbare energiebronnen")
    selection = {"filters": {"Measure": ["M002416_2"], "BronTechniek": [total]}, "series_dimensions": [], "reason": "Share"}
    fetched = cbs.fetch(description, selection, SCOPE, fetch=offline, post=None)
    table, prep = prepare_table(fetched.raw, fetched.selection)
    mapping = cbs.mapping(table, prep, selection, "renewable electricity share")
    analysis = analyse_csv(table, mapping, {"start_year": 2000, "end_year": 2024})
    values = {row["year"]: row["value"] for row in analysis["series"][0]["annual"]}
    assert values[2000] == pytest.approx(2.64) and values[2024] == pytest.approx(50.54)


def test_more_than_one_series_dimension_is_refused():
    candidate = base.DatasetCandidate("cbs", "82610NED", "x", "annual")
    description = cbs.describe(candidate, SCOPE, fetch=offline)
    codes = list({d.id: d for d in description.dimensions}["Measure"].codes)[:2]
    with pytest.raises(base.SelectionError, match="one series dimension"):
        cbs.mapping(b"", {}, {"filters": {"Measure": codes}, "series_dimensions": ["Measure", "BronTechniek"], "reason": ""}, "x")


def test_dataset_from_url():
    assert cbs.dataset_from_url("https://www.cbs.nl/nl-nl/cijfers/detail/82610NED") == "82610NED"
    assert cbs.dataset_from_url("https://opendata.cbs.nl/ODataApi/OData/85929NED") == "85929NED"
    assert cbs.dataset_from_url("https://datasets.cbs.nl/CSV/CBS/nl/85929NED") == "85929NED"
    assert cbs.dataset_from_url("https://www.cbs.nl/nl-nl/longread/2025/iets") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_cbs.py -q`
Expected: FAIL with `ImportError: cannot import name 'cbs'`

- [ ] **Step 3: Implement the connector**

```python
# sci_search/data_research/connectors/cbs.py
"""CBS connector: catalogue search and CSV packages with their code tables."""

import json
import re
from urllib.parse import urlsplit

from sci_search.data_research.connectors import base
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import read_csv

NAME = "cbs"
PUBLISHER = "CBS (Statistics Netherlands)"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
HOSTS = {"www.cbs.nl", "opendata.cbs.nl", "datasets.cbs.nl"}
CATALOGUE = "https://opendata.cbs.nl/ODataCatalog/Tables?$format=json&$select=Identifier,Title,Frequency,Language,Period,ShortDescription"
FREQUENCY = {"Perjaar": "annual", "Permaand": "monthly", "Perkwartaal": "quarterly"}
ID = r"\d{5}[A-Z]{3}"


def package_url(dataset):
    return "https://datasets.cbs.nl/CSV/CBS/nl/" + dataset


def dataset_from_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        return None
    match = re.search(rf"/(?:cijfers/detail|figures/detail|ODataApi/OData|CSV/CBS/[a-z]{{2}})/({ID})(?:/|$|\?)", parts.path + "/")
    return match[1].upper() if match else None


def search(terms, scope, *, fetch, cache_dir):
    body, digest = base.catalogue(NAME, CATALOGUE, fetch, cache_dir)
    found = []
    for table in json.loads(body)["value"]:
        points = base.score(table["Title"] + " " + (table.get("ShortDescription") or ""), terms)
        if points:
            found.append((points, table))
    found.sort(key=lambda item: -item[0])
    return [
        base.DatasetCandidate(
            NAME,
            t["Identifier"],
            t["Title"],
            FREQUENCY.get(t.get("Frequency", ""), "unknown"),
            landing_url="https://www.cbs.nl/nl-nl/cijfers/detail/" + t["Identifier"],
        )
        for _, t in found[:10]
    ], digest


def _codes(archive, name):
    _, rows = read_csv(archive.read(name), delimiter=";")
    return rows


def describe(candidate, scope, *, fetch):
    import io
    import zipfile

    raw, _, _ = fetch(package_url(candidate.dataset))
    table, preparation = prepare_table(raw)  # validates the package with the existing CBS reader
    metadata = json.loads(preparation["metadata"])
    measures = {m["Identifier"]: f"{m['Title']} ({m['Unit']})" for m in metadata["measures"]}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        dims = _codes(archive, "Dimensions.csv")
    time = next(d["Identifier"] for d in dims if d["Kind"] == "TimeDimension")
    dimensions = [base.Dimension("Measure", "Measure", measures)]
    for d in dims:
        if d["Identifier"] == time:
            continue
        codes = metadata["codes"][d["Identifier"]]
        dimensions.append(base.Dimension(d["Identifier"], d.get("Title", d["Identifier"]), {c: v["Title"] for c, v in codes.items()}))
    years = tuple(sorted({y for y in (base.annual(c) for c in metadata["codes"][time]) if y}))
    if not years:
        raise base.DatasetRejected("dataset has no annual periods; no aggregation was performed")
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dimensions),
        years=years,
        licence_url=preparation.get("license_url") or LICENCE_URL,
        definitions=preparation["metadata"][:30000],
        publisher=PUBLISHER,
        payload=raw,
        extra={"measure_units": {m["Identifier"]: (m["Title"], m["Unit"]) for m in metadata["measures"]}},
    )


def fetch(description, selection, scope, *, fetch, post):
    return base.Fetched(
        raw=description.payload,
        request={"method": "GET", "url": package_url(description.candidate.dataset)},
        selection=None,
        artifact="source.zip",
    )


def mapping(table, preparation, selection, measurement, description=None):
    series = selection["series_dimensions"]
    if len(series) > 1:
        raise base.SelectionError("CBS selections support at most one series dimension")
    if "Measure" in series:
        raise base.SelectionError("Select one CBS measure; compare measures as separate analyses")
    measure = selection["filters"]["Measure"][0]
    title, unit = (description.extra["measure_units"] if description else _units(preparation))[measure]
    labels = _labels(preparation)
    filters = {"Measure": title, "Unit": unit}
    for d, codes in selection["filters"].items():
        if d != "Measure" and d not in series:
            filters[d] = labels[d][codes[0]]
    _, rows = read_csv(table)
    selected = [r for r in rows if all(r[k] == v for k, v in filters.items())]
    comma = any("," in r["Value"] for r in selected)
    entity = series[0] if series else ""
    return dict(
        year_column="Year",
        value_column="Value",
        entity_column=entity,
        entities=[labels[entity][c] for c in selection["filters"][entity]] if entity else [],
        unit=unit,
        output_unit=unit,
        label=measurement,
        filters=filters,
        missing_values=[""],
        decimal_separator="," if comma else ".",
    )


def _units(preparation):
    metadata = json.loads(preparation["metadata"])
    return {m["Identifier"]: (m["Title"], m["Unit"]) for m in metadata["measures"]}


def _labels(preparation):
    metadata = json.loads(preparation["metadata"])
    return {d: {c: v["Title"] for c, v in codes.items()} for d, codes in metadata["codes"].items()}
```

The stage (Task 10) calls `mapping(table, preparation, selection, measurement)`; CBS reads units and labels from `preparation["metadata"]`, so the optional `description` argument is not needed there. In the test that refuses two series dimensions, `mapping` raises before reading `preparation`.

Register: extend `_register()` in `connectors/__init__.py` to import `cbs` and add `cbs.NAME: cbs`.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_cbs.py tests/test_data_packages.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sci_search/data_research/connectors tests/test_connector_cbs.py
git commit -m "Add the CBS connector"
```

---

### Task 8: PxWeb connector

**Files:**
- Create: `sci_search/data_research/connectors/pxweb.py`
- Modify: `sci_search/data_research/connectors/__init__.py` (register)
- Test: `tests/test_connector_pxweb.py`

**Interfaces:**
- Module contract as Task 6, with `NAME = "pxweb"`, `PUBLISHER` per installation (from `INSTALLATIONS`), `HOSTS = {i["host"] for i in INSTALLATIONS.values()}`.
- `INSTALLATIONS = {"scb": {"host": "statistikdatabasen.scb.se", "version": 2, "base": "https://statistikdatabasen.scb.se/api/v2", "publisher": "Statistics Sweden"}, "ssb": {"host": "data.ssb.no", "version": 1, "base": "https://data.ssb.no/api/v0/en/table", "publisher": "Statistics Norway", "table_from_title": True}}`. Statistics Finland and IRENA are added only after Step 5 confirms their search and data endpoints.
- Dataset ids are `"<installation>:<table>"`, e.g. `"scb:TAB4311"`. Statistics Norway's search returns `{"id": "ResultatKraftVerk", "path": "...", "title": "08386: Income statement ..."}` and its API addresses tables by the five-digit number at the start of the title, so its ids are `"ssb:08386"`. Other v1 installations use `path/id`.
- `fetch` returns `Fetched(raw, request, selection={"reader": "jsonstat2", "series_dimensions": [...], "code_labels": {...}, "reason": ...}, artifact="source.json")`. v2 uses GET with `valueCodes[<dim>]=a,b` parameters; v1 uses `post` with a JSON-stat 2 query body.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_pxweb.py
import json
import re
from pathlib import Path

from sci_search.data_research.connectors import base, pxweb
from sci_search.data_research.packages import prepare_table

FIX = Path(__file__).parent / "fixtures/data_research/connectors/pxweb"


def offline(url):
    if "/api/v2/tables?query=" in url:
        return (FIX / "scb-search.json").read_bytes(), "application/json", url
    if "/TAB4311/metadata" in url:
        return (FIX / "scb-TAB4311-metadata.json").read_bytes(), "application/json", url
    if "/TAB4311/data" in url:
        return (FIX / "scb-TAB4311-data.json").read_bytes(), "application/json", url
    if "data.ssb.no/api/v0/en/table/?query=" in url:
        return (FIX / "ssb-search.json").read_bytes(), "application/json", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": None, "end_year": None, "countries": []}


def test_search_covers_v1_and_v2_installations(tmp_path):
    candidates, _ = pxweb.search(["electricity"], SCOPE, fetch=offline, cache_dir=tmp_path)
    datasets = [c.dataset for c in candidates]
    assert any(d.startswith("scb:") for d in datasets)
    assert any(re.fullmatch(r"ssb:\d{5}", d) for d in datasets)


def test_v2_describe_and_fetch_read_through_jsonstat():
    candidate = base.DatasetCandidate("pxweb", "scb:TAB4311", "Electricity prices", "other")
    description = pxweb.describe(candidate, SCOPE, fetch=offline, require_annual=False)
    dims = {d.id: d for d in description.dimensions}
    assert "Tid" not in dims and {"Kategorimwh", "ContentsCode"} <= set(dims)
    first = {d: [next(iter(dims[d].codes))] for d in dims}
    selection = {"filters": first, "series_dimensions": [], "reason": "One series"}
    requested = []

    def recording(url):
        requested.append(url)
        return offline(url)

    fetched = pxweb.fetch(description, selection, SCOPE, fetch=recording, post=None)
    assert "valueCodes%5BContentsCode%5D=" in requested[-1] or "valueCodes[ContentsCode]=" in requested[-1]
    assert fetched.selection["reader"] == "jsonstat2" and fetched.artifact == "source.json"


def test_v1_fetch_posts_a_jsonstat_query():
    description = base.DatasetDescription(
        candidate=base.DatasetCandidate("pxweb", "ssb:08307", "08307: Electricity balance", "unknown"),
        dimensions=(base.Dimension("ContentsCode", "contents", {"Produksjon": "Production"}),),
        years=(2020, 2021),
        licence_url="https://data.norge.no/nlod/en/2.0",
        definitions="",
        publisher="Statistics Norway",
        extra={"time": "Tid", "time_codes": ["2020", "2021"]},
    )
    sent = []

    def post(url, payload):
        sent.append((url, payload))
        return b'{"class": "dataset"}', "application/json", url

    pxweb.fetch(description, {"filters": {"ContentsCode": ["Produksjon"]}, "series_dimensions": [], "reason": ""}, {"start_year": 2021, "end_year": None}, fetch=None, post=post)
    url, payload = sent[0]
    assert url == "https://data.ssb.no/api/v0/en/table/08307"
    assert payload["response"] == {"format": "json-stat2"}
    assert {"code": "Tid", "selection": {"filter": "item", "values": ["2021"]}} in payload["query"]


def test_monthly_tables_are_rejected_in_describe():
    meta = json.loads((FIX / "scb-TAB4311-metadata.json").read_text())
    assert any(not c.isdigit() for c in next(iter(meta["dimension"]["Tid"]["category"]["index"])))
    candidate = base.DatasetCandidate("pxweb", "scb:TAB4311", "Electricity prices, half-year", "other")
    import pytest

    with pytest.raises(base.DatasetRejected, match="no aggregation"):
        pxweb.describe(candidate, SCOPE, fetch=offline, require_annual=True)
```

`TAB4311` is half-yearly (`2014H2`); the v2 test therefore calls `describe(..., require_annual=False)` because it only checks the request shape, and the last test shows that the stage's call (`require_annual=True`, the default) rejects it. Use an annual SCB table in Task 14's live test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_pxweb.py -q`
Expected: FAIL with `ImportError: cannot import name 'pxweb'`

- [ ] **Step 3: Implement the connector**

```python
# sci_search/data_research/connectors/pxweb.py
"""PxWeb connector for a reviewed list of installations (API v1 and v2), via JSON-stat 2."""

import json
import re
from urllib.parse import quote, urlencode

from sci_search.data_research.connectors import base

NAME = "pxweb"
INSTALLATIONS = {
    "scb": {"host": "statistikdatabasen.scb.se", "version": 2, "base": "https://statistikdatabasen.scb.se/api/v2", "publisher": "Statistics Sweden", "licence": "https://creativecommons.org/licenses/by/4.0/"},
    "ssb": {"host": "data.ssb.no", "version": 1, "base": "https://data.ssb.no/api/v0/en/table", "publisher": "Statistics Norway", "licence": "https://data.norge.no/nlod/en/2.0", "table_from_title": True},
}
HOSTS = {i["host"] for i in INSTALLATIONS.values()}
PUBLISHER = "PxWeb statistical office"
LICENCE_URL = ""


def dataset_from_url(url):
    match = re.match(r"^https://statistikdatabasen\.scb\.se/api/v2/tables/(TAB\d+)", url)
    return "scb:" + match[1] if match else None


def _split(dataset):
    installation, table = dataset.split(":", 1)
    if installation not in INSTALLATIONS or not re.fullmatch(r"[A-Za-z0-9_/\-.]+", table):
        raise base.SelectionError("Unknown PxWeb dataset id")
    return INSTALLATIONS[installation], installation, table


def search(terms, scope, *, fetch, cache_dir):
    candidates = []
    for name, inst in INSTALLATIONS.items():
        for term in terms[:4]:
            if inst["version"] == 2:
                body, _, _ = fetch(f"{inst['base']}/tables?{urlencode({'query': term, 'lang': 'en', 'pageSize': 10})}")
                for t in json.loads(body).get("tables", []):
                    first = t.get("firstPeriod", "")
                    frequency = "annual" if re.fullmatch(r"\d{4}", first) else "other"
                    candidates.append(base.DatasetCandidate(NAME, f"{name}:{t['id']}", t["label"], frequency, first, t.get("lastPeriod", ""), f"{inst['base']}/tables/{t['id']}"))
            else:
                body, _, _ = fetch(f"{inst['base']}/?{urlencode({'query': term})}")
                for t in json.loads(body)[:10]:
                    if inst.get("table_from_title"):
                        number = re.match(r"^(\d{5}):", t.get("title", ""))
                        if not number:
                            continue
                        path = number[1]
                    else:
                        path = (t.get("path", "").rstrip("/") + "/" + t["id"]).lstrip("/")
                    candidates.append(base.DatasetCandidate(NAME, f"{name}:{path}", t["title"], "unknown", landing_url=f"{inst['base']}/{path}"))
    unique = {c.dataset: c for c in candidates}
    ranked = sorted(unique.values(), key=lambda c: -base.score(c.title, terms))
    return ranked[:10], ""


def describe(candidate, scope, *, fetch, require_annual=True):
    inst, _, table = _split(candidate.dataset)
    if inst["version"] == 2:
        body, _, _ = fetch(f"{inst['base']}/tables/{table}/metadata?lang=en&outputFormat=json-stat2")
        meta = json.loads(body)
        time = (meta.get("role") or {}).get("time", [None])[0]
        dims, time_codes = [], []
        for d in meta["id"]:
            category = meta["dimension"][d]["category"]
            index = category.get("index", {})
            codes = sorted(index, key=index.get) if isinstance(index, dict) else list(index)
            if d == time:
                time_codes = codes
                continue
            labels = category.get("label", {})
            dims.append(base.Dimension(d, meta["dimension"][d].get("label", d), {c: labels.get(c, c) for c in codes}))
        definitions = json.dumps({"label": meta.get("label"), "note": meta.get("note"), "units": {d: meta["dimension"][d]["category"].get("unit") for d in meta["id"]}}, ensure_ascii=False)
    else:
        body, _, _ = fetch(f"{inst['base']}/{table.lstrip('/')}")
        meta = json.loads(body)
        dims, time_codes, time = [], [], None
        for v in meta["variables"]:
            if v.get("time"):
                time, time_codes = v["code"], v["values"]
                continue
            dims.append(base.Dimension(v["code"], v["text"], dict(zip(v["values"], v["valueTexts"], strict=True))))
        definitions = json.dumps({"title": meta.get("title")}, ensure_ascii=False)
    years = tuple(y for y in (base.annual(c) for c in time_codes) if y)
    if require_annual and (not time_codes or len(years) != len(time_codes)):
        raise base.DatasetRejected("dataset periods are not annual; no aggregation was performed")
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=tuple(dims),
        years=years,
        licence_url=inst["licence"],
        definitions=definitions[:30000],
        publisher=inst["publisher"],
        extra={"time": time, "time_codes": time_codes},
    )


def _years(description, scope):
    codes = description.extra["time_codes"]
    start, end = scope.get("start_year"), scope.get("end_year")
    chosen = [c for c in codes if (base.annual(c) or 0) >= (start or 0) and (base.annual(c) or 0) <= (end or 9999)]
    if not chosen:
        raise base.DatasetRejected("dataset does not cover the requested years")
    return chosen


def fetch(description, selection, scope, *, fetch, post):
    inst, _, table = _split(description.candidate.dataset)
    years = _years(description, scope) if description.years else description.extra["time_codes"]
    filters = {**selection["filters"], description.extra["time"]: years}
    reader = {
        "reader": "jsonstat2",
        "series_dimensions": selection["series_dimensions"],
        "code_labels": {d.id: d.codes for d in description.dimensions},
        "reason": selection["reason"],
    }
    if inst["version"] == 2:
        params = {"lang": "en", "outputFormat": "json-stat2"}
        params.update({f"valueCodes[{d}]": ",".join(codes) for d, codes in filters.items()})
        url = f"{inst['base']}/tables/{table}/data?{urlencode(params)}"
        raw, _, final = fetch(url)
        request = {"method": "GET", "url": final}
    else:
        url = f"{inst['base']}/{quote(table.lstrip('/'))}"
        payload = {
            "query": [{"code": d, "selection": {"filter": "item", "values": codes}} for d, codes in filters.items()],
            "response": {"format": "json-stat2"},
        }
        raw, _, final = post(url, payload)
        request = {"method": "POST", "url": final, "body": payload}
    return base.Fetched(raw=raw, request=request, selection=reader, artifact="source.json")


def mapping(table, preparation, selection, measurement):
    return base.series_mapping(table, measurement)
```

Register `pxweb` in `connectors/__init__.py._register()`.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_pxweb.py tests/test_jsonstat.py -q`
Expected: all PASS

- [ ] **Step 5: Check further installations before adding them**

Run:
```bash
curl -s -o /dev/null -w '%{http_code}\n' 'https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/?query=electricity'
curl -s -o /dev/null -w '%{http_code}\n' 'https://pxweb.irena.org/api/v1/en/IRENASTAT/?query=renewable'
```
For each that returns 200 with a JSON list of tables, add it to `INSTALLATIONS` as a version-1 entry (`base` without the trailing `/?query`), record a search fixture with the recorder script, and add one search assertion to `test_search_covers_v1_and_v2_installations`. Leave out any installation that does not return 200, and note it in the fixture README.

- [ ] **Step 6: Commit**

```bash
git add sci_search/data_research/connectors tests/test_connector_pxweb.py tests/fixtures/data_research/connectors
git commit -m "Add the PxWeb connector for reviewed installations"
```

---

### Task 9: Our World in Data connector

**Files:**
- Create: `sci_search/data_research/connectors/owid.py`
- Modify: `sci_search/data_research/connectors/__init__.py` (register)
- Test: `tests/test_connector_owid.py`

**Interfaces:**
- Module contract as Task 6, with `NAME = "owid"`, `PUBLISHER = "Our World in Data"`, `HOSTS = {"ourworldindata.org"}`.
- Dataset id is the grapher slug. `describe` downloads the full CSV and metadata into `description.payload` (the JSON envelope from Task 4). Dimensions: `"indicator"` (column short names, labelled `"<titleShort> (<unit>)"`) and `"entity"` (entity names; restricted to `strategy["countries"]` by ISO-3 code when set).
- `fetch` returns `Fetched(raw=payload, request={"method": "GET", "url": csv_url, "csv_sha256": ..., "metadata_sha256": ...}, selection={"reader": "owid_csv", "indicator": ..., "entities": [...], "reason": ...}, artifact="source.json")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_owid.py
from pathlib import Path

from sci_search.data_research.connectors import base, owid
from sci_search.data_research.packages import prepare_table

FIX = Path(__file__).parent / "fixtures/data_research/connectors/owid"


def offline(url):
    if "/api/search?" in url:
        return (FIX / "search.json").read_bytes(), "application/json", url
    if url.startswith("https://ourworldindata.org/grapher/life-expectancy.csv"):
        return (FIX / "life-expectancy.csv").read_bytes(), "text/csv", url
    if url.startswith("https://ourworldindata.org/grapher/life-expectancy.metadata.json"):
        return (FIX / "life-expectancy.metadata.json").read_bytes(), "application/json", url
    raise AssertionError("unexpected request " + url)


SCOPE = {"start_year": 2000, "end_year": 2023, "countries": ["NLD", "DEU"]}


def test_search_returns_chart_slugs(tmp_path):
    candidates, _ = owid.search(["life expectancy"], SCOPE, fetch=offline, cache_dir=tmp_path)
    assert "life-expectancy" in [c.dataset for c in candidates]


def test_describe_restricts_entities_and_fetch_reads_through_reader():
    candidate = base.DatasetCandidate("owid", "life-expectancy", "Life expectancy", "annual")
    description = owid.describe(candidate, SCOPE, fetch=offline)
    dims = {d.id: d for d in description.dimensions}
    assert set(dims["entity"].codes) == {"Germany", "Netherlands"}
    indicator = next(iter(dims["indicator"].codes))
    selection = {"filters": {"indicator": [indicator], "entity": ["Germany", "Netherlands"]}, "series_dimensions": ["entity"], "reason": "Requested"}
    fetched = owid.fetch(description, selection, SCOPE, fetch=offline, post=None)
    table, prep = prepare_table(fetched.raw, fetched.selection)
    mapping = owid.mapping(table, prep, selection, "life expectancy")
    assert mapping["unit"] == "years" and set(mapping["entities"]) == {"Germany", "Netherlands"}
    assert len(fetched.request["csv_sha256"]) == 64


def test_dataset_from_url():
    assert owid.dataset_from_url("https://ourworldindata.org/grapher/life-expectancy?tab=chart") == "life-expectancy"
    assert owid.dataset_from_url("https://ourworldindata.org/life-expectancy") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_owid.py -q`
Expected: FAIL with `ImportError: cannot import name 'owid'`

- [ ] **Step 3: Implement the connector**

```python
# sci_search/data_research/connectors/owid.py
"""Our World in Data connector: chart search, grapher CSV and metadata."""

import csv
import hashlib
import io
import json
import re
from urllib.parse import urlencode, urlsplit

from sci_search.data_research.connectors import base

NAME = "owid"
PUBLISHER = "Our World in Data"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
HOSTS = {"ourworldindata.org"}
GRAPHER = "https://ourworldindata.org/grapher/"


def dataset_from_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        return None
    match = re.fullmatch(r"/grapher/([a-z0-9-]+)", parts.path)
    return match[1] if match else None


def search(terms, scope, *, fetch, cache_dir):
    found = {}
    for term in terms[:4]:
        body, _, _ = fetch("https://ourworldindata.org/api/search?" + urlencode({"q": term}))
        for result in json.loads(body).get("results", []):
            if result.get("type") == "chart" and re.fullmatch(r"[a-z0-9-]+", result.get("slug", "")):
                found.setdefault(result["slug"], result.get("title", result["slug"]))
    ranked = sorted(found.items(), key=lambda item: -base.score(item[1], terms))
    return [base.DatasetCandidate(NAME, slug, title, "annual", landing_url=GRAPHER + slug) for slug, title in ranked[:10]], ""


def describe(candidate, scope, *, fetch):
    slug = candidate.dataset
    csv_body, _, _ = fetch(f"{GRAPHER}{slug}.csv?v=1&csvType=full&useColumnShortNames=true")
    meta_body, _, _ = fetch(f"{GRAPHER}{slug}.metadata.json?v=1")
    metadata = json.loads(meta_body)
    columns = metadata.get("columns", {})
    reader = csv.DictReader(io.StringIO(csv_body.decode("utf-8-sig")))
    rows = list(reader)
    codes = {r["entity"]: r.get("code", "") for r in rows}
    wanted = set(scope.get("countries") or [])
    entities = {e: e for e, code in codes.items() if not wanted or code in wanted}
    shortnames = [c for c in reader.fieldnames or [] if c not in {"entity", "code", "year"}]
    indicators = {}
    for short in shortnames:
        info = next((v for v in columns.values() if v.get("shortName") == short), {})
        indicators[short] = f"{info.get('titleShort', short)} ({info.get('unit', '')})"
    years = tuple(sorted({int(r["year"]) for r in rows if re.fullmatch(r"\d{4}", r["year"])}))
    envelope = json.dumps({"csv": csv_body.decode("utf-8-sig"), "metadata": {"columns": {v.get("shortName", k): v for k, v in columns.items()}}}, ensure_ascii=False).encode()
    return base.DatasetDescription(
        candidate=candidate,
        dimensions=(base.Dimension("indicator", "Indicator", indicators), base.Dimension("entity", "Entity", entities)),
        years=years,
        licence_url=LICENCE_URL,
        definitions=json.dumps(columns, ensure_ascii=False)[:30000],
        publisher=PUBLISHER,
        payload=envelope,
        extra={"csv_sha256": hashlib.sha256(csv_body).hexdigest(), "metadata_sha256": hashlib.sha256(meta_body).hexdigest()},
    )


def fetch(description, selection, scope, *, fetch, post):
    slug = description.candidate.dataset
    return base.Fetched(
        raw=description.payload,
        request={
            "method": "GET",
            "url": f"{GRAPHER}{slug}.csv?v=1&csvType=full&useColumnShortNames=true",
            "csv_sha256": description.extra["csv_sha256"],
            "metadata_sha256": description.extra["metadata_sha256"],
        },
        selection={
            "reader": "owid_csv",
            "indicator": selection["filters"]["indicator"][0],
            "entities": selection["filters"]["entity"],
            "reason": selection["reason"],
        },
        artifact="source.json",
    )


def mapping(table, preparation, selection, measurement):
    return base.series_mapping(table, measurement)
```

The Task 4 reader keys `metadata["columns"]` by short name, which is why `describe` re-keys the columns by `shortName` in the envelope.

Register `owid` in `connectors/__init__.py._register()`.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_owid.py tests/test_owid_tables.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sci_search/data_research/connectors tests/test_connector_owid.py
git commit -m "Add the Our World in Data connector"
```

---

### Task 10: Connector stage (main path)

**Files:**
- Create: `sci_search/data_research/connectors/stage.py`
- Test: `tests/test_connector_stage.py`

**Interfaces:**
- Consumes: `connectors.CONNECTORS`; each connector's `search`, `describe`, `fetch`, `mapping`; `packages.prepare_table`, `packages.attach_provenance`; `tabular.analyse_csv`; `semantics.assess`; `artifacts.execute_analysis`; `workflow.save` (import from `sci_search.data_research.workflow` lazily to avoid a cycle; or copy the two-line `save` helper).
- Produces: `run(question: str, strategy: dict, directory: Path, *, complete, fetch, post, check_cancelled, progress, connectors: dict | None = None, cache_dir: Path | None = None) -> dict` returning `{"analyses": [...], "assessments": [...], "covered": [measurements], "search": {"terms": ..., "candidates": [...], "catalogues": {name: sha256}}}`.
- Produces: `analyse_dataset(question, strategy, directory, connector, candidate: DatasetCandidate, measurement: str, *, complete, fetch, post, check_cancelled, progress) -> tuple[dict | None, dict]` returning `(analysis or None, assessment)`. Used again by workflow rerouting (Task 12).
- Model schemas (module constants): `TERMS_SCHEMA`, `CHOICE_SCHEMA`, and `selection_schema(description) -> dict` with one property per dimension whose items enum is the observed codes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_stage.py
from pathlib import Path

from sci_search.data_research.connectors import base, stage
from tests.data_meaning_fixtures import with_positive_meaning_review

FIX = Path(__file__).parent / "fixtures/data_research/connectors/eurostat"


def offline(url):
    from tests.test_connector_eurostat import offline as eurostat_offline

    return eurostat_offline(url)


STRATEGY = {
    "adapter": "discovered_data_v1",
    "route": "data",
    "rationale": "Annual statistics",
    "measurements": ["life expectancy at birth"],
    "geography": "Netherlands, Germany and Greece",
    "country_scope": "other",
    "countries": ["NLD", "DEU", "GRC"],
    "start_year": 2000,
    "end_year": 2024,
}


def scripted(prompt, schema):
    title = schema.get("title", "")
    if title == "connector_terms":
        return {"terms": [{"measurement": "life expectancy at birth", "terms": ["life expectancy", "sex"]}]}
    if title == "connector_choice":
        return {"choices": [{"candidate": "eurostat:demo_mlexpec", "measurement": "life expectancy at birth", "reason": "Annual by sex and country"}]}
    if title == "connector_selection":
        return {
            "filters": {"freq": ["A"], "unit": ["YR"], "sex": ["F", "M"], "age": ["Y_LT1"], "geo": ["NL", "DE", "EL"]},
            "series_dimensions": ["sex", "geo"],
            "reason": "Birth, both sexes, requested countries",
        }
    raise AssertionError("unexpected model call " + title)


def test_stage_produces_an_executed_analysis(tmp_path):
    from sci_search.data_research.connectors import eurostat

    result = stage.run(
        "How has life expectancy changed for men and women in NL, DE and GR?",
        STRATEGY,
        tmp_path,
        complete=with_positive_meaning_review(scripted),
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )
    assert result["covered"] == ["life expectancy at birth"]
    analysis = result["analyses"][0]
    assert analysis["execution"]["status"] == "verified"
    assert analysis["source"]["connector"]["dataset"] == "demo_mlexpec"
    assert "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/" in analysis["source"]["connector"]["request"]["url"]
    assert len(analysis["series"]) == 6
    assert result["assessments"][0]["decision"] == "analysed"


def test_selection_schema_enumerates_observed_codes():
    description = base.DatasetDescription(
        candidate=base.DatasetCandidate("x", "d", "t", "annual"),
        dimensions=(base.Dimension("geo", "Country", {"NL": "Netherlands"}),),
        years=(),
        licence_url="",
        definitions="",
        publisher="",
    )
    schema = stage.selection_schema(description)
    assert schema["properties"]["filters"]["properties"]["geo"]["items"]["enum"] == ["NL"]
    assert schema["properties"]["series_dimensions"]["items"]["enum"] == ["geo"]
```

`with_positive_meaning_review` (existing helper in `tests/data_meaning_fixtures.py`) answers the semantic review call and forwards the other calls to `scripted`. If it does not forward a `title`, check its implementation and pass the schema through unchanged; the three stage schemas carry a `"title"` key for this reason.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_stage.py -q`
Expected: FAIL with `ImportError: cannot import name 'stage'`

- [ ] **Step 3: Implement the stage**

```python
# sci_search/data_research/connectors/stage.py
"""Connector stage: search terms, dataset choice, code selection, analysis and recovery."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sci_search.data_research import semantics
from sci_search.data_research.artifacts import execute_analysis
from sci_search.data_research.connectors import CONNECTORS, base
from sci_search.data_research.packages import attach_provenance, prepare_table
from sci_search.data_research.tabular import analyse_csv, read_csv

TERMS_SCHEMA = {
    "title": "connector_terms",
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["measurement", "terms"],
                "properties": {
                    "measurement": {"type": "string"},
                    "terms": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                },
            },
        }
    },
}
CHOICE_SCHEMA = {
    "title": "connector_choice",
    "type": "object",
    "additionalProperties": False,
    "required": ["choices"],
    "properties": {
        "choices": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["candidate", "measurement", "reason"],
                "properties": {"candidate": {"type": "string"}, "measurement": {"type": "string"}, "reason": {"type": "string"}},
            },
        }
    },
}


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def selection_schema(description):
    dims = [d.id for d in description.dimensions]
    return {
        "title": "connector_selection",
        "type": "object",
        "additionalProperties": False,
        "required": ["filters", "series_dimensions", "reason"],
        "properties": {
            "filters": {
                "type": "object",
                "additionalProperties": False,
                "required": dims,
                "properties": {
                    d.id: {"type": "array", "minItems": 1, "items": {"type": "string", "enum": sorted(d.codes)}}
                    for d in description.dimensions
                },
            },
            "series_dimensions": {"type": "array", "items": {"type": "string", "enum": dims}},
            "reason": {"type": "string"},
        },
    }


def _terms(question, strategy, complete):
    try:
        reply = complete(
            "For each requested measurement give 2 to 4 short search terms for official statistics "
            "catalogues, in English and also in Dutch for Dutch statistics. Do not name datasets.\n"
            + json.dumps({"question": question, "measurements": strategy["measurements"], "geography": strategy["geography"]}),
            TERMS_SCHEMA,
        )
        terms = {t["measurement"]: [x for x in t["terms"] if x.strip()][:4] for t in reply["terms"]}
    except (ValueError, KeyError, TypeError):
        terms = {}
    return {m: terms.get(m) or [m] for m in strategy["measurements"]}


def analyse_dataset(question, strategy, directory, connector, candidate, measurement, *, complete, fetch, post, check_cancelled, progress, catalogue_sha256=""):
    folder = Path(directory) / f"connector-{connector.NAME}-{candidate.dataset.replace('/', '_').replace(':', '_')}"
    folder.mkdir(parents=True, exist_ok=True)
    assessment = {
        "title": candidate.title,
        "url": candidate.landing_url,
        "publisher": getattr(connector, "PUBLISHER", connector.NAME),
        "connector": connector.NAME,
        "dataset": candidate.dataset,
        "measurement": measurement,
        "decision": "blocked",
    }
    stage_name = "connector:describe"
    try:
        check_cancelled()
        description = connector.describe(candidate, strategy, fetch=fetch)
        stage_name = "connector:selection"
        proposal = complete(
            "Choose the codes that answer the requested measurement. Use only listed codes. Fix every "
            "non-series dimension to one code; series dimensions may have several (e.g. countries, sexes). "
            "Keep totals and their components apart.\n"
            + json.dumps({"question": question, "measurement": measurement, "scope": strategy, "dataset": candidate.title, "dimensions": [{"id": d.id, "label": d.label, "codes": d.codes} for d in description.dimensions]}, ensure_ascii=False),
            selection_schema(description),
        )
        selection = base.validate_selection(description, proposal)
        assessment["selection"] = selection
        stage_name = "connector:fetch"
        progress(f"Requesting {candidate.title[:100]} from the {connector.NAME} API.")
        fetched = connector.fetch(description, selection, strategy, fetch=fetch, post=post)
        stage_name = "connector:normalize"
        try:
            table, preparation = prepare_table(fetched.raw, fetched.selection)
        except (ValueError, KeyError, TypeError) as exc:
            raise base.ReaderError(str(exc)) from exc
        mapping = connector.mapping(table, preparation, selection, measurement)
        analysis = analyse_csv(table, mapping, strategy)
        attach_provenance(analysis, preparation)
        analysis["limitations"] += list(fetched.notes) + preparation.get("limitations", [])
        source = {
            "title": candidate.title,
            "url": fetched.request["url"],
            "landing_url": candidate.landing_url,
            "publisher": description.publisher,
            "definition": description.definitions[:500],
            "license_url": description.licence_url,
            "license_note": "Licence from the dataset metadata: " + description.licence_url,
            "sha256": hashlib.sha256(fetched.raw).hexdigest(),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "artifact": fetched.artifact,
            "connector": {
                "name": connector.NAME,
                "dataset": candidate.dataset,
                "request": fetched.request,
                "catalogue_sha256": catalogue_sha256,
                "selection": selection,
            },
        }
        (folder / fetched.artifact).write_bytes(fetched.raw)
        (folder / "source.csv").write_bytes(table)
        analysis = {
            **analysis,
            "components": [copy.deepcopy(analysis)],
            "kind": "tabular",
            "source": source,
            "preparation": {**preparation, "selection": fetched.selection} if fetched.selection else preparation,
        }
        stage_name = "connector:meaning"
        _, rows = read_csv(table)
        documents = {"metadata": description.definitions, "table_sample": json.dumps(rows[:12], ensure_ascii=False)}
        review = semantics.assess(question=question, scope=strategy, analysis=analysis, documents=documents, complete=complete)
        assessment.setdefault("semantic_reviews", []).append(review)
        save(folder / "semantic-review.json", {"review": review, "evidence_documents": documents})
        if not review["accepted"]:
            raise base.DatasetRejected("Measurement meaning not confirmed: " + review["reason"])
        analysis["semantic_review"] = review
        stage_name = "execution"
        analysis = execute_analysis(analysis, folder, check_cancelled=check_cancelled)
        save(folder / "analysis.json", analysis)
        assessment.update(decision="analysed", reason=selection["reason"] or "Selected from dataset metadata", source=source)
        return analysis, assessment
    except (ValueError, KeyError, TypeError, OSError) as exc:
        assessment.update(reason=str(exc)[:700], failure_stage=stage_name, error_class=type(exc).__name__)
        if isinstance(exc, base.SelectionError):
            assessment["facts"] = exc.facts
        return None, assessment


def run(question, strategy, directory, *, complete, fetch, post, check_cancelled, progress, connectors=None, cache_dir=None):
    connectors = CONNECTORS if connectors is None else connectors
    directory = Path(directory)
    cache_dir = Path(cache_dir) if cache_dir else directory / "catalogues"
    result = {"analyses": [], "assessments": [], "covered": [], "search": {"terms": {}, "candidates": [], "catalogues": {}}}
    terms = _terms(question, strategy, complete)
    result["search"]["terms"] = terms
    found = {}
    for name, connector in connectors.items():
        check_cancelled()
        try:
            candidates, digest = connector.search(sorted({t for ts in terms.values() for t in ts}), strategy, fetch=fetch, cache_dir=cache_dir)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result["assessments"].append({"title": f"{name} catalogue", "connector": name, "decision": "blocked", "reason": str(exc)[:500], "failure_stage": "connector:search"})
            continue
        result["search"]["catalogues"][name] = digest
        for c in candidates:
            found[f"{name}:{c.dataset}"] = (connector, c)
    result["search"]["candidates"] = [{"key": k, "title": c.title, "frequency": c.frequency} for k, (_, c) in found.items()]
    if not found:
        return result
    choice = complete(
        "Choose at most 4 datasets that measure the requested measurements. Prefer annual series that "
        "cover the requested years; do not choose monthly or quarterly datasets.\n"
        + json.dumps({"question": question, "scope": strategy, "candidates": result["search"]["candidates"]}, ensure_ascii=False),
        CHOICE_SCHEMA,
    )
    for item in choice["choices"][:4]:
        if item["candidate"] not in found or item["measurement"] not in strategy["measurements"]:
            continue
        if item["measurement"] in result["covered"]:
            continue
        connector, candidate = found[item["candidate"]]
        analysis, assessment = analyse_dataset(
            question, strategy, directory, connector, candidate, item["measurement"],
            complete=complete, fetch=fetch, post=post, check_cancelled=check_cancelled, progress=progress,
            catalogue_sha256=result["search"]["catalogues"].get(connector.NAME, ""),
        )
        assessment["choice_reason"] = item["reason"]
        result["assessments"].append(assessment)
        if analysis:
            result["analyses"].append(analysis)
            result["covered"].append(item["measurement"])
    return result
```

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_stage.py -q`
Expected: all PASS. If `execute_analysis` fails with "Executed Python calculations differ", compare `folder/calculation/output/result.json` with `analysis.json`: the analysis must not hold values the sandbox cannot recompute (keep extra fields under `source` or `assessment`).

- [ ] **Step 5: Commit**

```bash
git add sci_search/data_research/connectors/stage.py tests/test_connector_stage.py
git commit -m "Add the connector stage that turns API datasets into executed analyses"
```

---

### Task 11: Automatic recovery in the connector stage

**Files:**
- Modify: `sci_search/data_research/connectors/stage.py`
- Test: `tests/test_connector_recovery.py`

**Interfaces:**
- Consumes: `analyse_dataset` and `run` from Task 10; `python_recovery.recover_python` (signature as used at `workflow.py:425-436`: `recover_python(question, strategy, data, source, folder, *, complete, reason, metadata, check_cancelled, progress)`).
- Produces: the recovery table from the spec, recorded in each assessment as `assessment["recovery"] = [{"class": ..., "action": ..., "outcome": ...}]`.
  - `SelectionError` → up to 2 repairs: the model receives the error message and `exc.facts`, and proposes a new selection.
  - `DatasetRejected` (meaning, frequency, coverage) → next chosen candidate; after all candidates for a measurement fail, one extra round: the model reformulates search terms given the rejection reasons, and the stage searches and chooses again for that measurement.
  - Transient (`OSError`, or `ValueError` whose message contains `HTTP 5`) → one retry of the same step.
  - `ReaderError` → `recover_python` on the same raw bytes, then `execute_analysis`.
  - No candidates for any term → the reformulation round runs once; then the measurement is left uncovered with an assessment `{"decision": "blocked", "failure_stage": "connector:search", "reason": "No connector dataset found after reformulated search"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_recovery.py
from sci_search.data_research.connectors import base, eurostat, stage
from tests.data_meaning_fixtures import with_positive_meaning_review
from tests.test_connector_eurostat import offline
from tests.test_connector_stage import STRATEGY

GOOD = {
    "filters": {"freq": ["A"], "unit": ["YR"], "sex": ["F", "M"], "age": ["Y_LT1"], "geo": ["NL", "DE", "EL"]},
    "series_dimensions": ["sex", "geo"],
    "reason": "Birth, both sexes",
}


def model(selections, *, terms=(["life expectancy"], ["life expectancy"]), choices=None):
    # Two term replies: the first search and the reformulation round for uncovered measurements.
    replies = {"selection": iter(selections), "terms": iter(terms)}
    seen = []

    def complete(prompt, schema):
        seen.append(schema.get("title"))
        if schema.get("title") == "connector_terms":
            return {"terms": [{"measurement": STRATEGY["measurements"][0], "terms": next(replies["terms"])}]}
        if schema.get("title") == "connector_choice":
            return choices or {"choices": [{"candidate": "eurostat:demo_mlexpec", "measurement": STRATEGY["measurements"][0], "reason": "Annual"}]}
        if schema.get("title") == "connector_selection":
            return next(replies["selection"])
        raise AssertionError(schema.get("title"))

    return with_positive_meaning_review(complete), seen


def run(tmp_path, complete, fetch=offline):
    return stage.run("Life expectancy", STRATEGY, tmp_path, complete=complete, fetch=fetch, post=None,
                     check_cancelled=lambda: None, progress=lambda m: None,
                     connectors={"eurostat": eurostat}, cache_dir=tmp_path / "cache")


def test_wrong_code_is_repaired_with_the_valid_codes(tmp_path):
    bad = {**GOOD, "filters": {**GOOD["filters"], "sex": ["X"]}}
    complete, seen = model([bad, GOOD])
    result = run(tmp_path, complete)
    assert result["covered"] == STRATEGY["measurements"]
    recovery = result["assessments"][0]["recovery"]
    assert recovery[0]["class"] == "selection" and recovery[0]["outcome"] == "repaired"


def test_repairs_stop_after_two_attempts(tmp_path):
    bad = {**GOOD, "filters": {**GOOD["filters"], "sex": ["X"]}}
    complete, _ = model([bad, bad, bad])
    result = run(tmp_path, complete)
    assert result["covered"] == []
    assert [r["class"] for r in result["assessments"][0]["recovery"]] == ["selection", "selection"]


def test_transient_errors_are_retried_once(tmp_path):
    calls = {"n": 0}

    def flaky(url):
        if "/data/demo_mlexpec/A.YR.F+M" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("Dataset server returned HTTP 503")
        return offline(url)

    complete, _ = model([GOOD])
    assert run(tmp_path, complete, flaky)["covered"] == STRATEGY["measurements"]


def test_no_candidates_triggers_one_reformulated_search(tmp_path):
    complete, seen = model([GOOD], terms=(["zzzz nothing"], ["still nothing"]))
    result = run(tmp_path, complete)
    assert seen.count("connector_terms") == 2
    assert result["assessments"][-1]["reason"] == "No connector dataset found after reformulated search"


def test_reader_failures_go_to_python_recovery(tmp_path, monkeypatch):
    called = {}

    def fake_recover(question, strategy, data, source, folder, **kwargs):
        called["bytes"] = len(data)
        raise ValueError("Python extraction stopped after 3 attempt(s)")

    monkeypatch.setattr(stage, "recover_python", fake_recover)
    monkeypatch.setattr(stage, "prepare_table", lambda raw, selection: (_ for _ in ()).throw(ValueError("unknown layout")))
    complete, _ = model([GOOD])
    result = run(tmp_path, complete)
    assert called["bytes"] > 0
    assert result["assessments"][0]["recovery"][-1]["class"] == "reader"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_recovery.py -q`
Expected: FAIL (`KeyError: 'recovery'` and missing `recover_python` attribute)

- [ ] **Step 3: Implement recovery**

In `stage.py`:

1. Add `from sci_search.data_research.python_recovery import recover_python` at module level.

2. Add a retry helper and use it around `connector.describe` and `connector.fetch`:

```python
def _transient(exc):
    return isinstance(exc, OSError) or (isinstance(exc, ValueError) and "HTTP 5" in str(exc))


def _with_retry(step, recovery):
    try:
        return step()
    except (OSError, ValueError) as exc:
        if not _transient(exc) or isinstance(exc, base.SelectionError):
            raise
        recovery.append({"class": "transient", "action": "retry", "outcome": str(exc)[:200]})
        return step()
```

3. In `analyse_dataset`, set `assessment["recovery"] = []`, call describe and fetch via `_with_retry(lambda: ..., assessment["recovery"])`, and replace the single proposal/validation/fetch sequence with a loop of at most 3 selection attempts:

```python
        feedback = None
        for attempt in range(3):
            prompt_facts = {"previous_error": feedback} if feedback else {}
            proposal = complete(SELECT_PROMPT + json.dumps({...existing payload..., **prompt_facts}, ensure_ascii=False), selection_schema(description))
            try:
                selection = base.validate_selection(description, proposal)
                fetched = _with_retry(lambda: connector.fetch(description, selection, strategy, fetch=fetch, post=post), assessment["recovery"])
                break
            except base.SelectionError as exc:
                if attempt == 2:
                    raise
                feedback = {"error": str(exc), "facts": exc.facts}
                assessment["recovery"].append({"class": "selection", "action": "repair", "outcome": str(exc)[:200]})
        if assessment["recovery"] and assessment["recovery"][-1]["class"] == "selection":
            assessment["recovery"][-1]["outcome"] = "repaired"
```

Keep the earlier `outcome` messages for failed attempts and mark only the final successful repair `"repaired"`. Move the existing selection prompt text into a module constant `SELECT_PROMPT`.

4. Wrap the normalize step so a `ReaderError` goes to Python recovery:

```python
        try:
            table, preparation = prepare_table(fetched.raw, fetched.selection)
        except (ValueError, KeyError, TypeError) as exc:
            assessment["recovery"].append({"class": "reader", "action": "python_recovery", "outcome": str(exc)[:200]})
            (folder / fetched.artifact).write_bytes(fetched.raw)
            source = {...same source dict as below, built before this try...}
            analysis = recover_python(question, strategy, fetched.raw, source, folder, complete=complete,
                                      reason="Connector reader could not read the response: " + str(exc)[:300],
                                      metadata=description.definitions, check_cancelled=check_cancelled, progress=progress)
            analysis = execute_analysis(analysis, folder, check_cancelled=check_cancelled)
            save(folder / "analysis.json", analysis)
            assessment.update(decision="analysed", reason="Recovered with executed Python extraction", source=source)
            return analysis, assessment
```

Build the `source` dict before this `try` so both paths use it (the `artifact` is known from `fetched`).

5. In `run`, after the candidate loop, for each measurement still uncovered (including the case of no candidates at all), run one reformulation round:

```python
    for measurement in [m for m in strategy["measurements"] if m not in result["covered"]]:
        reasons = [a.get("reason", "") for a in result["assessments"] if a.get("measurement") == measurement]
        reply = complete(
            "The previous searches did not yield a usable dataset. Using the reasons below, give 2 to 4 "
            "different search terms for this measurement.\n"
            + json.dumps({"measurement": measurement, "previous_terms": terms[measurement], "reasons": reasons}, ensure_ascii=False),
            TERMS_SCHEMA,
        )
        retry_terms = next((t["terms"] for t in reply["terms"] if t["measurement"] == measurement), [])
        found_again = _search_all(connectors, retry_terms, strategy, fetch, cache_dir, result)
        tried = {a.get("dataset") for a in result["assessments"] if a.get("measurement") == measurement}
        fresh = {k: v for k, v in found_again.items() if v[1].dataset not in tried}
        if not fresh:
            result["assessments"].append({"title": "Connector search", "measurement": measurement, "decision": "blocked",
                                          "failure_stage": "connector:search",
                                          "reason": "No connector dataset found after reformulated search"})
            continue
        _choose_and_analyse(question, strategy, directory, fresh, [measurement], result, complete=complete, fetch=fetch,
                            post=post, check_cancelled=check_cancelled, progress=progress)
```

Extract the search loop into `_search_all(connectors, terms, strategy, fetch, cache_dir, result) -> dict` and the choice-and-analyse loop into `_choose_and_analyse(question, strategy, directory, found, measurements, result, *, complete, fetch, post, check_cancelled, progress)` so `run` uses them for both rounds. `_choose_and_analyse` only considers choices whose `measurement` is in `measurements`.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_recovery.py tests/test_connector_stage.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sci_search/data_research/connectors/stage.py tests/test_connector_recovery.py
git commit -m "Recover automatically from connector selection, transient and reader errors"
```

---

### Task 12: Workflow integration, rerouting and connector gaps

**Files:**
- Modify: `sci_search/data_research/workflow.py` (`execute`, candidate loop)
- Test: `tests/test_connector_workflow.py`

**Interfaces:**
- Consumes: `connectors.enabled()`, `connectors.CONNECTORS`, `connectors.dataset_from_url`, `stage.run`, `stage.analyse_dataset`, `retrieval.post_public`.
- Produces in the result: connector analyses in `result["analyses"]`, their assessments in `result["assessments"]`, `result["connector_search"]` (terms, candidates, catalogue hashes), and `result["connector_gaps"] = [{"host", "measurement", "evidence"}]`.
- `execute` gains keyword `post=None` (defaults to `post_public`) and `connectors=None` (defaults to `CONNECTORS`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_workflow.py
from sci_search.data_research import workflow
from sci_search.data_research.connectors import eurostat
from tests.test_connector_recovery import GOOD, model
from tests.test_connector_eurostat import offline
from tests.test_connector_stage import STRATEGY


def test_connector_analysis_skips_web_search_when_everything_is_covered(tmp_path):
    complete, _ = model([GOOD])

    def no_search(*a, **k):
        raise AssertionError("web search should not run")

    result = workflow.execute("Life expectancy", STRATEGY, tmp_path, search=no_search, fetch=offline,
                              complete=complete, connectors={"eurostat": eurostat})
    assert result["analyses"] and result["analyses"][0]["source"]["connector"]["name"] == "eurostat"


def test_uncovered_measurements_go_to_web_search_only(tmp_path):
    strategy = {**STRATEGY, "measurements": [*STRATEGY["measurements"], "healthy life years"]}
    complete, _ = model([GOOD])
    searched = {}

    def search(question, scope, **kwargs):
        searched["measurements"] = scope["measurements"]
        return {"candidates": []}

    workflow.execute("Life expectancy", strategy, tmp_path, search=search, fetch=offline,
                     complete=complete, connectors={"eurostat": eurostat})
    assert searched["measurements"] == ["healthy life years"]


def test_connectors_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")
    calls = {}

    def search(question, scope, **kwargs):
        calls["search"] = True
        return {"candidates": []}

    def fetch(url):
        raise AssertionError("no connector request expected: " + url)

    complete, seen = model([])
    workflow.execute("Life expectancy", STRATEGY, tmp_path, search=search, fetch=fetch,
                     complete=complete, connectors={"eurostat": eurostat})
    assert calls["search"] and "connector_terms" not in seen


def test_web_candidate_on_a_connector_host_is_rerouted(tmp_path):
    strategy = {**STRATEGY, "measurements": ["life expectancy at birth"]}
    # First round finds nothing (terms that match no dataflow), then web search returns a Eurostat page.
    complete, _ = model([GOOD], terms=(["zzzz"], ["zzzz"]),
                        choices={"choices": []})

    def search(question, scope, **kwargs):
        return {"candidates": [{"url": "https://ec.europa.eu/eurostat/databrowser/view/demo_mlexpec/default/table",
                                "title": "Life expectancy", "publisher": "Eurostat", "rationale": "Official"}]}

    result = workflow.execute("Life expectancy", strategy, tmp_path, search=search, fetch=offline,
                              complete=complete, connectors={"eurostat": eurostat})
    assert result["analyses"][0]["source"]["connector"]["dataset"] == "demo_mlexpec"


def test_script_only_pages_are_recorded_as_connector_gaps(tmp_path):
    strategy = {**STRATEGY, "measurements": ["river discharge"], "countries": []}
    complete, _ = model([], terms=(["zzzz"], ["zzzz"]), choices={"choices": []})

    def search(question, scope, **kwargs):
        return {"candidates": [{"url": "https://waterinfo.rws.nl/#!/nav/index/", "title": "Waterinfo",
                                "publisher": "Rijkswaterstaat", "rationale": "Official"}]}

    def fetch(url):
        if "waterinfo" in url:
            return b"<html><body>Loading...</body></html>", "text/html", url
        return offline(url)

    result = workflow.execute("Rhine discharge", strategy, tmp_path, search=search, fetch=fetch,
                              complete=complete, connectors={"eurostat": eurostat})
    assert result["connector_gaps"] == [{"host": "waterinfo.rws.nl", "measurement": "river discharge",
                                         "evidence": result["connector_gaps"][0]["evidence"]}]
```

The last test's `complete` must also answer the existing web-path source assessment call. Extend `model` in `tests/test_connector_recovery.py` with a fallback for schemas without a `title` that returns the existing "unsupported" assessment shape used in `tests/test_autonomous_data.py` (`adapter="unsupported"`, `download_link_index=-1`, `reason="Page shows only a loading message"`, `definition_quote=""`, `license_note="Unknown"`, `covered_measurements=[]`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_workflow.py -q`
Expected: FAIL (`execute()` got an unexpected keyword argument 'connectors')

- [ ] **Step 3: Integrate the stage in `execute`**

In `workflow.execute` (after the `result = {...}` block and `finish()` definition, before `progress("Searching the web ...")`):

```python
    from sci_search.data_research import connectors as connector_registry
    from sci_search.data_research.connectors import stage as connector_stage
    from sci_search.data_research.retrieval import post_public

    post = post or post_public
    available = connector_registry.CONNECTORS if connectors is None else connectors
    web_strategy = strategy
    if connector_registry.enabled() and available:
        progress("Searching official statistics catalogues.")
        staged = connector_stage.run(
            question, strategy, directory / "connectors", complete=complete, fetch=fetch, post=post,
            check_cancelled=check_cancelled, progress=progress, connectors=available,
        )
        result["analyses"] += staged["analyses"]
        result["assessments"] += staged["assessments"]
        result["connector_search"] = staged["search"]
        remaining = [m for m in strategy["measurements"] if m not in staged["covered"]]
        if not remaining:
            result["status"] = "complete"
            return finish()
        web_strategy = {**strategy, "measurements": remaining}
```

Then pass `web_strategy` instead of `strategy` to `search(...)` and use it for the rest of the web path (`source_schema` enum, mapping prompts). The simplest safe change: right after the block above, `strategy_for_result = strategy; strategy = web_strategy`, and keep `result["strategy"] = strategy_for_result`. Check `finish()` and `period_summary(strategy, ...)`: pass `strategy_for_result` there so the period summary covers all measurements.

Add `post=None, connectors=None` to the `execute` signature. Check how `result["status"]` is set at the end of the existing web path (grep `result["status"]`) and set it the same way when connector analyses exist.

- [ ] **Step 4: Reroute web candidates on connector hosts**

At the start of the candidate loop body in `execute` (where `candidate["url"]` is first read, before `fetch_scoped`), add:

```python
        routed = connector_registry.dataset_from_url(candidate["url"]) if connector_registry.enabled() else None
        if routed and routed[0] in available:
            name, dataset = routed
            from sci_search.data_research.connectors.base import DatasetCandidate

            for measurement in [m for m in strategy["measurements"] if m not in covered]:
                analysis, routed_assessment = connector_stage.analyse_dataset(
                    question, strategy, directory / "connectors", available[name],
                    DatasetCandidate(name, dataset, candidate["title"], "unknown", landing_url=candidate["url"]),
                    measurement, complete=complete, fetch=fetch, post=post,
                    check_cancelled=check_cancelled, progress=progress,
                )
                routed_assessment["rerouted_from"] = candidate["url"]
                result["assessments"].append(routed_assessment)
                if analysis:
                    result["analyses"].append(analysis)
                    covered.add(measurement)
            if all(m in covered for m in strategy["measurements"]):
                continue
```

When the rerouted analysis fails, the loop continues into the existing scraper path for the same candidate (no `continue`), so nothing that works today is lost.

- [ ] **Step 5: Record connector gaps**

In the `except` block of the candidate loop (where `assessment["failure_stage"] = stage` is set), add after it:

```python
            text = (page or {}).get("text", "") if "page" in locals() else ""
            links = (page or {}).get("links", []) if "page" in locals() else []
            if stage in {"assessment", "navigation", "parse"} and (
                (len(text) < 300 and not links)
                or re.search(r"\b(loading|enable javascript|javascript is required)\b", text, re.I)
            ):
                host = urlsplit(candidate["url"]).hostname or ""
                gaps = result.setdefault("connector_gaps", [])
                if host and not any(g["host"] == host for g in gaps):
                    gaps.append({"host": host, "measurement": ", ".join(strategy["measurements"]), "evidence": str(exc)[:200]})
```

Some JavaScript-shell candidates are rejected without raising (the model returns `adapter="unsupported"` and the loop records `decision="blocked"`). Find that branch (grep `"unsupported"` in `workflow.py`) and apply the same check there via a small helper `_record_gap(result, candidate, strategy, page, reason)` used by both places.

- [ ] **Step 6: Run the tests, including the existing workflow tests**

Run: `uv run python -m pytest tests/test_connector_workflow.py tests/test_autonomous_data.py tests/test_adaptive_data.py tests/test_research_reflection.py tests/test_wildfire_data.py tests/test_excel_research.py -q`
Expected: all PASS. Existing tests pass `search=` and `fetch=` stubs that know nothing about connector catalogues; if a test now fails because the connector stage requested a catalogue URL, set `monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", "0")` for the whole module via an autouse fixture in those test files, since they test the web path.

- [ ] **Step 7: Commit**

```bash
git add sci_search/data_research/workflow.py tests/test_connector_workflow.py tests/test_connector_recovery.py tests/*.py
git commit -m "Run connectors before web search, reroute known hosts and record connector gaps"
```

---

### Task 13: Show connector provenance and gaps in the dashboard and report

**Files:**
- Modify: `sci_search/frontend/static/data_research.js` (`renderDiscovered`, analysis source block)
- Modify: `sci_search/data_research/reporting.py` (`markdown_appendix`)
- Modify: `sci_search/frontend/templates/app.html` (bump the asset version query string for `data_research.js`, following commit `938a2ea`)
- Test: `tests/browser/test_autonomous_data.py`, `tests/test_connector_reporting.py`

**Interfaces:**
- Consumes: `result["connector_gaps"]`, `analysis["source"]["connector"]`, `assessment["recovery"]`.

- [ ] **Step 1: Write the failing tests**

Browser test (append to `tests/browser/test_autonomous_data.py`, same style as `test_unconfirmed_meaning_and_malformed_reviews_remain_visible`):

```python
def test_connector_gaps_and_recovery_are_visible(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    page.request.post(live_browser_url + "/auth/development")
    page.goto(live_browser_url + "/app")
    page.evaluate("""async () => {
      const {renderDataResearch} = await import('/static/data_research.js');
      const host = document.createElement('div'); host.id = 'gap-test'; document.body.append(host);
      renderDataResearch({kind:'discovered', analyses:[], limitations:[],
        connector_gaps:[{host:'waterinfo.rws.nl', measurement:'river discharge', evidence:'Loading only'}],
        assessments:[{title:'Life expectancy', url:'https://ec.europa.eu/x', decision:'blocked', reason:'No published series',
          connector:'eurostat', recovery:[{class:'selection', action:'repair', outcome:'Unobserved code for sex'}]}]}, host);
    }""")
    expect(page.locator("#gap-test").get_by_text("Needs an API connector for waterinfo.rws.nl (river discharge)", exact=True)).to_be_visible()
    expect(page.locator("#gap-test").get_by_text("Automatic recovery: selection → repair · Unobserved code for sex", exact=True)).to_be_attached()
    page.close()
```

Report test:

```python
# tests/test_connector_reporting.py
from sci_search.data_research.reporting import markdown_appendix


def test_appendix_lists_connector_gaps():
    text = markdown_appendix({"kind": "discovered", "analyses": [], "assessments": [], "limitations": [],
                              "strategy": {"measurements": ["river discharge"]},
                              "connector_gaps": [{"host": "waterinfo.rws.nl", "measurement": "river discharge", "evidence": "Loading only"}]})
    assert "Needs an API connector for waterinfo.rws.nl (river discharge)" in "\n".join(text) if isinstance(text, list) else text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connector_reporting.py tests/browser/test_autonomous_data.py -k "gap" -q`
Expected: FAIL (text not found)

- [ ] **Step 3: Implement**

In `renderDiscovered` (`data_research.js`, after the `literature_fallback` line):

```javascript
  for (const gap of data.connector_gaps || []) parent.append(element('p', 'Needs an API connector for ' + gap.host + ' (' + gap.measurement + ')'));
```

In the source-decision loop (after the `article.append(safeLink(...))` line):

```javascript
    for (const step of item.recovery || []) article.append(element('p', 'Automatic recovery: ' + step.class + ' → ' + step.action + ' · ' + step.outcome));
```

In the analysis block (where `analysis.source.license_note` is shown):

```javascript
    if (analysis.source.connector) parent.append(element('p', 'Queried the ' + analysis.source.publisher + ' API: dataset ' + analysis.source.connector.dataset), safeLink('Exact request', analysis.source.connector.request.url));
```

In `reporting.markdown_appendix`, after the existing source lines, add one line per gap: `f"- Needs an API connector for {cell(gap['host'])} ({cell(gap['measurement'])})"` under a `### Connector gaps` heading when `result.get("connector_gaps")` is non-empty. Read the function first and follow how it returns (list of lines joined at the end).

Bump the `data_research.js` version query string in `app.html`.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_connector_reporting.py tests/browser/test_autonomous_data.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sci_search/frontend sci_search/data_research/reporting.py tests/test_connector_reporting.py tests/browser/test_autonomous_data.py
git commit -m "Show connector provenance, recovery steps and connector gaps"
```

---

### Task 14: Live acceptance test, docs and full verification

**Files:**
- Create: `tests/live/__init__.py`, `tests/live/test_data_connectors_live.py`
- Modify: `tests/conftest.py` (option and marker skip), `pyproject.toml` (register marker `live_data`)
- Create: `docs/operations/data-connectors-acceptance.md` (written by the test run)
- Modify: `README.md`, `.env.example`, `docs/data-research.md`

**Interfaces:**
- Consumes: `workflow.execute` with real network and the configured analyzer.

- [ ] **Step 1: Register the option and marker**

In `pyproject.toml` `markers`, add: `"live_data: queries real statistical APIs and a configured model; enable with --run-live-data",`.

In `tests/conftest.py`, follow the existing `--run-retained-corpus` pattern (grep for it) to add `--run-live-data`, skipping `live_data` tests unless given.

- [ ] **Step 2: Write the acceptance test**

```python
# tests/live/test_data_connectors_live.py
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sci_search.data_research.strategy import validate_strategy
from sci_search.data_research.workflow import execute

pytestmark = pytest.mark.live_data

QUESTIONS = [
    ("Life expectancy for men and women by European country", dict(measurements=["life expectancy at birth"], geography="Netherlands, Germany, Greece", countries=["NLD", "DEU", "GRC"], start_year=2000, end_year=2024), True),
    ("Renewable electricity share in NL, DE and DK", dict(measurements=["renewable electricity share"], geography="Netherlands, Germany, Denmark", countries=["NLD", "DEU", "DNK"], start_year=2005, end_year=2024), True),
    ("Burned area in Spain, Portugal and Greece", dict(measurements=["burned area"], geography="Spain, Portugal, Greece", countries=["ESP", "PRT", "GRC"], start_year=2001, end_year=2024), True),
    ("Annual mean CO2 at Mauna Loa", dict(measurements=["annual mean atmospheric CO2 concentration"], geography="Mauna Loa", countries=[], start_year=2001, end_year=2024), True),
    ("Electricity storage in the Netherlands", dict(measurements=["battery electricity storage capacity"], geography="Netherlands", countries=["NLD"], start_year=None, end_year=None), True),
    ("Rhine discharge at Lobith", dict(measurements=["annual river discharge"], geography="Rhine at Lobith", countries=[], start_year=1980, end_year=2024), False),
    ("Coral cover on the Great Barrier Reef", dict(measurements=["total coral cover"], geography="Great Barrier Reef", countries=[], start_year=2000, end_year=2025), False),
]
OUTCOMES = []
# Answered by sources without a connector (EFFIS workbook, NOAA), so they need web search.
WEB_ONLY = {"Burned area in Spain, Portugal and Greece", "Annual mean CO2 at Mauna Loa"}


@pytest.mark.parametrize("question,values,should_succeed", QUESTIONS, ids=[q[0] for q in QUESTIONS])
def test_live_question(tmp_path, question, values, should_succeed):
    strategy = validate_strategy({"route": "data", "rationale": "Acceptance run", **values})
    result = execute(question, strategy, tmp_path)
    succeeded = bool(result["analyses"])
    sources = sorted({a["source"].get("connector", {}).get("name") or a["source"]["publisher"] for a in result["analyses"]})
    OUTCOMES.append((question, succeeded, sources, [g["host"] for g in result.get("connector_gaps", [])]))
    import os

    connector_only = os.environ.get("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral") == "mistral"
    if should_succeed and not (connector_only and question in WEB_ONLY):
        assert succeeded, json.dumps(result["assessments"], default=str)[:3000]
    else:
        assert result.get("connector_gaps"), "expected a named connector gap"


def teardown_module(module):
    if not OUTCOMES:
        return
    lines = [
        "# Data connectors acceptance run",
        "",
        f"Run: {datetime.now(UTC).isoformat(timespec='minutes')}. Provider: see SCI_SEARCH_ANALYSIS_PROVIDER.",
        "",
        "| Question | Succeeded | Sources | Connector gaps |",
        "|---|---|---|---|",
    ]
    lines += [f"| {q} | {'yes' if ok else 'no'} | {', '.join(s) or '-'} | {', '.join(g) or '-'} |" for q, ok, s, g in OUTCOMES]
    Path("docs/operations/data-connectors-acceptance.md").write_text("\n".join(lines) + "\n")
```

- [ ] **Step 3: Document the feature**

- `.env.example`: add under the analysis settings:
  ```
  # Query Eurostat, CBS, PxWeb and Our World in Data APIs before web search (1/0).
  SCI_SEARCH_DATA_CONNECTORS=1
  ```
- `docs/data-research.md`: add a section "## Statistical API connectors" describing the four connectors, the recovery table (copy it from the spec), connector gaps, and the `--run-live-data` acceptance run.
- `README.md`: one paragraph in the data-research section pointing to `docs/data-research.md` and the setting.

- [ ] **Step 4: Run the full offline verification**

Run:
```bash
uv run ruff format .
uv run ruff check .
uv run pyright
podman compose -f compose.integration.yml -p sci-search-it up -d --wait
uv run python -m pytest -q
podman compose -f compose.integration.yml -p sci-search-it down
```
Expected: format and lint clean, pyright 0 errors, all tests pass (live tests skipped).

- [ ] **Step 5: Run the live acceptance twice**

Run with the OpenAI provider, then with Mistral (no web search):
```bash
SCI_SEARCH_ANALYSIS_PROVIDER=openai uv run python -m pytest tests/live -q --run-live-data
cp docs/operations/data-connectors-acceptance.md docs/operations/data-connectors-acceptance-openai.md
SCI_SEARCH_ANALYSIS_PROVIDER=mistral uv run python -m pytest tests/live -q --run-live-data
cp docs/operations/data-connectors-acceptance.md docs/operations/data-connectors-acceptance-mistral.md
```
Expected with OpenAI: the first five questions succeed; Rhine and coral list a connector gap. Expected with Mistral (no web search): the three connector-covered questions (life expectancy, renewable share, electricity storage) succeed; burned area (EFFIS) and CO₂ (NOAA) come from non-connector sources and are expected to fail without web search. Report both tables to your human partner as they are; do not change thresholds or expectations to make them pass.

- [ ] **Step 6: Commit**

```bash
git add tests/live tests/conftest.py pyproject.toml .env.example README.md docs/data-research.md docs/operations/data-connectors-acceptance-*.md
git commit -m "Add the live connector acceptance run and document statistical connectors"
```
