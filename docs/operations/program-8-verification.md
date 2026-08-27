# Program 8 verification and release checklist

Verified on 2026-08-27 in the isolated `feature/production-platform` worktree.

## Release decision

**Engineering verification: pass. Production identity acceptance: pending. Release: hold.**

The application, migration, isolation, recovery, scientific-integrity, and deployment gates below
pass. A release tag and deletion of retained legacy data remain prohibited until both external
gates are complete:

1. the Utrecht University identity administrator supplies a SURFconext test client and the callback
   is exercised with a real test-environment account; and
2. the seven-day rollback window has elapsed and the repository owner explicitly approves deletion
   after a fresh backup/restore verification.

## Migration and storage lifecycle

- A protected-copy import preserved **560/560 publications, 45/45 research runs, 594/594 evidence
  records, and 560/560 blob references**, producing 556 unique content-addressed objects with zero
  unexplained loss and no source mutation. The measured import and parity time was 7.38 seconds.
- Interrupted and incremental imports resume from ledger checkpoints without duplicate runs or
  evidence. Conflicting source metadata is retained as source variants.
- Garbage collection records an immutable dry-run plan, defaults to no deletion, requires the plan
  identifier as explicit confirmation, rejects stale plans, and rechecks references before every
  bounded deletion batch. Metadata removal commits before physical deletion; PostgreSQL advisory
  locks serialize each blob key with uploads, worker publication, imports, and cleanup. When an
  expired database record shares bytes with a live document or artifact, only the expired record is
  removed and the shared bytes are retained.
- The final container's `storage-gc` command connected to production-like PostgreSQL and MinIO in
  dry-run mode with a 30-day grace period. It recorded a valid plan containing zero eligible
  objects and deleted nothing. Local filesystem storage remains available only as an explicit
  migration/testing option.

Production dry run (never substitute `--apply-plan` without reviewing the recorded plan):

```bash
docker compose run --rm --no-deps web storage-gc --grace-days 30
```

Applying a reviewed plan requires both arguments; the service revalidates it before deletion:

```bash
docker compose run --rm --no-deps web storage-gc \
  --apply-plan PLAN_UUID --confirm PLAN_UUID
```

## Platform and security acceptance

- The production-like TLS stack ran Caddy, FastAPI, PostgreSQL, authenticated Redis, MinIO, and a
  Dramatiq worker. Only Caddy published host ports. Readiness reported all dependencies healthy and
  returned the required browser security headers.
- Two distinct test OIDC `(issuer, subject)` identities received stable, separate identities. Ten
  simultaneous authenticated sessions queued ten bounded jobs and the next job was rejected by
  quota. Test profile email addresses used the non-deliverable `@mit.example` domain; email is not
  an identity key.
- Owner, editor, reviewer, and viewer permissions were exercised on private and shared projects.
  Unrelated users received the same not-found response for reads, writes, job controls, uploads,
  reviews, downloads, exports, and audit resources.
- Forced web and worker process termination caused container restart and readiness recovery. Durable
  restart tests verified that claimed work resumes without duplicate evidence or artifacts.
- Invalid model evidence follows the deterministic extractive fallback and records its validation
  outcome; exact-passage provenance and answer-withholding tests pass.

## Recovery, deployment, and engineering evidence

- The encrypted PostgreSQL/MinIO backup restored into isolated targets and matched database rows,
  authorization grants, object hashes, audit chain, and representative report artifacts.
- The Compose deployment state-machine rehearsal used the final Program 8 container image with
  deterministic probe processes and passed backup-marker, drain, migration, readiness,
  worker-release, and rollback-order assertions in 23.84 seconds. Application recovery is covered
  separately by the production-like stack restart and isolated PostgreSQL/MinIO restore drills.
- Repository verification: **408 tests passed, 4 intentionally gated tests skipped, and 2 subtests
  passed**. The scientific validation subset contributed 31 passing tests.
- Reconstructed branch coverage was **84%**, above the 80% release gate. Ruff formatting/lint and
  the secret scan passed. Pyright reported 0 errors (136 pre-existing non-blocking warnings).
- The source distribution and wheel built successfully; the wheel installed in an isolated Python
  3.11 target and its CLI started. The locked dependency audit reported no known vulnerabilities.
- The final image ran as UID/GID `10001:10001` with a read-only root filesystem. It contained no
  source `.env.local`, corpus data, or retired local web runtime. Trivy reported zero high/critical
  Debian and Python vulnerabilities. Verified local image ID:
  `sha256:3851ac40c8be6dc3f20a7f209888bda6eed1f88f33d704d3812254b7b3da5aa9`.

## Evidence commands

```bash
.venv/bin/python -m pytest -q tests/api tests/application tests/contracts tests/deployment \
  tests/domain tests/infrastructure tests/research tests/security
.venv/bin/python -m pytest -q tests/integration tests/system
PLAYWRIGHT_BROWSERS_PATH=/tmp/sci-search-playwright \
  .venv/bin/python -m pytest -q tests/browser
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/python -m build --outdir /tmp/sci-search-program8-dist
.venv/bin/pip-audit -r requirements.lock
```

The retained source tree and prior image must remain read-only and recoverable until the external
release gates at the top of this checklist are signed off.
