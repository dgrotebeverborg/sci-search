# Data research maintainability corrections

The user approved addressing the maintainability review: repair the legacy export
dependency drift, centralize retained-file validation, consolidate publication,
replace positional/shared-state coupling with explicit source/state contracts,
and distinguish internal errors from expected source failures.

Preserve numerical behavior, requested scope, immutable retained observations,
source-isolation requirements, cancellation/budget propagation, historical run
readability and offline replay. Prior uncommitted correctness fixes stay intact.
No benchmark relabeling, default-budget changes, dependency installation, merge,
deployment or broad workflow rewrite is part of this work.

Prefer small standalone standard-library helpers that can be copied into replay
packages. Shared publication must retain the distinct initial/reassessment overlap
policies. Stable source IDs coexist with positional model/API inputs through an
explicit compatibility adapter. Planning should consume an explicit state snapshot
provider instead of relying on undocumented mutations of its input dictionary
between yields. Existing generator consumers may keep a compatibility wrapper.

Expected external/model/source errors remain recoverable. Unexpected programming
errors remain distinguishable, carry developer diagnostics, and must not become
claims about source availability. Preserve partial results and cancellation.

Keep the full environment inventory as provenance, but use an explicit replay
dependency set for install requirements. Shared test builders can move to fixture
modules where touched; avoid unrelated test rewrites.
