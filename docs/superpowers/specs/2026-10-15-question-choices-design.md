# Question choices — design

Date: 2026-10-15. Branch: `feature/question-choices` (on top of `feature/clean-results-screen`).

## Goal

Getting the right interpretation of a question becomes a short, clickable workflow. The
researcher never has to rewrite the question:

- The AI proposes a few versions of the question.
- The researcher clicks one and sees its details.
- Each detail offers clickable alternatives, with free editing as the last option.

Data stays possible whenever data could answer part of the question, including projections to 2100.

Decisions confirmed with the researcher:

- The AI proposes 2–4 versions of the question as clickable cards.
- After a card is chosen, its details are visible and adjustable. Every detail offers clickable
  choices, and editing it by hand is the last option.
- A clarification is answered by clicking one of the proposed answers, not by typing.
- Small steering buttons ("Narrower", "Broader", "More data", "More literature") produce a new set
  of cards.

## Problems today

- **The data route is locked.** When the interpretation chooses literature, the measurement list
  may be empty, and the "Find and analyse datasets" and "Datasets and literature" options are
  disabled (`runs.js`, when `scope.measurements` is empty). For example, "How does melting of
  Himalayan glaciers affect downstream water availability until 2100?" cannot use data.
- **Projections are excluded.** `validate_strategy` rejects any year after the current one, and
  its prompt says measurements are *observed* base variables. Questions about the future
  therefore never reach the data route, although modelled glacier mass and runoff per basin and
  scenario are published.
- **Unclear questions cost a rewrite.** When the interpretation needs clarification, the
  researcher reads an open question and has to type a new question.
- **Details can't be changed.** Measurements, geography and period are shown as fixed text.

## Interpretation result

`interpret_question` returns the brief it returns today, plus two new fields:

- `options`: 2 to 4 versions of the question. Each option is a complete, validated brief proposal:
  - `title` (at most 80 characters);
  - `summary`, one sentence on what is studied and how;
  - `route`;
  - `research_plan`;
  - `research_strategy`.
  The first option stays closest to the original question and is marked `closest: true`.
- `clarification_options`: when the ambiguity is material, 2 to 4 short answers to the
  clarification question.

Each option also carries `alternatives` for its adjustable details. These are proposals the
researcher can click:

| Detail | Alternatives | What applying one changes |
|---|---|---|
| Route | literature, data, both | the strategy's `route` |
| Measurements | up to 4 sets, each a list of measurement names | the strategy's `measurements` |
| Geography | up to 4, each `{label, geography_terms, countries}` | the plan's `geography_terms`, and the strategy's `geography` and `countries` |
| Period | up to 4, each `{label, start_year, end_year}` | the plan's `time_terms`, and the strategy's `start_year` and `end_year` |

The model call stays one call: the existing schema grows by `options` and
`clarification_options`.

Every option is checked with the existing validation (`plan_from_brief`, `validate_strategy`):

- An option that fails validation is dropped.
- When none survives, the main brief is used as the only option.

The brief sent to start a run is built from the chosen option, so `original_question` remains the
researcher's own question.

## Applying a choice

`POST /api/v1/projects/{p}/runs/interpret/adjust` takes `{brief, change}` and returns a
validated brief. It makes no model call. `change` is one of:

- `{"detail": "route", "value": "both"}`
- `{"detail": "measurements", "value": ["projected glacier runoff"]}`
- `{"detail": "geography", "value": {"label": …, "geography_terms": […], "countries": […]}}`
- `{"detail": "period", "value": {"label": …, "start_year": 2000, "end_year": 2100}}`

Free editing sends the same shapes:

- typed measurements become a list;
- a typed geography becomes `{label: text, geography_terms: [text], countries: []}`;
- a typed period is two years.

When the change makes the brief invalid, the server returns a readable 422, and the screen shows
it next to the detail. An example is choosing data while no measurement is set.

Applying a choice keeps the plan and the strategy consistent. Validation stays in Python, not in
JavaScript.

## Steering and clarification

- **Steering:** `POST /runs/interpret` accepts an optional `steer`, with `{option, direction}`
  where direction is one of `narrower`, `broader`, `more_data` or `more_literature`. It produces
  a new set of options, built from the chosen option. This is one model call.
- **Clarification:** `POST /runs/interpret` accepts an optional `clarification` (the answer the
  researcher clicked or typed). The model receives the original question together with that
  answer, and `original_question` stays unchanged.

## Projections in the data route

- `validate_strategy` accepts `end_year` up to 2100. A `start_year` later than the current year
  is still rejected.
- The strategy prompt changes in two ways:
  - Measurements are observed or modelled base variables. For questions about the future,
    projected variables are allowed, named with their scenario family (for example "projected
    glacier runoff (SSP scenarios)").
  - When data could answer part of a literature question, the model offers that data version as
    an option instead of leaving measurements empty.
- The meaning review instruction adds one sentence: a projected series must be documented as a
  model projection with a named scenario. It is never accepted as an observation.

## Screen ("Before we search")

1. **Versions of your question:**
   - 2–4 cards, the closest one first with the label "Closest to your question";
   - each card shows its title, summary and a route chip;
   - selecting a card highlights it.
2. **Details of the chosen version**, one row per detail:
   - Route, Measurements, Geography, Period;
   - each row shows its current value as text, and its alternatives as chips;
   - the last chip is "Edit…", which opens a small inline field;
   - clicking a chip applies it through `adjust`, and the row updates.
3. **Steering**: a quiet row with "Narrower", "Broader", "More data" and "More literature",
   each producing new cards.
4. **Start research**: the existing approve button, with the existing review depth and model
   choice.

For a clarification, the open question is shown with its answers as chips, plus "Something
else…". Clicking an answer re-interprets the question.

The data options are never disabled. When the route needs measurements and none is set, the
Measurements row is marked as required, and Start research waits until a measurement is chosen
or typed.

Visual rules follow the results screen:

- one column, aligned with the page heading;
- UU yellow for the selected card and the selected chips;
- no internal field names.

## Error handling

- A model failure falls back to today's behaviour: the deterministic brief as the only card, with
  the reason shown.
- `adjust` never changes a brief silently. It returns either a valid brief or a 422 with the reason.
- An older client that sends no `steer`, `clarification` or `adjust` works as before.

## Testing

- **Unit tests**, with scripted model responses:
  - options are returned and validated, and invalid options are dropped;
  - the closest option comes first;
  - clarification options are returned.
  - `adjust`:
    - each detail applies consistently to the plan and the strategy;
    - an invalid change gives a 422 with a reason;
    - free text is accepted.
  - steering and clarification inputs reach the model prompt.
  - `validate_strategy` accepts 2100 as `end_year` and rejects a future `start_year`.
- **API tests** for `interpret` with `steer` or `clarification`, and for `adjust`.
- **A browser test** using a scripted interpretation:
  - cards, choosing a card, a chip change, "Edit…", a steering button, a clarification chip;
  - starting a run sends the adjusted brief;
  - the data options are not disabled.
- Finally, the Himalaya question in the local app with Codex. It should offer a data or "both"
  option with projected glacier measurements to 2100. Whether the data route then finds such a
  dataset is reported as an observation; the connectors target statistics offices, so it depends
  on the web path.

## Out of scope

- New connectors for climate model output (for example ISIMIP or glacier model archives).
- Changing how a run executes after it starts.
