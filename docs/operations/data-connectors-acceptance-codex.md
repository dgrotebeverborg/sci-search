# Data connectors acceptance run

Run: 2026-10-14T07:37+00:00. Provider: codex.

| Question | Succeeded | Sources | Missing countries | Connector gaps |
|---|---|---|---|---|
| Life expectancy for men and women by European country | yes | Statistics Netherlands (CBS) | DEU, GRC | genesis.destatis.de |
| Renewable electricity share in NL, DE and DK | yes | eurostat | - | - |
| Burned area in Spain, Portugal and Greece | yes | European Commission Joint Research Centre | - | geocatalogo.icnf.pt |
| Annual mean CO2 at Mauna Loa | no | - | - | - |
| Electricity storage in the Netherlands | no | - | - | - |
| Rhine discharge at Lobith | no | - | - | - |
| Coral cover on the Great Barrier Reef | no | - | - | - |

This run added the dataset-title rule to the meaning review, a national geography line for CBS
tables without a region dimension, and the missing-countries check. Codex reached its usage limit
during the run: storage, Rhine discharge and coral cover failed on `CodexRequestError` alone,
and some web sources for CO₂, burned area and life expectancy were not reviewed. Those results
measure nothing about the changes.

- Renewable share succeeded through a connector for the first time: Eurostat `sdg_07_40`, code
  `REN_ELC` in percent, for all three countries. Earlier runs rejected `REN_ELC` for lacking a
  numerator and denominator definition.
- Life expectancy succeeded again only for the Netherlands (CBS 37360ned), and the report now
  shows Germany and Greece as missing. `demo_mlexpec` ("by age and sex") was rejected again on
  age Y_LT1, as expected; `tps00205` was not tried in this run.
- CBS battery storage was not reached, so the geography line is untested live.

## Previous run, after the re-selection prompt change

Run: 2026-10-13T13:27+00:00. Provider: codex.

| Question | Succeeded | Sources | Connector gaps |
|---|---|---|---|
| Life expectancy for men and women by European country | yes | Statistics Netherlands (CBS) | - |
| Renewable electricity share in NL, DE and DK | no | - | - |
| Burned area in Spain, Portugal and Greece | yes | European Commission Joint Research Centre, EFFIS | - |
| Annual mean CO2 at Mauna Loa | no | - | - |
| Electricity storage in the Netherlands | no | - | - |
| Rhine discharge at Lobith | no | - | rijkswaterstaatdata.nl, waterinfo.rws.nl, ddapi20-waterwebservices.rijkswaterstaat.nl |
| Coral cover on the Great Barrier Reef | no | - | apps.aims.gov.au |

This run told the re-selection that missing years or countries are no reason to keep the
rejected codes. Four questions passed: life expectancy, burned area, and the two connector-gap
questions (Rhine, now also coral cover with apps.aims.gov.au). Re-selection still accepted
nothing. Of nine re-selections, eight repeated the codes and one changed them and was
rejected again.

- Most repeats had no better code to choose. Our World in Data allows one indicator per
  selection, so a female-only or male-only life expectancy chart cannot add the other sex. The
  burned-area charts hold only land-cover components, and the re-selection moved from forest to
  croplands. Eurostat `nrg_ind_ured` publishes GWh, not a share.
- Eurostat `demo_mlexpec` and `tps00205` were rejected again because no source text says age
  Y_LT1 is life expectancy at birth.
- Life expectancy passed through the web path on CBS 37360ned, which covers the Netherlands only
  (2000–2024, men and women). Germany and Greece are missing, but the test counts any analysis.
- CBS 85929NED (battery storage) was rejected because the passages do not state the geographic
  coverage, although CBS publishes Dutch statistics only.
- Burned area passed through EFFIS on the web path, as in the first run.

## Previous run, with re-selection

Run: 2026-10-13T11:36+00:00. Provider: codex.

| Question | Succeeded | Sources | Connector gaps |
|---|---|---|---|
| Life expectancy for men and women by European country | no | - | data-explorer.oecd.org |
| Renewable electricity share in NL, DE and DK | no | - | - |
| Burned area in Spain, Portugal and Greece | yes | Our World in Data; source: Global Wildfire Information System | gwis.jrc.ec.europa.eu |
| Annual mean CO2 at Mauna Loa | no | - | - |
| Electricity storage in the Netherlands | no | - | - |
| Rhine discharge at Lobith | no | - | rijkswaterstaatdata.nl, grdc.bafg.de, portal.grdc.bafg.de |
| Coral cover on the Great Barrier Reef | no | - | - |

This run added one re-selection after a meaning rejection. Every re-selection ended with
"no other codes": the model repeated the rejected codes, including hydropower and wind share for
the renewable share. Most rejections also contained a time complaint that no other code could
fix. Three of those complaints came from defects in the review's evidence, since fixed: the
selection document's "Years published" listed only the years inside the requested period; the
table summary included rows outside that period; and the proposal showed only the first 8 years
of each series, so the reviewer saw series ending in 2012. Burned area succeeded through the
web path on an Our World in Data file. The connector datasets were rejected for selecting one
land cover only, or on the period defects.

## Previous run, before re-selection

Run: 2026-10-13T07:42+00:00. Provider: codex.

| Question | Succeeded | Sources | Connector gaps |
|---|---|---|---|
| Life expectancy for men and women by European country | no | - | - |
| Renewable electricity share in NL, DE and DK | no | - | - |
| Burned area in Spain, Portugal and Greece | yes | European Commission Joint Research Centre, European Forest Fire Information System | - |
| Annual mean CO2 at Mauna Loa | no | - | - |
| Electricity storage in the Netherlands | no | - | - |
| Rhine discharge at Lobith | no | - | rijkswaterstaatdata.nl, waterinfo.rws.nl, ddapi20-waterwebservices.rijkswaterstaat.nl, rijkswaterstaat.github.io |
| Coral cover on the Great Barrier Reef | no | - | - |

This run used Codex (`gpt-6-sol`, with web search) after the meaning review started receiving
plain-text connector metadata and a selection document. Quotes no longer fail: every rejection
is on substance.

- Several rejections are correct. The selected series was forest-only or cropland-only burned
  area, hydropower share instead of renewable share, or renewable production in GWh instead of
  a share.
- Eurostat `demo_mlexpec` passed unit, geography and time, but failed definition: no source text
  states that age class Y_LT1 ("Less than 1 year") is life expectancy at birth.
- A recurring false rejection comes from the review's `table_sample`, which holds only the first
  12 table rows. The reviewer read it as the whole series. It reported data "only for 2000–2007"
  and said the endpoint changes contradicted the values it saw, for example for CBS 37979ned.
- Rhine discharge recorded its connector gaps (Rijkswaterstaat) and burned area succeeded through
  EFFIS on the web path. Life expectancy, renewable share and storage still did not succeed.
