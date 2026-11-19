# Twenty-question validation: literature and data routes (2026-11-17 – 2026-11-19)

Twenty wide-ranging scholarly questions were run in four batches of five, first on the
literature route and then on the data route. After each batch the failures were diagnosed
and general (not question-specific) fixes were committed to `main`. All runs used the
Codex provider (`gpt-6-sol`) with the `quick` run limits.

Run outputs are kept locally (git-ignored) in `data/validation_runs/new-questions-20261117/`
(literature) and `data/validation_runs/data-20q-20261118/` (data; `<id>-b<N>.json` per batch,
`<id>-final.json` for the final rerun).

## Questions

| ID | Topic |
|---|---|
| microplastics-zooplankton | Microplastic exposure and zooplankton survival/reproduction |
| class-size | Class size and student achievement |
| mbct-relapse | Mindfulness-based cognitive therapy and depressive relapse |
| green-space-heat | Urban green space and urban heat |
| wage-gap | Gender wage gap in Europe |
| social-media-depression | Social media use and adolescent depression |
| no-till-carbon | No-till farming and soil organic carbon |
| carbon-tax | Carbon taxes and emissions |
| bilingual-dementia | Bilingualism and age of dementia onset |
| acidification-coral | Ocean acidification and coral calcification |
| printing-reformation | Printing press and the spread of the Reformation |
| remote-work-productivity | Remote work and productivity |
| neonicotinoids-bees | Neonicotinoids and wild bees |
| microfinance-poverty | Microfinance and household poverty |
| flyash-concrete | Fly ash replacement and concrete compressive strength |
| sleep-memory | Sleep deprivation and working memory |
| minimum-wage | Minimum wage and employment |
| livestock-antibiotics | Livestock antibiotic use and human antimicrobial resistance |
| perovskite-stability | Perovskite solar cell stability |
| l2-age | Age of second-language onset and ultimate proficiency |

## Literature route — final result: 13 adequate, 5 partial, 2 insufficient

| Result | Questions |
|---|---|
| Adequate (13) | mbct, green-space, social-media, no-till, bilingual, remote-work, flyash, minimum-wage, microplastics, wage-gap, acidification-coral, sleep-memory, livestock |
| Partial (5) | class-size, neonicotinoids, microfinance, perovskite, l2-age |
| Insufficient (2) | carbon-tax, printing-reformation |

Remaining failures: paywalled full texts (economics, history) and run-to-run variation in the
model's research plan.

Fixes:

- `fd40ee5` Result sentences may use their source's defined abbreviations and head-noun
  shorthand; study populations are matched once per document.
- `de20c4c` Species binomials ("Apis mellifera" / "A. mellifera") and "head of X" synonym wording.
- `b806cba` A setting-qualified subject ("X in Y") is located by its core name and abbreviation.

## Data route — final rerun: 8 adequate, 8 partial, 4 insufficient

Only one question was answered completely from datasets; seven more were adequate through the
literature fallback.

| Question | Overall | Answered by |
|---|---|---|
| mbct-relapse | adequate | data (published relapse rates, complete) |
| microplastics-zooplankton | adequate | literature fallback |
| class-size | adequate | literature fallback |
| no-till-carbon | adequate | literature fallback |
| bilingual-dementia | adequate | literature fallback |
| remote-work-productivity | adequate | literature fallback |
| neonicotinoids-bees | adequate | literature fallback |
| perovskite-stability | adequate | literature fallback |
| wage-gap | partial | data: 6 Eurostat datasets, period not fully covered |
| green-space-heat | partial | data: green-space share; land surface temperature missing |
| carbon-tax | partial | data: emissions; tax rates missing |
| sleep-memory | partial | data: one study; memory scores not extracted |
| minimum-wage | partial | data: employment only; minimum wage missing |
| livestock-antibiotics | partial | data: livestock use; human resistance missing |
| acidification-coral | partial | literature fallback |
| flyash-concrete | partial | literature fallback |
| social-media-depression | insufficient | literature fallback |
| printing-reformation | insufficient | literature fallback |
| microfinance-poverty | insufficient | literature fallback |
| l2-age | insufficient | literature fallback |

Fixes:

- `8f01f18` Regional country panels count for "Europe"/"EU" cells; bounded downloads
  (overall deadline and Content-Length precheck); an open-ended period is complete after a
  completed search for newer data; Codex web-search headroom.
- `1bd58e0` Placeholder geographies ("Unspecified", "Cities") are treated as no geography.
- `e2f550a` Annual observations accepted from year 1000 (early-modern panels); Google Drive
  viewer links resolve to the file export; literature summaries skip flattened tables,
  keyword lists and reference fragments.
- `aa75714` The numerical answer status is computed from the run's final coverage (a run with
  all cells complete could be reported as partial).

Known blockers not fixed:

- Dryad file downloads now require an API token (HTTP 401/403 without it).
- Harvard Dataverse access can answer HTTP 202 (asynchronous preparation) instead of the file.
- Experimental datasets without a calendar year (e.g. strength by % fly ash) cannot be
  represented: the data model is annual series only.
- Replication packages in Stata/ZIP form often fail extraction.
- Cross-series (between-group) differences are not a supported calculation.

## Assessment

Strengths:

- Conservative: adequacy requires at least two independent publications whose statements cover
  the subject, driver and outcome; otherwise the conclusion is withheld. No confident wrong
  answers were observed in the 40 runs.
- Open-access empirical fields (ecology, materials, medicine) work well on the literature route.
- Official statistics (Eurostat, Our World in Data, CBS) work well on the data route for levels,
  trends and country comparisons, with retained files, mappings and decisions for audit.

Weaknesses:

- Paywalled fields (economics, history) lack full texts.
- The data route rarely answers causal/association questions, which need paired measurements
  from one study.
- Results vary between runs because the model plans searches and chooses sources differently.
- Data-source selection occasionally picks poorly matching series.
- When the data route runs first it consumes time the literature fallback then lacks.

Recommended next steps, by impact:

1. Route causal/association questions to literature first; use data as context only.
2. Reduce run-to-run variance (fixed search plan, or merged repeated discovery).
3. Broaden full-text access (institutional access, NBER/SSRN/RePEc working papers).
4. Support non-annual experimental data, Dryad tokens and Dataverse polling.

## Deployment readiness (shared research-cloud server)

Present: Docker Compose stack (web, worker, PostgreSQL, Redis, MinIO, Caddy), OIDC login with a
personal workspace per user, default-deny project roles, runbooks in `docs/runbooks/`, health
endpoints and metrics.

Before opening to other users:

1. Model provider: Codex with a personal ChatGPT login is disabled in production by design.
   Configure an OpenAI or Mistral API key and rerun this twenty-question set with that provider;
   the results above do not automatically carry over. Estimate cost per question.
2. Identity provider: institutional OIDC client (e.g. SURFconext) with the callback URL.
3. Per-user limits: verify per-user quotas and concurrency caps for API cost and source rate limits.
4. Privacy and licensing: privacy statement for stored questions; check licences for sharing
   downloaded full texts between users.
5. Backups: off-host encrypted backup storage and a restore drill.
6. Verify user isolation in a production-mode start with two test users (as required by
   `docs/runbooks/DEPLOYMENT.md`).
