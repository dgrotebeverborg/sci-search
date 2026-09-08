# Incident response runbook

Preserve scientific provenance and tenant isolation while restoring service. Assign an incident lead, record UTC timestamps, and use correlation IDs rather than copying research questions, passages, tokens, or source documents into tickets or chat.

## Compromised browser session

1. Revoke all server-side sessions for the affected internal user ID; do not identify the account by email alone.
2. If identity-provider compromise is suspected, disable access at the institutional identity provider and rotate the OIDC client secret.
3. Review bounded audit events for affected project operations. Do not expose other projects while investigating.
4. Require reauthentication and verify old opaque cookies remain invalid.

## Provider outage or invalid model output

- Leave PostgreSQL jobs and evidence authoritative; Redis messages are only wakeups.
- Allow bounded retry for transient discovery/acquisition failures.
- For model failures or grounding rejection, preserve the validation audit record and use the deterministic extractive fallback. Never publish an unvalidated model answer to clear a queue.
- If a provider remains unavailable, stop scheduling that provider, disclose reduced coverage in reports, and monitor queue age.

## Leaked secret

1. Remove the secret from its upstream authority, not merely from a container.
2. Rotate the affected database, Redis, S3, session, OIDC, or model credential independently.
3. Restart only processes that consume it and verify readiness.
4. For a session-secret leak, revoke all active server-side sessions.
5. Search logs and build context with the secret scanner; never paste the leaked value into a ticket.

## Failed migration or deployment

Keep workers stopped, preserve the deployment-state file, and follow [ROLLBACK.md](ROLLBACK.md). The migration command holds a PostgreSQL advisory lock, so investigate another apparent migration process before breaking or bypassing the lock.

## Suspected data loss or corruption

Make the affected storage read-only where possible, preserve logs, and stop workers. Restore the latest eligible encrypted backup into isolated new targets and run full verification. Switch production only with incident-lead approval after row counts, grants, audit endpoints, report artifacts, and object hashes match.

