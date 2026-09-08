# Program 7 verification record

Verified on 2026-08-27 in the isolated `feature/production-platform` worktree.

## Production composition and recovery

- The production-like Compose stack ran the production FastAPI, PostgreSQL, authenticated Redis,
  MinIO, Dramatiq worker, and Caddy compositions. A regression test prevents the disposable-volume
  override from downgrading web or worker to test services.
- Caddy was the only service with published ports. Plain HTTP returned a permanent HTTPS redirect;
  PostgreSQL, Redis, MinIO, web, and worker had no published host port.
- HTTPS readiness reported PostgreSQL, Redis, and object storage healthy. The response included
  HSTS, CSP, frame denial, no-sniff, referrer, and permissions headers.
- The load smoke provisioned two stable `(issuer, subject)` users with dummy `@mit.example`
  profile addresses, authenticated ten simultaneous durable sessions, queued ten PostgreSQL jobs,
  rejected an eleventh job at the configured quota, and revoked all smoke sessions.
- Unexpected termination of the web and worker application processes caused both containers to
  restart (`restart_count=1`). HTTPS readiness recovered and the Dramatiq worker returned to
  `ready for action` without Redis authentication errors.

## Security, backup, and release gates

- The immutable image ran as UID/GID `10001:10001`, with a read-only root filesystem and an explicit
  bounded temporary filesystem. No repository environment file or corpus data was present.
- Trivy found **0 fixed high/critical Debian vulnerabilities and 0 fixed high/critical Python
  vulnerabilities** in the deployable image. The build applies current Debian security upgrades,
  installs the runtime from builder-produced wheels without network access, and removes unused
  packaging tools from both runtime interpreters.
- The locked Python dependency audit reported **no known vulnerabilities**.
- The encrypted PostgreSQL/MinIO backup and isolated real restore drill passed, including row,
  authorization-grant, object-hash, audit-chain, and representative-artifact checks.
- The Compose deployment and rollback rehearsal passed with backup, drain, migration, readiness,
  worker release, and rollback eligibility in the required order.

## Engineering and scientific gates

- Full deterministic, integration, migration, API security, browser, worker recovery, and
  scientific suite: **393 passed, 3 intentionally gated system tests skipped, and 2 subtests
  passed**.
- Branch coverage: **82.59%**, above the 80% release gate.
- Ruff formatting and lint passed.
- Pyright completed with **0 errors and 139 non-blocking legacy warnings**.
- Secret scan passed.
- Source distribution and wheel built successfully; the wheel installed into a fresh Python 3.11
  environment and the `sci-search` CLI started.

The final SURFconext test-tenant login and production data cutover remain Program 8 acceptance
items because they require the institution-provided client registration and retained-data decision.
