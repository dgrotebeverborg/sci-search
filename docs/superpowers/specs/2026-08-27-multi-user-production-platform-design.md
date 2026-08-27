# Sci-Search Multi-User Production Platform Design

**Date:** 2026-08-27
**Status:** Approved in conversation; pending repository-root placement and commit
**Audience:** Sci-Search maintainers, operators, security reviewers, and scientific reviewers

## Objective

Turn Sci-Search from a trusted local research prototype into a deployable multi-user service for approximately ten simultaneous users. The production service authenticates through SURFconext, supports private projects and shared institutional workspaces, executes research jobs durably, preserves the existing provenance and fail-closed evidence contracts, and runs on one Docker host without preventing later horizontal scaling.

Version 1 requires authentication for all research content. It does not provide anonymous access or public sharing links.

## Guiding principles

1. Preserve scientific integrity before expanding convenience or recall.
2. Treat metadata, acquired documents, extracted evidence, researcher decisions, and generated conclusions as different lifecycle states.
3. Deny access unless a project-scoped authorization decision explicitly permits it.
4. Keep the scientific domain core independent of HTTP, databases, queues, identity providers, and object stores.
5. Make background work durable, idempotent, resumable, bounded, and auditable.
6. Prefer a modular monolith over microservices at the expected scale.
7. Introduce changes incrementally behind compatibility adapters; do not replace validated behavior in one rewrite.
8. Do not describe generated output as a systematic review until the formal methodological requirements are satisfied.

## Chosen architecture

The production system is a modular Python application deployed through Docker Compose as six cooperating containers:

- `proxy`: HTTPS termination, request-size limits, and security headers.
- `web`: FastAPI UI and REST API; it does not execute long research pipelines.
- `worker`: durable background research and artifact-generation jobs.
- `postgres`: authoritative application metadata, authorization, job state, evidence lifecycle, and audit events.
- `redis`: job broker, leases, rate limits, and short-lived session/cache data.
- `minio`: S3-compatible storage for acquired documents and generated artifacts.

The web and worker containers use the same versioned application image. They import the same domain and application modules but expose different process entry points. This keeps deployment simple while ensuring HTTP requests and long-running research work have independent lifecycles.

## Code boundaries

The target package structure is:

```text
sci_search/
  domain/             # evidence types, provenance, comparison, validation
  research/           # pure or injected pipeline stages
  application/        # project-scoped use cases and transaction boundaries
  infrastructure/     # PostgreSQL, Redis, S3, OIDC, provider adapters
  api/                # FastAPI routes, schemas, auth dependencies, errors
  frontend/           # HTML templates and separate CSS/JavaScript assets
  compatibility/      # temporary adapters for the current CLI and artifacts
```

Existing modules move incrementally. The first refactors create interfaces and characterization tests without changing externally visible scientific results. Compatibility adapters keep current CLI commands, serialized research artifacts, and regression fixtures working throughout migration.

## Identity and sessions

Production authentication uses SURFconext OpenID Connect Authorization Code flow through Authlib. The implementation must use discovery metadata and an established OIDC library; it must not implement protocol validation manually.

The durable identity key is `(issuer, subject)`. Email address, display name, affiliation, and institution claims are profile data and cannot be used as authentication or authorization identifiers. A successful first login creates a user and a private personal workspace automatically.

The login flow validates:

- exact registered redirect URI;
- authorization state and nonce;
- PKCE verifier and challenge;
- issuer and audience;
- token signature and supported algorithm;
- issued-at and expiry times.

After callback, the application creates an opaque, revocable server-side session. The browser receives only a random session identifier in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie. Production does not expose passwords or a local-login fallback. Development uses a local OIDC provider such as Keycloak through the same adapter contract.

## Tenancy and authorization

Every research resource belongs to exactly one project. A project is either private or attached to a shared workspace. A private project initially grants access only to its owner. A workspace project derives access from workspace membership plus optional project-specific membership.

Roles are:

| Role | Permissions |
| --- | --- |
| Owner | All project operations, membership, settings, transfer, and deletion |
| Editor | Create, retry, cancel, and manage runs, corpora, uploads, and exports |
| Reviewer | Read research content and create evidence or screening reviews |
| Viewer | Read and download content authorized for the project |

