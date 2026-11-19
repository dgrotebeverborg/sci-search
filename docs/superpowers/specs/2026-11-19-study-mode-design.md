# Study mode, phase 1: the study plan — design

## Intent

Sci-Search answers one question per run. A researcher asking a broad question such as
"How much energy storage does the Netherlands need at 0, 50 and 100% solar and wind?"
needs a study, not an answer page: an interpretation, background, a check of existing
studies and models, possibly a model of its own, and a synthesis. The researcher wants
to steer that study: approve a plan first, then review and correct each chapter before
the next one builds on it. Only desk research and computation are in scope; anything
that would require real-world experiments is named as out of reach, never attempted.

Phase 1 builds the first step only: **a study plan the researcher can correct and
approve**, in a separate tool that reuses the existing parts and leaves the main app
unchanged. Chapters come in later phases.

## Goals

- From a question, produce a study plan grounded in a quick scan of what exists
  (publications, models, datasets), not only in the model's memory.
- Let the researcher correct any part of the plan, by instruction or by direct edit,
  and approve it. Every version is kept.
- Reuse existing interpretation, literature discovery, dataset discovery and model access.
- Keep the core independent of the web page so it can later move into the main app.

## Non-goals (phase 1)

- Writing chapters, running models, building models.
- Multi-user use, login, deployment. Local, single user.
- Changes to the main app, its database or its UI.
- Full-text acquisition or screening during planning.

## Anti-goals

- A plan that reads well but is not grounded: every existing study, model or dataset the
  plan names must come from the scan with its link, never invented.
- Hiding what cannot be done: work that needs real-world experiments or unavailable data
  must be stated in "Out of reach", not silently dropped.
- Corrections that silently rewrite approved or unrelated parts of the plan.

## Constraints

- Python, same repo, same `.venv`, same `.env.local`; model access through
  `configured_analyzer()` (Codex locally; OpenAI/Mistral when configured).
- Starlette/FastAPI are already dependencies; no new frontend framework or build step.
- Runs on loopback only, like `serve --unsafe-development`.
- Planning takes minutes (discovery plus model calls); the page must show progress and
  survive a reload.

## Approaches considered

1. **Command-line tool in the same repo**, plan as an editable file. Fast, but terminal-only.
2. **A page inside the existing app** (`/study`) with its login and storage. Usable by others,
   but much more work and it touches the app.
3. **Separate package importing Sci-Search.** No gain now; the two drift apart.

**Chosen (by the researcher): 1 with a very simple web page** — a separate small local
server with one page, on top of a core module that holds all logic.

## Design

### Parts

- `sci_search/study/` — the core, no web code:
  - `store.py` — study folders and versions on disk.
  - `scan.py` — the grounding scan (reuses existing discovery).
  - `planner.py` — writes and revises the plan with the model.
  - `schema.py` — the plan's JSON schema and validation.
- `sci_search/study/web.py` — a small Starlette/FastAPI app with one HTML page and a JSON API.
- `sci_search/study/static/study.html` (+ small `study.js`, `study.css`) — the page.
- CLI: `sci-search study-serve [--port 8020]`, loopback only.

### Storage

`data/studies/<study-id>/` (git-ignored, like other run data):

- `study.json` — question, status (`scanning` · `draft` · `approved` · `failed`),
  current version number, created/updated times, model used.
- `scan.json` — the scan results (interpretation, publications, datasets) as retrieved.
- `plan-v<N>.json` — each plan version, immutable once written, with what produced it
  (`initial`, `instruction: <text>`, `edit`) and the section it changed.
- `plan.md` — a readable export of the current version.

Writes go to a temporary file and are renamed into place, so a crash never leaves a
half-written version.

### The scan (grounding)

Run in a background thread; `study.json` holds progress messages for the page.

1. **Interpretation:** `interpret_question(question)`; keep the closest option's brief
   (English interpreted question, terms, place, period, route).
2. **Publications:** build a `ResearchPlan` with `plan_from_brief`, queries with
   `plan_search_queries`, then `discover_with_providers` over OpenAlex, Europe PMC and
   Crossref (titles, abstracts, years, DOIs, citation counts). No full texts. Keep the
   top ~40 by the existing ranking/deduplication (`merge_candidates`).
