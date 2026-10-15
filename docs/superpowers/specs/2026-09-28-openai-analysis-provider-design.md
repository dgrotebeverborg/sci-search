# OpenAI as a second analysis provider

Date: 2026-09-28. Status: implemented; analysis and question interpretation live-checked with
OpenAI gpt-4.1-mini on 2026-09-28. Full-text adjudication was not needed in the live runs;
contradiction-group quality remains unassessed because neither run produced groups.
See the [live-check record](../../operations/contradiction-groups-quality-check.md).

## Product outcome

Sci-Search can run its model-assisted steps (question interpretation, full-text adjudication, and
grounded evidence analysis) through either Mistral or OpenAI, selected by one explicit setting.
Grounding validation is identical for both providers. Every stored result records which provider
and model produced it, and cached analyses from one provider are never reused for the other.

Motivation: Mistral can become unavailable (on 2026-09-27 the account hit its monthly spending
limit, HTTP 402), which silently reduces every run to the extractive fallback.

## Decisions

- Selection is explicit: `SCI_SEARCH_ANALYSIS_PROVIDER=mistral|openai`, default `mistral`. There is
  no automatic failover. An unavailable provider produces the existing visible extractive fallback.
  A run therefore never mixes providers.
- The Mistral request stays byte-identical to today's. Mistral cannot be re-verified while its limit
  is reached, so nothing about its request changes.
- `OPENAI_API_KEY` is read only from the process environment or `sci-search/.env.local`. The
  sci-graph legacy loader continues to import only `MISTRAL_API_KEY`
  (`configuration.load_legacy_mistral_key`, pinned by `tests/test_online_discovery.py`).

## Current evidence from the repository

- All three model call sites build a chat-completions body with a strict JSON schema and call
  `analyzer.complete_json(body, headers)`: `question_interpretation._model_interpretation`,
  `study_matrix` adjudication, and `MistralAnalyzer.analyze`. Tests inject `complete_json`.
- Five places read `MISTRAL_API_KEY` or `MISTRAL_MODEL` directly: `question_interpretation.py:77`,
  `study_matrix.py:243`, `mistral_analysis.analyze_if_configured`, `research_runs.py:1381`
  (fingerprint model), and `infrastructure/research_execution._manager`. `worker_runtime.py:23`
  passes `MISTRAL_API_KEY` to workers.
- "mistral" is hard-coded as the recorded provider in `question_interpretation.py:167`,
  `study_matrix.py:304`, `mistral_analysis.py:242`, and `application/analysis.py:65`.
- OpenAI strict mode requires every property to be listed in `required`. Probed on 2026-09-28 with
  `gpt-4.1-mini`: the unmodified analysis schema is rejected (HTTP 400, missing
  `cause_explanation`). After the conversion below, all three schemas are accepted (HTTP 200),
  including `minItems`, `maxItems`, and `maxLength`. Only two properties are optional today, both in
  the analysis schema: `$defs.assertion.qualification` and `$defs.contradiction_group.cause_explanation`.

## Configuration

| Variable | Values | Default |
|---|---|---|
| `SCI_SEARCH_ANALYSIS_PROVIDER` | `mistral`, `openai` | `mistral` |
| `MISTRAL_API_KEY`, `MISTRAL_MODEL` | key, model | model `mistral-small-latest` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | key, model | model `gpt-4.1-mini` |

- The provider value is trimmed and lowercased. Any other value raises
  `ValueError("SCI_SEARCH_ANALYSIS_PROVIDER must be one of: mistral, openai")`.
- A missing key for the selected provider yields no analyzer. Each call site then takes its existing
  fallback, with the reason naming the selected provider's key variable, for example
  `"OPENAI_API_KEY is not configured; deterministic extractive analysis was used"`.
- `.env.example` and the README document the new variables. `worker_runtime.py` passes through
  `SCI_SEARCH_ANALYSIS_PROVIDER`, `OPENAI_API_KEY`, and `OPENAI_MODEL` as it does for Mistral.

## Components

New module `sci_search/model_provider.py`:

```python
@dataclass(frozen=True, slots=True)
class ProviderProfile:
    name: str                 # "mistral" | "openai"
    endpoint: str             # chat-completions URL
    default_model: str
    key_variable: str         # "MISTRAL_API_KEY" | "OPENAI_API_KEY"
    model_variable: str       # "MISTRAL_MODEL" | "OPENAI_MODEL"
    prepare: Callable[[dict[str, Any]], dict[str, Any]]

PROFILES: dict[str, ProviderProfile]   # "mistral", "openai"

def selected_profile() -> ProviderProfile: ...       # reads SCI_SEARCH_ANALYSIS_PROVIDER
def configured_analyzer() -> ModelAnalyzer | None: ... # None when the selected key is missing
def openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]: ...
```

