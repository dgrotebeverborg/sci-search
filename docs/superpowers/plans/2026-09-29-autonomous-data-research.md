# Autonomous Data Research Implementation Plan
Goal: execute source discovery and reproducible data research from questions in the running app.
Architecture: model strategy -> bounded web search -> observed source retrieval -> checked adapter or declarative CSV -> durable result, optionally combined with existing literature workflow.
Execution: inline, preserving the existing uncommitted workspace. User has authorized implementation; no additional approval gates or commits.
- [x] Add tested strategy validation and schema to question interpretation.
- [x] Add bounded source discovery transport, retained citations and source assessment; public-only downloader.
- [x] Add generic CSV annual-series validation, calculations and reproducible exports.
- [x] Orchestrate discovery/adapters and integrate data/both routes in ResearchRunManager.
- [x] Show plan, source decisions, failures, charts and actual model usage in dashboard; export both branches.
- [x] Run unit/browser/regression checks and live wildfire + non-wildfire acceptance checks; restart local app.


## Verification and decisions
- Full regression run: 808 passed, 17 skipped, 2 subtests passed.
- Subsequent offline replay fix and browser checks: 23 passed.
- Two independent live runs completed through the app using gpt-6-sol:
  wildfire 9012cf29-494e-4bd2-bfda-904be3329b00; CO2 8c0a3ad4-c022-48ae-998b-554f1789c0d0.
- Both downloaded packages independently replayed retained calculations offline; live HTML/ZIP
  downloads returned successfully; desktop/mobile dashboards rendered without page errors or
  horizontal overflow.
- Wildfire explicitly requested 46 countries; fixed panel 22, 2001–2024, missing 2025.
- CO2 autonomously found NOAA annual CSV, selected 2001–2024, units ppm; source rows 87–110.
- Ruling: bounded supported formats, not unrestricted generated code. Unsupported APIs/formats are
  visible source gaps. Models assess source fit; this is not expert validation.
- Independent read-only code review completed; findings addressed with regression tests, including
  empty data, geographic negation, recoverable source errors, multi-metric CSV, blocked replay,
  combined report/export preservation and display precision.
- No commit, merge or deployment; existing workspace edits preserved and local app restarted.
