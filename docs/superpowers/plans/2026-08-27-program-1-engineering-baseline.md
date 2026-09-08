# Program 1: Engineering Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sci-Search reproducibly installable and enforce compatibility, testing, typing, linting, packaging, and security gates before architectural migration.

**Architecture:** Keep runtime behavior unchanged. Add executable characterization tests around public CLI/artifact contracts, centralize tool configuration in `pyproject.toml`, and run deterministic checks in CI without credentials or live provider calls.

**Tech Stack:** Python 3.11–3.14, setuptools, uv, pytest, pytest-cov, Ruff, Pyright, build, pip-audit, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Existing CLI commands and serialized artifacts must remain compatible.
- CI must not access paid models or live scholarly providers.
- Runtime dependency bounds remain explicit; the lock mechanism must resolve Python 3.11.
- Generated research data and secrets remain excluded from version control.

---

### Task 1: Characterize public contracts

**Files:**
- Create: `tests/contracts/test_cli_contract.py`
- Create: `tests/contracts/test_artifact_contract.py`
- Modify: `tests/__init__.py`

**Interfaces:**
- Consumes: `sci_search.cli.main`, `EvidenceStore.to_evidence_artifact()`, and `EvidenceStore.to_graph_artifact()`.
- Produces: regression gates that allow later internal module movement without changing public behavior.

- [x] **Step 1: Write the CLI characterization test**

```python
from sci_search.cli import main


def test_cli_requires_corpus_and_exposes_supported_commands(capsys):
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    output = capsys.readouterr().out
    assert "--corpus" in output
    for command in ("investigate", "research-online", "serve", "evaluate-discovery"):
        assert command in output
```

- [x] **Step 2: Run the test and verify the initial expected failure**

Run: `python -m pytest tests/contracts/test_cli_contract.py -q`

Expected: FAIL because `tests/contracts/` does not yet exist or because an independently discovered contract mismatch must be resolved before freezing it.

Execution note (2026-08-27): the existing CLI already satisfied this characterization, so the
test passed on its first run and now freezes that behavior.

- [x] **Step 3: Add artifact assertions with hand-written required keys**

```python
def test_evidence_artifact_keeps_versioned_top_level_contract(evidence_store):
    artifact = evidence_store.to_evidence_artifact()
    assert artifact["artifact_type"] == "scientific_evidence"
    assert artifact["artifact_contract_version"] == "scientific_evidence_v1"
    assert set(artifact) == {
        "artifact_type", "artifact_contract_version", "publications",
        "entities", "results", "statements", "evidence",
    }
```

- [x] **Step 4: Run both contract tests and make only fixture/setup corrections required for green**

Run: `python -m pytest tests/contracts -q`

Expected: PASS.

- [x] **Step 5: Run the existing suite**

Run: `python -m pytest -q`

Expected: all existing tests and new contract tests pass.

- [x] **Step 6: Commit**

```bash
git add tests/contracts tests/__init__.py
git commit -m "test: freeze public CLI and artifact contracts"
```

### Task 2: Define reproducible dependency and tool configuration

**Files:**
- Modify: `pyproject.toml`
- Create: `uv.lock`

**Interfaces:**
- Produces: `pip install -e '.[dev]'`, `python -m build`, `ruff check`, `pyright`, and coverage configuration.

- [x] **Step 1: Add a packaging smoke test that installs the built wheel in a clean virtual environment**

Create `tests/contracts/test_package_metadata.py`:

```python
from importlib.metadata import entry_points, version


def test_installed_distribution_exposes_cli():
    assert version("sci-search")
    scripts = {item.name: item.value for item in entry_points(group="console_scripts")}
    assert scripts["sci-search"] == "sci_search.cli:main"
```

- [x] **Step 2: Run the test before editable installation and confirm it fails when distribution metadata is absent**

Run: `python -m pytest tests/contracts/test_package_metadata.py -q`

Expected: FAIL with `PackageNotFoundError` in a clean test environment.

- [x] **Step 3: Expand `pyproject.toml`**

Add project readme, license metadata, authors, classifiers, URLs, dependency groups, and tool sections. Runtime groups must include FastAPI-era dependencies only in the program that first uses them; Program 1 adds test/build/lint/type/security tools without prematurely changing runtime behavior.

Execution note (2026-08-27): readme, classifiers, reproducible dependency groups, and tool
configuration are present. License, owner/author metadata, and project URLs remain intentionally
unset pending the repository owner's explicit choices.

```toml
[project.optional-dependencies]
dev = [
  "build>=1.2,<2",
  "pip-audit>=2.7,<3",
  "pytest>=8.3,<9",
  "pytest-cov>=6,<7",
  "pyright>=1.1.400,<2",
  "ruff>=0.12,<1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-config --strict-markers"

[tool.coverage.run]
branch = true
source = ["sci_search"]

[tool.coverage.report]
fail_under = 80
show_missing = true

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "standard"
include = ["sci_search"]
```

- [x] **Step 4: Generate and verify the deterministic uv lock file**

Run:

```bash
uv lock --python 3.11
uv lock --check
```

