# Backup and restore runbook

Sci-Search is recoverable only when both PostgreSQL and the S3-compatible object bucket are captured by one completed, encrypted backup and that backup passes an isolated restore drill. A copied database alone is not a Sci-Search backup: it omits source PDFs, extracted artifacts, and generated reports.

## Schedule and retention

- Run an encrypted backup every 24 hours and before every migration or release.
- Retain daily backups for 14 days, weekly backups for 12 weeks, and monthly backups for 12 months, subject to the institution's research-data policy.
- Copy completed backup directories to storage outside the Docker host. Replication begins only after `COMPLETE` exists.
- Alert when the latest `COMPLETE` marker is more than 26 hours old, when backup execution fails, or when available backup storage falls below two full-backup estimates.
- Perform and record an isolated restore verification every quarter and before shortening retention.

## Encryption and key custody

The backup command refuses plaintext output. Use an `age` recipient owned by the institutional operations team; do not use an application session or OIDC secret as an encryption key. Keep the private identity in the institutional secrets manager, with recovery access held by at least two authorized operators. Test key recovery during each quarterly drill.

Example from an administrative container, with the backup destination mounted at `/backups`:

```sh
docker compose --profile admin run --rm \
  --volume /srv/sci-search/backups:/backups \
  web backup \
  --destination /backups/2026-08-27T020000Z \
  --encryption-command '["age","--recipient","age1replace-with-operations-recipient","--output","{output}","{input}"]'
```

The command writes into a private partial directory, verifies the database dump and every downloaded object, encrypts one archive, removes plaintext staging data, writes `manifest.json` and `COMPLETE`, and atomically renames the finished directory. Never replicate a `.partial-*` directory.

## Isolated restore drill

Create a new empty PostgreSQL database and a new empty bucket. Their names must differ from the source identifiers recorded in the manifest. Never point a restore at production.

```sh
docker compose --profile admin run --rm \
  --volume /srv/sci-search/backups:/backups:ro \
  --volume /run/secrets/backup-age-key:/run/secrets/backup-age-key:ro \
  web restore \
  --source /backups/2026-08-27T020000Z \
  --database-url "$SCI_SEARCH_RESTORE_DATABASE_URL" \
  --s3-bucket sci-search-restore-2026q3 \
  --decryption-command '["age","--decrypt","--identity","/run/secrets/backup-age-key","--output","{output}","{input}"]'

docker compose --profile admin run --rm \
  --volume /srv/sci-search/backups:/backups:ro \
  web verify-restore \
  --source /backups/2026-08-27T020000Z \
  --database-url "$SCI_SEARCH_RESTORE_DATABASE_URL" \
  --s3-bucket sci-search-restore-2026q3
```

Verification must report `ok: true`. It compares the migration version, every table count, project-document grant count, the first and last audit records, object sizes, object SHA-256 hashes, and therefore generated report artifacts represented in object storage. Record the backup ID, drill date, operator, result, and cleanup ticket.

## Failure handling

- A missing or mismatched `COMPLETE` marker means the backup is unusable.
- A checksum, row-count, grant, audit-endpoint, or report-object mismatch fails the drill. Preserve the failed target for diagnosis and do not weaken verification.
- If decryption fails, validate key custody and the encrypted-payload checksum before retrying.
- If `pg_restore` fails, preserve its exact exit status, inspect schema compatibility, and restore into another new empty database.
- Delete isolated drill data only after the result has been reviewed and recorded. Production restoration requires incident-lead authorization and follows the deployment rollback runbook.
