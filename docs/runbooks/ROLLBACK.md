# Rollback runbook

A release is application-roll-back eligible only when both the previous immutable image digest and its compatible Alembic revision were recorded before deployment. The deploy state file exposes this as `rollback_eligible`; it is a prerequisite, not an automatic safety guarantee.

## Application rollback

1. Stop workers with the same bounded drain used during deployment.
2. Confirm whether the new migration is backward compatible with the recorded previous image.
3. If compatible, set `SCI_SEARCH_IMAGE` to the recorded digest, start only `web`, and require `/health/ready` to pass.
4. Start workers at the same previous digest and run the two-user smoke test.
5. Record the incident, image digests, schema revision, and correlation IDs.

## Schema rollback

Do not downgrade merely because the new application failed. An Alembic downgrade can destroy data. Use it only when the migration's release notes explicitly certify the downgrade, an encrypted pre-release backup has a verified completion marker, and the incident lead approves it. Run the downgrade through `scripts.migrate` so the advisory lock is held.

If backward compatibility or downgrade safety is unknown, keep workers stopped and restore the pre-release backup into new database and bucket names. Verify it fully before changing production endpoints. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md).

## Rehearsal

For every release, exercise the recorded command sequence against the isolated test stack: previous image → candidate image → readiness → previous image. Confirm no duplicate evidence or artifacts after worker recovery. A command-order unit test is not a substitute for this rehearsal.

