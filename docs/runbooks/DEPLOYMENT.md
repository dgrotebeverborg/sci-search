# Deployment runbook

Deploy only immutable image digests. The deployment state machine is intentionally backup-first and keeps workers stopped until the new web process passes dependency-aware readiness.

## Preconditions

1. CI has passed deterministic scientific, isolation, browser, migration, package, container, and security gates for the image digest.
2. Production secret files exist with operator-only permissions; no secret is placed in the Compose file or deployment-state file.
3. The previous image digest and the Alembic revision to which it can roll back are recorded.
4. There is capacity for a new encrypted backup, and the latest quarterly restore drill is current.
5. Announce the maintenance window. Starting new research runs should be temporarily disabled at the ingress or operational level.

## Execute

The backup command is a JSON argument array so it is executed directly without a shell. Its destination must be a new path on the mounted off-host backup filesystem.

```sh
python -m scripts.deploy \
  --hostname search.example.edu \
  --confirm-production 'DEPLOY search.example.edu' \
  --backup-command '["docker","compose","run","--rm","web","backup","--destination","/backups/pre-release-20260827","--encryption-command","[\"age\",\"--recipient\",\"age1operationsrecipient\",\"--output\",\"{output}\",\"{input}\"]"]' \
  --readiness-url https://search.example.edu/health/ready \
  --drain-timeout 300 \
  --state-file /var/lib/sci-search/deployments/20260827.json \
  --previous-image registry.example.edu/sci-search@sha256:PREVIOUS \
  --migration-rollback-revision 0005_risk_of_bias
```

The recorded order is:

1. complete an encrypted backup;
2. stop accepting worker messages and give the worker a bounded graceful-stop interval;
3. run Alembic under the PostgreSQL session advisory lock;
4. start the new web image;
5. require `/health/ready` to pass PostgreSQL, Redis, and object-store checks;
6. release workers.

If the bounded worker stop expires, in-flight leases remain authoritative in PostgreSQL and are reclaimed after expiry. Do not manually mark the corresponding jobs complete.

## Validate

- Confirm the state file ends at `released` and contains no credentials.
- Check `/health/live`, `/health/ready`, and bounded Prometheus metrics.
- Authenticate two institutional test subjects, open their separate private projects, and start one small run in each.
- Verify worker heartbeat/lease metrics, exact-passage provenance, export download, and deterministic answer withholding.
- Keep the previous image and pre-release backup through the rollback window.

## Failed deployment

The state file records the failed phase. Workers are not released if readiness fails. Preserve logs by correlation ID, follow [ROLLBACK.md](ROLLBACK.md), and never skip a failed migration or readiness check merely to complete the state sequence.

