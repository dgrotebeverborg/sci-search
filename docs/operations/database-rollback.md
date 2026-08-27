# Database migration and rollback

Sci-Search changes PostgreSQL only through explicit Alembic migrations. Application startup must
never create or alter tables.

## Before deployment

1. Stop new research jobs and wait for active database transactions to finish.
2. Back up PostgreSQL and the object store as one recovery point.
3. Record the current application image and Alembic revision.
4. Run `alembic upgrade head` with the production database URL supplied through deployment
   secrets.
5. Start the new image and verify readiness before admitting traffic.

## Supported Program 3 rollback

The application image immediately before the legacy-import checkpoint expects revision
`0002_research_storage`. To roll back that checkpoint:

1. Disable imports and stop web and worker processes.
2. Confirm no import is active and preserve a fresh database backup.
3. Run `alembic downgrade 0002_research_storage`.
4. Start the previous application image and verify that projects, documents, grants, runs,
   evidence, validation checks, reviews, and artifacts remain readable.

This downgrade removes only the `legacy_imports` ledger. It does not delete imported documents or
research records. Do not re-run a legacy import until the ledger migration has been restored and
the imported project has been checked for duplicates.

Downgrading farther to `0001_identity_projects` drops all Program 3 research-storage tables and is
destructive. It is not an operational rollback. Restore the pre-migration backup instead if the
service must return to a Program 2 image.

## Verification

After either forward migration or rollback, check the Alembic revision, application readiness,
project-scoped document access, and one exact-provenance evidence record. Blob objects are not
deleted by database downgrade; content cleanup is a separate, explicitly approved lifecycle task.