3. **Existing models and studies:** one extra discovery pass with queries aimed at
   models/scenario studies for the topic (e.g. "<subject> model", "<subject> scenario
   study"), same providers.
4. **Datasets:** `data_research.discovery.discover(question, strategy)` when the
   interpretation has a data strategy; candidates only (title, URL, publisher,
   rationale), no download.

Each step can fail on its own; the plan is still written from what succeeded, and the
plan's "Limits of this plan" says which scan step failed.

### The plan

One model call with a strict JSON schema. Input: the question, the interpretation, and
the scan (publications and datasets with numbered IDs). Sections:

| Section | Content |
|---|---|
| `question` | The question as understood, one paragraph |
| `definitions` | Key terms with the definition the study will use |
| `subquestions` | Ordered sub-questions |
| `scope` | Assumptions and boundaries (place, period, what is held fixed) |
| `out_of_reach` | What would need real-world experiments or unavailable data, and why |
| `existing_work` | Studies and models from the scan, each referenced by scan ID, with why it matters |
| `data` | Datasets from the scan, by scan ID, with what they would provide |
| `chapters` | Ordered chapters: title, goal, method (`literature` · `data` · `model` · `synthesis`), sub-questions answered, expected output |
| `limits` | What this plan could not ground (failed scan steps, thin evidence) |

Validation after the call: every scan ID referenced must exist (unknown IDs are
removed and noted in `limits`); every sub-question must be covered by at least one
chapter; chapter methods are from the fixed list. Links shown on the page come from
the scan, never from the model's text.

### Corrections

- **By instruction:** per section, a box "What should change?". One model call receives
  the current plan, the section, the instruction and the scan, and returns the full plan;
  only the named section may change, except that `chapters` may be updated when the
  correction affects them (e.g. a new sub-question needs a chapter). The page shows what
  changed. Other sections are compared and kept from the previous version if the model
  altered them without cause.
- **Directly:** each section can be edited as text (list items one per line; chapters as
  a small form). Saved as a new version without a model call, validated the same way.
- **Versions:** a dropdown lists versions with what produced them; any version can be
  viewed and restored (restore creates a new version, nothing is overwritten).
- **Approve:** marks the current version approved and locks editing. "Reopen" unlocks it
  (for phase 1; chapters will later depend on the approved version).

### The page

One page, no login, plain HTML/JS, the main app's look (fonts/colours) reused loosely.

- Left: list of studies (question, date, status) and "New study".
- New study: a question box and "Make study plan"; then progress messages until the
  plan appears.
- Plan view: sections in order, each with its content, an "Edit" link and a
  "What should change?" box; existing work and data shown with their links; at the top
  "Approve plan", "Versions ▾", "Download plan (.md)".

### Errors

- No model available: the page says so before starting (same check as the main app).
- A model call that fails or returns invalid JSON: retried once with the validation
  error; on second failure the study keeps its last valid version and shows the error.
- Discovery providers down: handled per scan step (see above).

### Testing

- Unit tests for store (versions, atomic writes, restore), plan validation (unknown scan
  IDs, uncovered sub-questions, invalid methods), correction merging (unchanged sections
  kept), and the scan with fake providers and a fake analyzer.
- One API test with FastAPI's test client covering new → scan → plan → correct → approve
  with fakes.
- A live check by hand on the storage question.

## Calls made in the design (check these)

- **Which version of the question:** the scan uses the interpretation's closest version;
  the researcher corrects the understanding in the plan's `question` section rather than
  choosing a card first.
- **Language:** the plan is written in English, like the rest of the pipeline (questions
  are interpreted into English); a Dutch question is understood, but the plan reads in English.
- **New topics during correction:** an instruction is applied with the existing scan. To
  bring in new material (e.g. "also look at hydrogen storage"), a separate
  "Search more" box on the existing-work section runs an extra publication/dataset scan
  for the given terms, appended to `scan.json`, after which the plan can be revised.
- **One study at a time** is scanned or revised; a second request waits with a message.
- **Model:** the configured default (`configured_analyzer()`), recorded in `study.json`;
  no model picker in phase 1. Dataset discovery is skipped (and noted in `limits`) when
  the model has no web search.

## Left to the builder

- Exact prompt wording, number of publications kept, and the extra "models" queries.
- Page styling details.
- Whether the scan runs in a thread or a subprocess (thread is the default; it must be
  cancellable on server stop).
