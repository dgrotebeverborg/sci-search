# Sci-Search architecture

Sci-Search is evolving incrementally from a local scientific-evidence prototype into a secure,
multi-user research platform. The approved target is documented in the
[production-platform design](superpowers/specs/2026-08-27-multi-user-production-platform-design.md),
and its gated delivery sequence is recorded in the
[implementation roadmap](superpowers/plans/2026-08-27-production-platform-roadmap.md).

## Scientific contracts that remain stable

- Every scientific assertion links to an acquired and parsed full text, exact passage, publication,
  section, page when available, and extraction method.
- Discovery metadata and abstracts are candidates, not scientific evidence.
- Numerical results retain technology, configuration, conditions, evidence nature, assumptions,
  uncertainty, and provenance needed for comparability decisions.
- Model output cannot enter an answer or scientific memory unless deterministic grounding checks
  pass; invalid output falls back visibly to deterministic extraction.
- Missing question dimensions cause qualification or answer withholding.
- Existing CLI commands and version-1 evidence and graph artifacts remain available through the
  compatibility layer until a verified migration explicitly retires them.

## Current structure

The current package is a modular local application. Scientific contracts live in `models.py`,
validated storage and graph projection in `store.py`, extraction and comparison in their named
modules, and the generic research pipeline across discovery, acquisition, screening, study-matrix,
evidence, synthesis, reporting, and scientific-memory modules. `cli.py` and `web.py` currently
provide the process boundaries.

These modules are protected by characterization and scientific-regression tests while they move
behind explicit interfaces. Migration is evolutionary: validated behavior is not replaced in one
rewrite.

## Target boundaries

```text
sci_search/
  domain/          scientific evidence, provenance, comparison, validation
  research/        injected, serializable research pipeline stages
  application/     project-scoped use cases and transaction boundaries
  infrastructure/  PostgreSQL, Redis, S3, OIDC, and provider adapters
  api/             FastAPI routes, schemas, authorization dependencies, errors
  frontend/        templates and separate CSS/JavaScript assets
  compatibility/   temporary CLI and artifact adapters
```

Dependencies point inward:

```text
api/frontend/infrastructure -> application -> research/domain
compatibility              -> application/research/domain
domain                     -> Python standard library only
```

Domain modules must not import FastAPI, SQLAlchemy, Redis/Dramatiq, Authlib, boto3, or concrete
provider clients. Research stages receive repositories, providers, clocks, and blob stores through
interfaces. API routes validate and authorize requests, then call application use cases; they do
not execute long research pipelines.

PostgreSQL is authoritative for application and job state. Redis provides delivery, leases, rate
limits, and short-lived coordination only. Document bytes are content-addressed behind a `BlobStore`
interface, while project-scoped database grants control access.

## Compatibility migration

Each delivery program must keep the complete existing suite green, add focused tests for its new
boundary, document forward and rollback procedures, and preserve existing serialized artifacts.
Legacy SQLite, process-local jobs, and the current web server remain readable through adapters until
the final migration program verifies imported counts, hashes, provenance, authorization, reports,
and rollback rehearsal.

## Static-analysis baseline

Ruff formatting and selected correctness rules are enforced without exceptions in the checked
source tree. Pyright runs in standard mode. Categories containing pre-existing findings are
temporarily reported as warnings; they must be reduced over time and may not be globally disabled.
New modules should pass standard diagnostics without adding warnings.