Commit `uv.lock` and verify it contains no environment-specific paths or credentials.

- [x] **Step 5: Build and install the wheel in a temporary virtual environment**

Run:

```bash
python -m build
python -m venv /tmp/sci-search-wheel-test
/tmp/sci-search-wheel-test/bin/pip install dist/sci_search-*.whl
/tmp/sci-search-wheel-test/bin/sci-search --help
```

Expected: all commands exit 0 and the help output lists supported commands.

- [x] **Step 6: Run package metadata, lint, type, and test checks**

```bash
python -m pytest tests/contracts/test_package_metadata.py -q
ruff format --check .
ruff check .
pyright
python -m pytest --cov=sci_search --cov-report=term-missing -q
```

- [x] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock tests/contracts/test_package_metadata.py
git commit -m "build: establish reproducible quality toolchain"
```

### Task 3: Add deterministic CI and scheduled contract workflows

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/provider-contracts.yml`
- Create: `scripts/check_no_secrets.py`
- Test: `tests/contracts/test_no_secrets.py`

**Interfaces:**
- Produces: pull-request gates and a separately authorized scheduled provider check.

- [x] **Step 1: Write a failing secret-scanner behavior test**

```python
from scripts.check_no_secrets import scan_text


def test_secret_scan_rejects_assignments_but_allows_examples():
    assert scan_text("MISTRAL_API_KEY=actual-secret-value")
    assert scan_text("MISTRAL_API_KEY=") == []
```

- [x] **Step 2: Run it and verify import/function failure**

Run: `python -m pytest tests/contracts/test_no_secrets.py -q`

Expected: FAIL because `scan_text` does not exist.

- [x] **Step 3: Implement the scanner as a deterministic library plus CLI**

`scan_text(text: str) -> list[str]` returns labels for non-empty assignments to known secret variables and private-key headers. `main()` scans tracked text files, excludes lock hashes and fixtures explicitly, reports paths without printing values, and returns nonzero on findings.

- [x] **Step 4: Add CI jobs**

`ci.yml` must run, in order, secret scan, Ruff, Pyright, Python 3.11–3.14 pytest matrix, coverage on 3.11, package build/install, pip-audit, and artifact upload for test reports. Provider credentials are absent.

`provider-contracts.yml` must be manual and scheduled, use environment-scoped secrets, set strict per-run limits, and upload sanitized diagnostics. It must never run for untrusted pull requests.

- [x] **Step 5: Run the workflow-equivalent commands locally**

```bash
python scripts/check_no_secrets.py
ruff format --check .
ruff check .
pyright
python -m pytest --cov=sci_search --cov-report=term-missing -q
python -m build
pip-audit
```

- [x] **Step 6: Commit**

```bash
git add .github scripts/check_no_secrets.py tests/contracts/test_no_secrets.py
git commit -m "ci: enforce deterministic engineering gates"
```

### Task 4: Add project governance and architecture documentation

**Files:**
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `docs/ARCHITECTURE.md`
- Modify: `README.md`

**Interfaces:**
- Produces: clear licensing, contribution, vulnerability reporting, and architecture boundaries.

- [x] **Step 1: Obtain the repository owner's explicit license choice**

Licensing is a legal decision and cannot be inferred. Record the chosen SPDX identifier in `pyproject.toml` and add its unmodified canonical license text.

- [x] **Step 2: Document executable contributor commands**

`CONTRIBUTING.md` must list environment setup, full local CI commands, TDD expectations, artifact compatibility, migration rules, and the prohibition on committing research data or credentials.

- [x] **Step 3: Document private vulnerability reporting**

`SECURITY.md` must state supported versions, a non-public reporting channel chosen by the owner, expected acknowledgement, secret-handling rules, and that scientific-validity disagreements are handled separately from software vulnerabilities.

- [x] **Step 4: Document current and target module boundaries**

`docs/ARCHITECTURE.md` must link the approved design, explain the compatibility migration, list dependency directions, and state that domain code cannot import API or infrastructure modules.

- [x] **Step 5: Run documentation link and package metadata checks**

Run: `python -m build && python -m pytest tests/contracts -q`

Expected: PASS with the readme and license included in package metadata.

- [x] **Step 6: Commit**

```bash
git add LICENSE CONTRIBUTING.md SECURITY.md README.md docs/ARCHITECTURE.md pyproject.toml
git commit -m "docs: define project governance and architecture"
```

### Task 5: Program 1 verification

- [x] Run `ruff format --check .` and verify exit 0.
- [x] Run `ruff check .` and verify exit 0.
- [x] Run `pyright` and verify exit 0 at the documented baseline.
- [x] Run `python -m pytest --cov=sci_search --cov-report=term-missing -q` and verify the threshold.
- [x] Run `python -m build` and install the wheel in a clean temporary environment.
- [x] Run `pip-audit` and resolve or explicitly fail on known vulnerabilities.
- [x] Confirm scheduled workflows cannot expose secrets to untrusted pull requests.
- [x] Confirm existing CLI output and artifact contract tests pass unchanged.
