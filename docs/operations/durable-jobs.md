# Durable job operations

PostgreSQL is authoritative for job status, stage attempts, leases, and checkpoints. Redis carries
only opaque `(job_id, stage_name)` wakeups. Losing or duplicating a Redis message must not create a
second scientific result.

## Drain workers for deployment

1. Stop accepting new durable research submissions.
2. Keep workers running until active leases reach a stage boundary.
3. Request cancellation for jobs that cannot finish within the deployment window.
4. Wait until no jobs are `running` or `cancel_requested`, then stop workers.
5. Deploy, migrate, start workers, and re-enable submissions after readiness succeeds.

Do not delete Redis keys to drain work. If Redis is lost, enqueue the current stage of each queued
or lease-expired PostgreSQL job again; duplicate delivery is safe.

## Failed jobs and retries

Transient failures are retried only to the configured bound. Exhausted or deterministic failures
remain `failed` and receive a `job.dead_lettered` audit event. An operator should inspect the stage,
attempt category, input fingerprint, and provider health before using the application retry action.
Never edit job or checkpoint rows manually. A retry must retain prior attempts and checkpoints.

## Cancellation

Queued cancellation is immediate. Running cancellation is cooperative: workers check before and
after each stage, and bounded acquisition or gap-search loops use the supplied cancellation token
between iterations. Completed checkpoints remain available; a cancelled stage cannot publish its
output or enqueue a later stage.

## Recovery and rollback

After a worker crash, wait for its lease to expire and redeliver the job's current stage. The next
worker records the abandoned attempt as `lease_expired`. Verify that checkpoint, document, and
evidence uniqueness constraints remain satisfied.

To roll back Program 4:

1. Disable durable submissions and drain or cancel all non-terminal jobs.
2. Back up PostgreSQL and object storage.
3. Stop workers and the web process.
4. Run `alembic downgrade 0003_legacy_import`.
5. Start the previous image and use the retained `ResearchRunManager.run_sync` compatibility path.

The downgrade removes job, checkpoint, and attempt history. It does not remove projects, imported
research data, documents, or evidence. Restore from backup rather than downgrading while useful
jobs are active or their operational history must be retained.