- Mistral `prepare` returns the body unchanged.
- OpenAI `prepare` returns a deep copy of the body whose
  `response_format.json_schema.schema` is passed through `openai_strict_schema`.
- `openai_strict_schema` walks every object that has `properties`. For each property that is not
  listed in `required`, it wraps the property as `{"anyOf": [<original>, {"type": "null"}]}`, and
  then sets `required` to all property names in order. It recurses into `properties`, `items`,
  `$defs`, and `anyOf`. It never mutates its input and is idempotent.

`mistral_analysis.MistralAnalyzer` becomes `ModelAnalyzer`:

```python
class ModelAnalyzer:
    def __init__(self, api_key: str, *, provider: ProviderProfile = PROFILES["mistral"],
                 model: str | None = None, complete_json: JsonCompletion | None = None) -> None: ...
```

- `model` defaults to the `model_variable` environment value, then `provider.default_model`.
- `self.complete_json(body, headers)` always applies `provider.prepare(body)` first, then calls the
  injected transport or the HTTP transport to `provider.endpoint`. Tests that inject
  `complete_json` therefore receive the prepared body.
- `MistralAnalyzer = ModelAnalyzer` remains as an alias. The file name `mistral_analysis.py` is kept
  to avoid churn.

`application.analysis.MistralAnalysisProvider` takes `provider_name` from `analyzer.provider.name`.

## Recorded provenance

- The recorded provider becomes `analyzer.provider.name` in the analysis result, question brief, and
  adjudication record.
- Method names become `f"{provider}_structured_evidence_analysis_v1"`,
  `f"{provider}_structured_question_interpretation_v1"`, and
  `f"{provider}_quote_validated_fulltext_adjudication_v1"`. For Mistral these equal today's strings,
  so stored runs keep their meaning. The adjudication `not_needed` and `unavailable` records, which
  involve no model, keep `ADJUDICATION_METHOD`.
- `PROMPT_CONTRACT_VERSION` and `SCHEMA_VERSION` do not change: the prompt and logical schema are
  identical, and the strict-mode conversion is a transport detail identified by the provider name.
- Analysis cache fingerprint (`research_runs.py`): the model comes from the configured analyzer (or
  the selected profile's model when no analyzer is set). A `"provider"` entry is added only when the
  provider is not Mistral, so existing Mistral cache keys stay valid. Model names already separate
  the providers; the provider entry makes the separation explicit.
- `infrastructure/observability._PROVIDERS` gains `"openai"`.

## Error handling

Unchanged from Mistral: the transport retries HTTP 429 and 5xx with backoff, and any other failure
(for example 401 or 402) makes the call site fall back visibly, recording the reason. The
grounding validators accept `null` for `qualification` (treated as empty) and `cause_explanation`
(treated as absent, so the group becomes or stays `unexplained`).

## Testing

Unit tests (no network):

- `openai_strict_schema`: optional properties become nullable, every property is required, nested
  `$defs`, `items`, and `anyOf` are handled, the input is not mutated, and applying it twice gives
  the same result. Mistral `prepare` returns the body unchanged.
- `selected_profile` and `configured_analyzer`: default Mistral, `openai` selection and model
  default, `OPENAI_MODEL` override, invalid value raises, missing key returns `None`.
- Validation accepts `null` `qualification` and `null` `cause_explanation`.

Integration tests (through the injected `complete_json`):

- With the OpenAI profile, question interpretation, adjudication, and analysis each send a body
  whose schema is converted and whose `model` is the OpenAI model, and each records provider
  `openai` and the `openai_` method name.
- With the Mistral profile, the sent body equals today's body.
- The analysis fingerprint changes for OpenAI and is unchanged for Mistral.
- `load_legacy_mistral_key` still never imports `OPENAI_API_KEY` (existing test).

Manual live check (not in CI): with `SCI_SEARCH_ANALYSIS_PROVIDER=openai`, run the two questions of
`docs/operations/contradiction-groups-quality-check.md` and complete that protocol's table.

## Compatibility and rollback

No database migration. Default behavior is unchanged. Rolling back removes the setting; stored
OpenAI results remain readable because they use the same schema, with `openai` provider and method
names.
