# Legacy data inventory

Run the inventory before any import. It opens SQLite read-only, reads retained run files without
modifying them, contains all resolved paths below the selected root, and stops at a configurable
record bound.

```bash
python scripts/inventory_legacy_data.py data --output legacy-inventory.json
```

The deterministic JSON records source fingerprints, publications, runs, evidence counts, unique
blob hashes and reference counts, unreadable inputs, incomplete/invalid runs, and conflicting
metadata variants. Review every reported error and conflict. An inventory is evidence for an
import decision; it is not permission to delete or rewrite the source tree.