One centralized project-policy service makes authorization decisions for API routes, application use cases, worker jobs, and exports. Repository methods require a project identifier and cannot offer an unscoped lookup for protected resources. Requests for unknown and unauthorized resources return the same not-found response.

All version-1 research content requires authentication. Public links and anonymous reports are outside scope.

## Core data model

PostgreSQL stores at least these entities:

- users and external identities;
- server-side sessions;
- workspaces and workspace memberships;
- projects and project memberships;
- research runs and immutable run configuration;
- jobs, leases, attempts, stage checkpoints, cancellation requests, and errors;
- publication identities and content-addressed document references;
- project-document grants and run-document relations;
- evidence records, validation checks, review revisions, and study decisions;
- artifact metadata and storage references;
- append-only audit events.

All mutable tables carry created/updated timestamps and an optimistic version where concurrent edits matter. Database changes use Alembic migrations. Migrations are explicit deployment operations, not implicit web-process startup behavior.

SQLite remains readable only through migration/import tooling for existing scientific-memory data. New production state is never split between SQLite and PostgreSQL.

## Object storage

A `BlobStore` interface supports a filesystem implementation for development and an S3-compatible implementation for production. It exposes bounded streaming put/get operations, metadata lookup, and deletion by opaque object key.

Document bytes are addressed by SHA-256 digest and stored once. Database rows grant projects access to content; object keys are not authorization tokens. Generated reports and packages record their input fingerprint and generator version so they can be regenerated safely.

Retention rules are:

- source documents remain while referenced by an authorized project or retained audit requirement;
- transient upload and pipeline files expire automatically;
- generated exports have a configurable lifetime and can be regenerated;
- project deletion immediately revokes access and queues reference-counted garbage collection;
- audit events retain identifiers and actions but not deleted document content;
- operators can inspect usage, identify unreferenced objects, run dry-run cleanup, and then perform bounded garbage collection.

## Durable job execution

HTTP requests create jobs transactionally and return a stable job/run identifier. Redis carries delivery and lease coordination; PostgreSQL remains the source of truth for job state.

Job requirements are:

- an idempotency key prevents duplicate start requests;
- only one active lease may execute a job;
- leases expire and can be reclaimed after worker failure;
- each pipeline stage records its inputs, version, start, checkpoint, outcome, and error;
- completed stages are not repeated unless their input fingerprint or implementation version changes;
- retry policies distinguish transient external failures from invalid inputs and deterministic rejection;
- retries and provider calls remain bounded;
- cancellation is checked between stages and within bounded acquisition loops;
- global, workspace, and per-user queue/concurrency limits protect capacity;
- restart recovery derives state from PostgreSQL rather than process memory;
- operators can retry a failed stage or whole run without editing stored JSON by hand.

The initial worker implementation uses one queue and explicit stage names. Separate service deployment or queues are introduced only if measured load requires them.

## Research pipeline decomposition

The current orchestration is decomposed into injected stage objects with serializable inputs and outputs:

1. question interpretation and planning;
2. memory lookup and discovery;
3. metadata merge, deduplication, and screening;
4. bounded citation expansion;
5. full-text acquisition and parsing;
6. question-specific full-text screening;
7. study-matrix construction and optional adjudication;
8. evidence extraction and deterministic validation;
9. coverage assessment and bounded gap search;
10. deterministic and optional model-assisted synthesis;
11. research landscape and literature review generation;
12. scientific-memory ingestion and artifact publication.

Stages communicate through versioned contracts and depend on repository, provider, clock, and blob-store interfaces. They do not import FastAPI, global service instances, or process-local session dictionaries.

## API and user interface

FastAPI routers are divided by responsibility: authentication, workspaces, projects, runs, documents, evidence reviews, validation, exports, audit, and operational health. Pydantic request and response schemas reject unknown or malformed state-changing inputs. Error mapping is uniform and does not return stack traces or secrets.

The UI is project-first:

1. authenticate through SURFconext;
2. choose a personal or shared workspace and project;
3. start or inspect research runs;
4. follow durable stage progress and request retry or cancellation;
5. inspect search, screening, study, evidence, provenance, and limitation records;
6. review evidence according to role;
7. manage project membership as an owner;
8. export permitted research documents and reports;
9. inspect relevant audit activity.

