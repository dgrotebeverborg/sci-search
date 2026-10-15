# Executable data research implementation plan

Goal: every new data result is produced by retained executable Python, and unfamiliar downloaded tables can be recovered by model-written extraction code with bounded repair.

User approved the redesign and requested implementation on 2026-10-09. Execute inline in the existing workspace; preserve all pre-existing work. No commit or deployment is required. This plan records the agreed chat design rather than introducing another approval gate.

Architecture: retain the existing discovery and checked adapters. Add a Linux bubblewrap runner for untrusted extraction scripts, a generated-script repair loop, and a shared executable calculation artifact for both generated and existing adapters. Numerical publication depends on execution and validation. Keep the existing annual-series UI contract; generated extraction broadens input structures, not the scientific scope of that contract.

## Tasks
- [x] Add a real isolated runner; test filesystem/network/environment isolation, timeouts, cancellation, output limits, symlink rejection and unavailable isolation.
- [x] Add Python extraction from unfamiliar downloaded data, bounded repair and independent semantic assessment; validate rows, finite values, units, requested measurements, unique series/year and source references.
- [x] Execute and retain a calculation script for existing adapters and generated extraction before publishing; record hashes, runtime dependencies, attempts and offline replay.
- [x] Integrate recovery into source processing and preserve partial results; expose execution and validation in dashboard/report/package.
- [x] Run targeted, regression and browser checks; inspect a live model-generated extraction; restart the local app after verification.

## Review focus
- Untrusted code must never run on the host as a fallback when isolation fails.
- Failed or cancelled attempts must not publish stale output from another attempt.
- A replay package must execute retained code, check hashes and compare results, including missing observations.
- Model review is not proof of scientific correctness; provenance and assumptions remain visible.
- Existing dashboards and offline replay for old packages remain compatible.

## Implementation decisions
- Generated code has no network; source acquisition remains in the existing public downloader. Browser-only portals and arbitrary authenticated APIs remain explicit access gaps.
- First execution supports Python standard library plus installed data extras (pandas/openpyxl) and pypdf. No runtime package installation by generated code.
- Public data-only runs remain annual descriptive analyses. General non-temporal statistical analysis is outside this implementation's output contract.
- Real isolation tests require execution outside the enclosing Codex sandbox, whose network-namespace restrictions otherwise prevent bubblewrap startup.

## Verification and review
- Combined data/browser/local API/cancellation regression: 156 passed. Final artifact/runner/extraction/CSV/wildfire checks after package changes: 49 passed.
- Independent read-only code review identified writable temporary mounts and missing aggregate replay comparison. Both reproduced with regression tests and fixed. Temporary storage is 64 MiB; root, devices and proc are read-only; child processes are disabled. Replay checks top-level published analyses and fails for changed/missing source results.
- Live Codex gpt-6-sol generated extraction on the EFFIS workbook retained by the user's failed 2026-10-09 run. The first experiment caught both a coding mistake and insufficient source preview. Inspection was expanded. The accepted experiment explicitly asked for reported burned area, not a forest-only measure unsupported by the workbook metadata. It produced three 24-year series after one repair.
- Accepted live artifact: `/tmp/sci-search-live-python-20261009T075050`. Offline replay succeeded. An independent openpyxl check matched all 72 published values to original cells (normalizing the workbook's thousands-separator spaces).
- Ruff and diff whitespace checks pass. New modules: Pyright 0 errors, 0 warnings.
- First broad run: 903 passed, 17 skipped, 33 setup errors because test services had not yet been started; 4 order-dependent failures. Integration/system rerun with PostgreSQL/Redis/MinIO ready: 74 passed, 2 skipped. All 4 failing scientific/data tests passed independently.
- Root cause of order dependence: CLI contract and investigation tests loaded the developer's `.env.local` even for `--help`, leaving live model configuration in later deterministic tests. The shared test fixture now isolates that CLI loader; configuration-loader behavior remains covered separately. A contracts-only isolation experiment was interrupted when the investigation CLI reintroduced live settings; the shared fixture fixes both callers.
- Final full suite: **940 passed, 17 skipped, 2 subtests passed**, with one timeout in the pre-existing browser test `test_local_workspace_preview_keeps_research_disabled_after_project_creation[workspace-preview]` (Create project stayed disabled). The complete `tests/browser/test_projects.py` rerun then passed all 6 tests in 1.82 seconds without product changes. This is an intermittent browser failure, not a claim that the full run was entirely green.
- Final extraction/artifact tests after validating generated note shapes: 16 passed. Ruff/diff checks pass; new modules have Pyright 0 errors, 0 warnings. Original real extraction was also replayed offline and independently checked cell-by-cell.
- Review boundaries: arbitrary scientific correctness is not established by the model review; browser-only acquisition, OCR and non-annual analysis remain unsupported in this version. No unrelated pre-existing implementation was rewritten.
- Local app restarted on port 8010; login page returned HTTP 200. No commit, push or deployment performed. Container dependency configuration updated, but no production container deployment was tested.
