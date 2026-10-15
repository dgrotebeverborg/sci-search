# Question Choices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the fixed interpretation screen with clickable versions of the question and
clickable choices per detail, and allow data for projections to 2100.

**Architecture:**
- The model call that interprets a question also returns `options` and `clarification_options`.
- `sci_search/question_choices.py` turns each option into a validated brief and applies a
  researcher's change to a brief without a model call.
- A new route `POST /runs/interpret/adjust` exposes those changes.
- `runs.js` delegates the new screen to `question_choices.js`.

**Tech Stack:** Python 3.11, FastAPI, vanilla ES modules, pytest, Playwright, ruff.

**Spec:** `docs/superpowers/specs/2026-10-15-question-choices-design.md`

## Global Constraints

- The screen stays English; the brief keeps `original_question` as the researcher's own text.
- Every brief that leaves the server passes `plan_from_brief` and, when it has a data strategy,
  `validate_strategy`. `adjust` returns a valid brief or raises `ValueError`, which the route
  turns into a 422 with that reason.
- Model output is untrusted. Options that fail validation are dropped, never repaired silently.
- The EFFIS curated brief (`effis_reported_fires_v1`) keeps its existing screen.
- Use `.venv/bin/python`. Test and lint commands as in the previous plan.

## Review Focus

1. **A model that returns no `options`** (an older provider or a failed parse) must still give
   one card built from the main brief.
2. **Choosing data when no measurement is set** must give a readable reason and block Start.
   It must not raise a 500 error.
3. **A free-typed geography or period** must produce a valid brief:
   - typed countries are not guessed;
   - years outside 1800 to 2100 are rejected.
4. **An interpretation that comes back after the researcher changed the question** must be
   ignored. The existing `interpretationVersion` guard must still apply to steering and
   clarification.
5. **The brief sent to start a run** must contain the adjusted values, and must not contain the
   options list.

---

### Task 1: Projections in the data strategy

**Files:**
- Modify: `sci_search/data_research/strategy.py`:
  - year rule: `end_year` up to 2100, `start_year` not after the current year;
  - `PROMPT` sentences on projections and data versions.
- Modify: `sci_search/data_research/semantics.py`: add one sentence to `INSTRUCTIONS`.
- Test: `tests/test_data_strategy_projection.py`.

Tests:
- `end_year=2100` is accepted.
- `end_year=2101` is rejected.
- `start_year` = the current year + 1 is rejected.
- `start_year` > `end_year` is rejected. Check whether the existing code already rejects it,
  and keep that behaviour.
- `PROMPT` mentions projected variables.

### Task 2: Options and changes (`sci_search/question_choices.py`)

**Interfaces (produces):**
- `OPTION_SCHEMA`: the JSON schema of one option. Required fields:
  - `title`
  - `summary`
  - `closest`
  - `interpreted_question`
  - `objective`
  - `research_plan`
  - `research_strategy`
  - `alternatives`

  `alternatives` holds:
  - `route`: an array of route enums;
  - `measurements`: an array of string arrays;
  - `geography`: `[{label, geography_terms, countries}]`;
  - `period`: `[{label, start_year|null, end_year|null}]`.
- `option_briefs(question, base_brief: dict, raw_options: list) -> list[dict]` returns
  `[{title, summary, closest, brief, alternatives}]`, with the closest option first. It drops
  invalid options; when none survives, it uses the base brief as one option titled
  "Your question".
- `adjust(brief: dict, change: dict) -> dict` applies route, measurements, geography or period
  (the spec's shapes) and raises `ValueError` with a readable reason.

Tests (`tests/test_question_choices.py`):
- Two valid options and one invalid option give two options, with the closest first.
- No options gives one option built from the base brief.
- Each detail change updates both the plan and the strategy:
  - geography updates `geography_terms`, the strategy's `geography` and `countries`;
  - period updates `time_terms` and the years.
- Choosing route `data` without measurements raises "Choose or type at least one measurement
  for data research."
- Measurements on a literature-only brief create a strategy and keep the route.
- A free-typed geography is accepted with empty countries.
- An unknown detail is rejected.
- The adjusted brief passes `plan_from_brief`.

### Task 3: Interpretation returns options, steering and clarification

**Files:**
- Modify: `sci_search/question_interpretation.py`:
  - the schema gains `options` (up to 4) and `clarification_options` (up to 4 strings);
  - the prompt sentences;
  - `interpret_question(question, analyzer=None, *, steer=None, clarification=None)` passes
    them to the model;
  - the result dict gains `options` and `clarification_options`;
  - the deterministic and failure paths return one option.
- Modify: `sci_search/application/research_api.py` and
  `sci_search/infrastructure/production_services.py`:
  - `interpret_question(..., steer=None, clarification=None)`;
  - new `adjust_brief(user_id, project_id, brief, change)` with the same permission check.
- Modify: `sci_search/api/schemas.py`: `QuestionInterpretationCreate` gains `steer` and
  `clarification`.
- Modify: `sci_search/api/routes/runs.py`: the `interpret` route passes them; new
  `POST /interpret/adjust` route.
- Test: `tests/test_question_choices.py` (interpretation with a scripted model) and
  `tests/api/test_question_choices_api.py`.

Tests:
- A scripted model response with three options gives three options.
- The `steer` and `clarification` values appear in the model's user message.
- No analyzer gives one option.
- The adjust route returns 200 with a changed brief, a 422 with the reason for an invalid
  change, and requires CSRF.

### Task 4: The screen (`question_choices.js`)

**Files:**
- Create: `sci_search/frontend/static/question_choices.js` with
  `renderChoices(interpretation, {project, onBrief, onInterpret})`, which renders:
  - the cards;
  - the detail rows with chips and an "Edit…" chip;
  - the steering row;
  - the clarification chips.
- Modify: `sci_search/frontend/static/runs.js`:
  - use `renderChoices` for every brief that is not EFFIS;
  - remove the old `discovered_data_v1` controls and the disabled data options;
  - keep `questionBrief` set to the chosen, adjusted brief, without `options`;
  - gate Start on a valid brief.
- Modify: `sci_search/frontend/static/app.css`: choice styles in UU yellow.
- Test: `tests/browser/test_question_choices.py` with a scripted interpretation. Update
  `tests/browser/test_question_confirmation.py` and `test_autonomous_data.py` wherever they used
  the old controls.

Browser test:
1. Cards are shown, with the closest one first.
2. Choosing the second card shows its details.
3. Clicking a geography chip calls adjust, and the row updates.
4. "Edit…" on Measurements takes typed text.
5. "More data" calls interpret with a steer.
6. A clarification chip calls interpret with a clarification.
7. Start sends a brief without `options`, with the adjusted values.
8. No route option is disabled.

### Task 5: Real check and docs

- Restart the app and ask the Himalaya question with Codex. Record the options, and whether a
  data or both option with projected measurements to 2100 appears.
- README: one paragraph on choosing a version of the question.
