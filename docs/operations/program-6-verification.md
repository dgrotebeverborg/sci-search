# Program 6 verification record

Verified on 2026-08-27 in the isolated `feature/production-platform` worktree.

## Scientific and engineering gates

- Full suite with PostgreSQL, Redis, MinIO and Chromium: **345 tests plus 2 subtests passed**.
- Branch coverage: **83.62%**, above the 80% release gate.
- Diversity-selection, provider-contract, risk-of-bias authorization/concurrency, independent
  gold-label, locked 43-question, reliability, source-grounding and validation tests passed.
- PostgreSQL migration chain upgraded, downgraded and upgraded through `0005_risk_of_bias`.
- Ruff formatting and lint passed.
- Pyright completed with **0 errors and 139 non-blocking legacy warnings**.
- Secret scan passed.
- Source distribution and wheel built successfully; the wheel contains the modular frontend
  templates, styles and JavaScript.
- Locked third-party dependency audit reported **no known vulnerabilities**.

## Deterministic compatibility and provenance

The existing representative iron-air comparison remains source-compatible: 12 evidence passages
from 7 publications, including the locked 82.9% at 550 °C and 0.2 C and 35% system-context values.
Every summary citation resolves to a returned evidence ID; every selected statement remains inside
its exact stored passage with valid offsets.

The generic goat-foraging corpus also retained exact passage provenance and known citation IDs. Its
current coverage gate withheld the overall answer rather than promoting topic matches to an
unsupported conclusion. The locked cross-domain benchmark remained green, so the Program 6 schema
migration did not change deterministic evidence or citation semantics.

Malformed model structures, unknown evidence IDs, non-source quotes, quotes outside the selected
statement and empty grounded answers all produce the deterministic fallback. These rejected outputs
are recorded in analysis diagnostics and cannot enter persisted evidence or generated reviews as
validated assertions.
