# Production import rehearsal

Date: 2026-08-27

The retained local corpus was copied to a protected temporary tree. The importer read that copy,
wrote to a freshly migrated PostgreSQL database and a separate blob root, and then rescanned the
protected source to prove that its fingerprint had not changed.

## Sanitized result

- Full-text-backed publications mapped: 560 / 560
- Research runs mapped: 45 / 45
- Provenance-bearing evidence records mapped: 594 / 594
- Unique document blobs created: 556
- Blob hashes matched: 560 / 560 document references
- Unexplained losses: 0
- Source mutation: none; before/after fingerprints matched
- Result: PASS

The source fingerprint and record-level mappings are deliberately stored in the target import
ledger rather than this repository. No publication content, identifying user data, API secrets, or
absolute source paths are included here.

## Operational behavior

Imports commit bounded batches and record the next source offset after every batch. Re-running an
interrupted import resumes from the ledger; re-running a completed fingerprint is a no-op.
Publication metadata disagreements are retained under `legacy_source_variants`. The parity command
fails when any mapped publication, blob hash, run question, evidence passage, section, or page no
longer agrees with the source manifest.

Rehearsal command:

```bash
SCI_SEARCH_PROTECTED_LEGACY_ROOT=/path/to/protected-copy \
  .venv/bin/pytest -q -s \
  tests/system/test_production_import.py::test_protected_current_tree_import_has_exact_parity
```