Version 1 keeps framework-free browser code but separates templates, CSS, and JavaScript modules. The frontend never treats hidden controls as authorization. All operations are authorized by the API.

Progress uses bounded HTTP polling. WebSockets or server-sent events are deferred because approximately ten simultaneous users do not justify the additional operational surface.

## Security controls

The production configuration enforces:

- HTTPS and trusted proxy configuration;
- restrictive same-origin CORS;
- CSRF tokens on state-changing cookie-authenticated requests;
- secure session rotation and revocation;
- per-user and per-workspace rate limits;
- request, upload, download, archive, provider-call, and job bounds;
- current path traversal, document signature, parseability, and content-size checks;
- outbound URL policy restricting automatic full-text acquisition to HTTPS and explicitly permitted scholarly hosts or provider adapters;
- no secrets, tokens, raw document contents, or model prompts in normal logs;
- Docker secrets or environment injection for credentials;
- least-privilege database and object-storage credentials;
- security headers including CSP, frame restrictions, no-sniff, and referrer policy;
- append-only audit events for authentication, membership, research, upload, review, export, administrative action, and deletion.

The default production deployment fails startup if insecure development authentication, wildcard origins, non-HTTPS callback URLs, or default credentials are enabled.

## Scientific integrity and model behavior

The existing fail-closed scientific rules remain release requirements:

- discovery metadata is not scientific evidence;
- evidence must link to acquired, parsed full text and exact provenance;
- source-grounding status does not imply scientific truth;
- missing question dimensions cause qualification or answer withholding;
- evidence nature and comparison context remain explicit;
- generative output cannot enter answers or memory unless deterministic validation succeeds;
- deterministic extraction remains visible when model analysis is unavailable or invalid.

Model input selection replaces the fixed leading-record slice with a versioned diversity-aware policy. The policy selects within a configured token/evidence budget across publications, evidence types, positive and negative directions, methods, limitations, and counterevidence. It records included and excluded evidence IDs plus selection reasons.

A provider-neutral `AnalysisProvider` interface supports Mistral initially and allows later adapters. Run provenance records provider, exact model identifier, policy version, prompt contract, schema version, validator version, usage, rejected records, and fallback reason.

Risk-of-bias support stores explicit reviewer judgments, tool/version, domain, rationale, and source references. The system does not infer a favorable risk assessment from missing data.

## Validation strategy

The current deterministic regression suite remains mandatory. New testing layers are:

- unit tests for policies, stages, repositories, and input validation;
- PostgreSQL integration tests for tenancy, transactions, migrations, leases, and concurrent review updates;
- MinIO-compatible integration tests for content deduplication and authorization-independent object keys;
- Redis/worker integration tests for retry, cancellation, duplicate delivery, lease expiry, and restart recovery;
- OIDC tests against a local provider for callback validation, session rotation, logout, and claim handling;
- API tests proving cross-project access is denied for every protected resource type;
- browser tests for login, project navigation, role behavior, research progress, reviews, uploads, and exports;
- migration tests using copies of existing SQLite/run artifacts;
- scheduled provider-contract tests with controlled credentials and cost limits;
- restore drills for PostgreSQL and object storage.

Scientific validation expands locked benchmarks with independent researcher labels. Metrics remain separate: discovery recall, screening precision, full-text availability, evidence grounding, unsupported-assertion rate, conclusion coverage, context preservation, and reviewer disagreement. A combined score cannot hide a failure of the zero-unsupported-assertion gate.

## Engineering quality gates

The project defines locked production and development dependencies and CI for supported Python versions. Required checks are:

- Ruff formatting and linting;
- Pyright type checking at a documented strictness baseline that can only increase;
- pytest with branch coverage and an enforced threshold;
- package build and clean-environment install smoke test;
- database migration upgrade test;
- dependency and static security scans;
- deterministic unit and integration tests without live paid/provider calls;
- container image build and vulnerability scan.

The repository adds license metadata, a license file, contributor guidance, security reporting instructions, architecture documentation, operational runbooks, and an explicit dependency-update policy.

## Observability and operations

