# Contributing to Sci-Search

Sci-Search treats scientific provenance and correctness as release-critical behavior. Changes
must preserve exact source passages, deterministic validation, and explicit answer withholding.

## Development setup

Install Python 3.11 and `uv`, then create the locked development environment:

```bash
uv sync --frozen --extra dev --python 3.11
```

Run the local quality gates:

```bash
uv run python scripts/check_no_secrets.py
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run python -m pytest --cov=sci_search --cov-report=term-missing -q
uv run python -m build
uv export --frozen --all-extras --no-emit-project --quiet --output-file /tmp/sci-search-audit.txt
uv run pip-audit --strict --requirement /tmp/sci-search-audit.txt
```

## Change discipline

- Use test-driven development for behavior changes: add a failing behavioral test, implement the
  smallest change that makes it pass, then refactor with the suite green.
- Keep the current CLI commands and `scientific_evidence_v1` and
  `scientific_evidence_graph_v1` artifacts compatible until a documented migration retires them.
- Add explicit forward and rollback steps for schema, storage, or serialized-contract changes.
- Keep domain and research code independent of HTTP, database, queue, identity-provider, and
  object-store implementations.
- Do not weaken source-grounding, validation, or answer-withholding rules to make a test pass.
- Do not use live paid models or scholarly providers in deterministic pull-request tests.

## Data and credentials

Never commit API keys, tokens, `.env.local`, acquired publication files, generated research runs,
scientific-memory stores, validation replays, or benchmark-run output. Small synthetic fixtures,
manifests, manually curated benchmark definitions, and approved anonymized validation labels may
be committed when their provenance and redistribution status are documented.

## Pull requests

Explain the scientific or operational contract affected, list the tests run, identify migrations
and rollback steps, and call out any change to provenance, evidence selection, model behavior, or
researcher-visible conclusions.
