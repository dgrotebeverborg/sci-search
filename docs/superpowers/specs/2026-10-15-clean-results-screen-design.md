# Clean results screen — design

Date: 2026-10-15. Branch: `feature/clean-results-screen` (on top of PR #3).

## Goal

A researcher who opens a result first sees the answer and how certain it is, then why it is
that certain. Everything else is one click away and hidden by default. The screen must be as
clean and uncluttered as possible.

Decisions confirmed with the researcher:

- First: the answer and its certainty, with the key sources (option 1).
- Then: why the evidence is strong or weak — which studies count, which were left out and why,
  what is missing (option 2).
- Certainty is one label with one sentence of explanation (option 1).
- A question answered from data and literature shows a short joint conclusion, then a data
  part and a literature part (option 2).
- The research landscape stays, collapsed, after the explanation.
- The researcher left the visual design to me, with the instruction: as clean as possible.

## Problems with the current screen

- Five tabs and thirteen blocks; "Findings" overlaps "Literature review", "Studies" overlaps
  "Evidence".
- The answer block repeats the verdict three times: summary, adequacy decision, quality label.
- Expandable panels print internal fields (`coverage:geography:sweden`, `publication_count`).
- The data result sits inside the answer block, so data and literature are not distinguishable.

## Architecture

### Server: `sci_search/result_summary.py` (new)

`summarize(snapshot: dict) -> dict` is a pure function over a dashboard snapshot (the blocks
and `result_quality` that `build_dashboard` already produces). It makes no model calls and
changes no evidence.

- `build_dashboard` adds `snapshot["summary"] = summarize(snapshot)` to new snapshots.
- `GET /runs/{run_id}/dashboard` recomputes `summary` on every read, so saved runs from
  before this change get it too, and later rule changes apply to them without a rebuild.

The summary contains only display-ready text and links:

| Field | Content |
|---|---|
| `answer` | `{text, evidence_ids}` from the executive summary; when the answer is withheld, the withholding reason. |
| `certainty` | `{level, label, sentence}`. `level` is one of `strong`, `moderate`, `weak`, `insufficient`, `not_assessed`. |
| `key_sources` | Up to 5 publications or datasets: `{title, year, publisher, url, kind}`. Ordered by citations in the answer, then by evidence passages. |
| `data` | Present when the data route ran: datasets analysed `{title, publisher, url, entities, first_year, last_year, unit}` and the number of sources rejected. |
| `literature` | Present when the literature route ran: counts `{found, full_texts, included, uncertain, excluded}`. |
| `included` | Studies that count as evidence: `{title, year, url, reason}`. |
| `left_out` | Up to 10 studies whose full text was read but did not count: `{title, year, url, decision, reason}`. Excluded and uncertain studies come first. |
| `missing` | Plain sentences, one per failed requirement. |
| `landscape_line` | For example "312 studies found, 1990–2025; 3 count as evidence." |

### Certainty rules

The level builds on the existing `result_quality` status and the adequacy checks:

| Level | When |
|---|---|
| `strong` | `result_quality` is `adequate`. |
| `moderate` | `partial`, at least the required number of independent publications, and at most one failed required check. |
| `weak` | `partial` otherwise, or a data answer with coverage limits. |
| `insufficient` | `insufficient`. |
| `not_assessed` | No adequacy was recorded. |

The labels are "Strong evidence", "Moderate evidence", "Weak evidence", "Not enough evidence"
and "Not assessed".

The sentence names what supports the answer and the most important gap, for example:

> 3 studies from the Netherlands and Sweden count as evidence; none links HPV vaccination
> directly to incidence, and the United Kingdom is missing.

The sentence is assembled from fixed templates, not written by a model:

- the number of included studies;
- the requested places they cover;
- the first one or two `missing` items.

### Plain-language missing items

Each failed required adequacy check becomes one sentence:

| Check kind | Sentence |
|---|---|
| geography | "No included study covers {place}." |
| subject part | "No included study covers {part}." |
| population, time, outcome, topic | "No included study covers {label}." |
| driver (relationship) | "No included study links {driver} to the outcome." |
| independent publications | "No single passage answers the whole question." when the count is 0; otherwise "{n} of {minimum} required studies answer the whole question." |
| trend checks | "No study reports a change over time for the requested period." |
| other | The check's label, capitalised, as a sentence. |

Labels are shown as the researcher wrote them: place names keep their capitals.

## Screen

One page, no tabs. From top to bottom:

1. **Header** — the question, run date, and the **Download all** button.
2. **Answer** — the answer text, the certainty label as a coloured pill with its sentence, and
   the key sources as a short linked list.
3. **Data** — only when the data route ran. One compact card per analysed dataset:
   - title, publisher and link;
   - countries or entities, years and unit;
   - the existing chart.

   Rejected sources sit behind a "Sources not used (n)" toggle.
4. **Literature** — only when the literature route ran:
   - the key findings with their citations;
   - "Where studies disagree", when present.

   The full literature review sits behind "Read the full review".
5. **Why this certainty**:
   - the included studies, each with title, year and reason;
   - the studies left out, each with title, decision and reason;
   - what is missing, as a short list.
6. **Research landscape** — collapsed, showing `landscape_line`. When opened, it shows the
   existing landscape (timeline, authors, topics, study browser).
7. **More details** — collapsed:
   - the question interpretation and scope;
   - the search queries and methods;
   - validation;
   - all evidence passages;
   - references;
   - downloads.

   Raw records stay available here, but under readable headings.

### Visual rules

- One column, maximum width about 760 px, generous spacing; no cards inside cards.
- Two text sizes in the body, one accent colour; the certainty pill is the only coloured
  element in the answer:
  - green for strong;
  - amber for moderate and weak;
  - grey for not enough evidence and not assessed.
- Collapsed sections use native `<details>` with a one-line summary, so they work without
  JavaScript state and with the keyboard.
- No internal identifiers, JSON keys or snake_case labels outside "More details".
- Empty sections are not shown; there are no "No X was retained" placeholders.

## Error handling

- `summarize` never raises on a saved snapshot. Missing parts give empty fields, and the
  certainty level falls back to `not_assessed`.
- A summary failure on read is logged, and the screen shows the answer and "More details" only.

## Testing

- `tests/test_result_summary.py`, with snapshots built through `build_dashboard` from the five
  real runs' shapes:
  - HPV is weak: 3 included, and the sentence names the missing link and the United Kingdom;
  - insects comes from data, with dataset, entities and years;
  - euro is not enough evidence, with plain missing sentences;
  - a saved snapshot without adequacy is not assessed;
  - no internal identifiers appear in any text field.
- An API test checks that `GET /dashboard` returns `summary` for a snapshot saved without one.
- The browser tests in `tests/browser/test_saved_dashboards.py` (and others that select tabs)
  are updated to the single page. A new browser test checks the order of the sections, that
  "More details" and the landscape start collapsed, and that no internal identifiers are
  visible.
- The full unit suite and ruff must pass. Afterwards the five saved runs are opened in the
  local app and compared with the old screen.

## Out of scope

- Editing measurements in the question brief, and the data-route option being disabled
  (a separate design).
- A data answer that misses countries continuing with literature (a separate fix).
- GRADE-style certainty ratings.
