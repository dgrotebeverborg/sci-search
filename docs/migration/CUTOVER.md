# Production cutover and rollback

This runbook makes PostgreSQL and private object storage authoritative without deleting the
retained legacy tree. The release owner is accountable for the go/no-go decision; the database
operator owns backup/restore and parity; the application operator owns drain, deploy, readiness,
and rollback; the identity administrator owns the SURFconext client.

## Entry gates

1. Freeze the candidate image by digest and record the current image and Alembic revision.
2. Run the encrypted backup and isolated restore drill. `verify-restore` must report `ok: true`.
3. Inventory the protected legacy tree twice. Fingerprints must match and all errors must be
   classified.
4. Run the resumable import and parity command. Unexplained losses must equal zero.
5. Confirm two stable OIDC `(issuer, subject)` identities can access their private projects, and
   that the invited researcher has only the assigned role in the shared project.
6. Submit simultaneous research jobs and confirm both become durable PostgreSQL jobs.

Any failed gate is a no-go. Never repair parity by deleting source rows or changing the source
tree.

## Cutover

1. Announce the write freeze and disable legacy submissions. Existing read access may remain.
2. Wait up to 300 seconds for legacy work to drain; cancel or explicitly record anything that does
   not reach a terminal checkpoint.
3. Take the final encrypted backup, then rescan and run the incremental import in bounded batches.
4. Require exact parity again. The import ledger must be `completed` and contain per-record UUID
   mappings and blob hashes.
5. Run the production deployment state machine: backup, worker drain, migration, web replacement,
   readiness, then worker release.
6. Verify readiness dependencies, audit events, two identities, one private and one shared project,
   downloads, review creation, and a fresh research job.
7. Record the source fingerprint, image digest, schema revision, backup identifier, operator names,
   and timestamps. Do not record tokens or source text.

Measured rehearsal baselines on 2026-08-27:

- protected 560-publication import plus parity: 7.38 seconds;
- encrypted production-like backup/isolated restore: passed;
- Compose deploy/rollback rehearsal: 52.79 seconds;
- readiness target after web replacement: 60 seconds maximum;
- total worker-drain allowance: 300 seconds.

## Rollback window

Keep the prior image and retained legacy tree read-only for at least seven days. If application
acceptance fails, stop workers, restore the previous application image, and leave PostgreSQL and
object storage untouched when the schema is backward-compatible. If the schema is not compatible,
restore the pre-cutover encrypted backup into new targets and verify it before switching traffic.

After rollback, compare run, evidence, job, grant, artifact, and audit counts captured immediately
before the switch. New authoritative data must not be discarded or copied back into SQLite.

Legacy copies may be deleted only after the rollback window, a fresh backup/restore verification,
and explicit repository-owner approval.

## Executable evidence

```bash
.venv/bin/pytest -q tests/system/test_cutover.py
SCI_SEARCH_BACKUP_SYSTEM_TESTS=1 .venv/bin/pytest -q \
  tests/system/test_backup_restore.py::test_real_postgres_and_minio_restore_drill
SCI_SEARCH_DEPLOY_REHEARSAL=1 .venv/bin/pytest -q \
  tests/deployment/test_deploy_sequence.py::test_real_test_stack_deployment_and_rollback_rehearsal
```
