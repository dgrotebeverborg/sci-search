# Wildfire data-research pilot

Approved direction: use the user's European wildfire question to build a first quantitative research route alongside the existing literature route.

Scope: a curated EFFIS country-reporting workbook adapter, annual reported fire counts and burned area in km², fixed-country comparisons, visible missing years/countries, source snapshot and reproducible exports. The interpretation screen proposes data analysis and lets the user choose the country scope or keep literature review. This is not an arbitrary-dataset agent or an automatic causal explanation.

Source: EFFIS country totals accompanying the 2024 annual report, historical workbook 1980–2024. National reported forest-fire counts must not be merged with satellite-mapped fire-event counts. Default requested years 2001 through the last completed calendar year; absent years remain missing.

Implementation sequence:
1. Validate and normalize the official workbook with source/cell provenance.
2. Calculate per-year available totals and a fixed complete-country panel over the available requested years. Never treat missing values as zero; separate counts and area; no causal/statistical significance claims.
3. Add a reviewed data route to question interpretation and the existing persisted run lifecycle.
4. Render charts, annual values, coverage, limitations and downloadable source/calculation package.
5. Test numerical invariants, missingness, routing, saved results, exports, browser interactions, and one live official-source run.

Acceptance: the original wildfire question produces a traceable numerical result, honestly identifies limits on answering for all Europe and all century years, and leaves the literature workflow available.