Web and worker processes emit structured logs with request, user, workspace, project, run, and job correlation identifiers. Identifiers are included only where the operator is authorized to access the corresponding records. Sensitive payloads are excluded.

Health endpoints distinguish liveness from readiness. Readiness verifies required database, queue, and object-store connections. Worker heartbeat and queue-age metrics identify stalled execution.

Prometheus-compatible metrics cover request latency, authorization denials, queue depth and age, active leases, stage durations, provider failures, acquisition results, storage use, evidence counts, answer withholding, and model-validation rejection. Metrics do not contain document text or unbounded user-supplied labels.

Backups include PostgreSQL and object-store metadata/content. The runbook defines automated backup frequency, encryption, retention, restoration into an isolated environment, and periodic restore verification. Deployment drains workers, runs explicit migrations, starts new processes, checks readiness, and preserves a rollback path compatible with the last database migration.

## Delivery programs

The work is divided into eight independently testable programs:

1. **Engineering baseline:** dependency management, CI, quality tools, characterization tests, licensing, and documentation skeleton.
2. **Identity and projects:** OIDC adapter, sessions, users, workspaces, projects, roles, centralized authorization, and isolation tests.
3. **Persistence and blobs:** PostgreSQL repositories, Alembic, content-addressed object storage, and legacy import tooling.
4. **Durable jobs and pipeline stages:** Redis queue, leases, retry/cancel/recovery, and decomposition of the run orchestrator.
5. **API and frontend:** FastAPI routers, schemas, secure browser flow, modular assets, and browser tests.
6. **Scientific quality:** diversity-aware model evidence selection, provider-neutral analysis, risk-of-bias records, and gold-label workflow extensions.
7. **Production operations:** Compose deployment, proxy, secrets, metrics, health, backups, restore test, and runbooks.
8. **Legacy retirement and storage lifecycle:** migrate retained data, verify parity, enable garbage collection, and remove obsolete server/thread/SQLite/UI paths only after rollback windows expire.

Each program keeps the existing scientific regression suite green and supplies a forward migration and rollback procedure. Programs execute in order except that scientific benchmark labeling can proceed in parallel with infrastructure work outside the code migration.

## Acceptance criteria

The platform is ready for version-1 production when:

1. A SURFconext test-environment user can authenticate and receive a private workspace.
2. Owners can create shared projects and assign all four roles.
3. Automated tests prove no role can access or mutate another unauthorized project by guessing identifiers.
4. A research job survives worker termination and resumes without duplicate published evidence or artifacts.
5. Two simultaneous users can run and review different projects without state leakage.
6. Existing deterministic scientific tests and serialized-artifact compatibility tests pass.
7. Model analysis either passes all grounding gates or visibly falls back to deterministic extraction.
8. Documents are deduplicated by content while authorization remains project-scoped.
9. Database and object-storage backups restore successfully in an isolated drill.
10. CI passes formatting, linting, typing, coverage, packaging, migrations, security, and container checks.
11. Production startup rejects insecure authentication, origin, callback, and secret settings.
12. Operations documentation covers deployment, migration, rollback, backup, restore, incident response, user removal, and storage cleanup.

## Out of scope for version 1

- anonymous access or public sharing links;
- Kubernetes manifests or independent microservice deployment;
- mobile applications;
- billing or quota purchases;
- real-time collaborative editing;
- a claim of systematic-review completeness;
- automatic favorable risk-of-bias conclusions;
- replacing researcher validation with model evaluation;
- WebSockets solely for progress updates.

## Migration and rollback

Migration begins by adding new persistence and application boundaries while the existing CLI and artifacts remain operational. Import tools copy, validate, and fingerprint legacy scientific-memory and research-run data; they never mutate the source during dry runs. Repeated imports are idempotent.

For each program, deployment supports the last compatible schema and application image. Destructive schema cleanup is deferred until data parity, backup restoration, and a documented rollback window have passed. Legacy files are retained read-only until operators explicitly approve garbage collection.

## Workspace constraint

This specification is temporarily stored under `sci_search/docs/` because the active workspace permits writes only inside the package directory. Before normal repository integration, move it to `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`, review the resulting path references, and commit it from a checkout with functional Git metadata.
