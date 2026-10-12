# Data connectors acceptance run

The brief expected life expectancy, renewable electricity share and electricity storage to
succeed through connectors with Mistral; none did in the three runs below. The main remaining
cause is the meaning reviewer, which rejects on substance (for example Eurostat's age code
Y_LT1 read as not "at birth") and on quotes that do not match the source text exactly. These runs
assert gaps for the web-dependent questions; the test now skips those under Mistral.

Run: 2026-10-12T13:42+00:00. Provider: mistral.

| Question | Succeeded | Sources | Connector gaps |
|---|---|---|---|
| Life expectancy for men and women by European country | no | - | - |
| Renewable electricity share in NL, DE and DK | no | - | - |
| Burned area in Spain, Portugal and Greece | no | - | - |
| Annual mean CO2 at Mauna Loa | no | - | - |
| Electricity storage in the Netherlands | no | - | - |
| Rhine discharge at Lobith | no | - | - |
| Coral cover on the Great Barrier Reef | no | - | - |

After the meaning review was limited to one review per measurement, no review failed on its
structure any more. Every connector attempt that reached the review was rejected on substance:
definitions the reviewer judged ambiguous (for example Eurostat's age code Y_LT1, "Less than 1
year", for life expectancy at birth; battery power versus storage capacity; the denominator of a
renewable share), or quotes that did not match the source text exactly. Without web search
(Mistral) no connector gap can be recorded.

## Second run, before the meaning-review fix

Run: 2026-10-12T13:32+00:00. Provider: mistral.

| Question | Succeeded | Sources | Connector gaps |
|---|---|---|---|
| Life expectancy for men and women by European country | no | - | - |
| Renewable electricity share in NL, DE and DK | no | - | - |
| Burned area in Spain, Portugal and Greece | no | - | - |
| Annual mean CO2 at Mauna Loa | no | - | - |
| Electricity storage in the Netherlands | no | - | - |
| Rhine discharge at Lobith | no | - | - |
| Coral cover on the Great Barrier Reef | no | - | - |

Without web search (Mistral), connector gaps cannot be recorded, so Rhine, coral, burned area
and CO2 cannot pass this run. Most connector attempts now reach the meaning review and stop there:
the reviewer returned one review per country or sex instead of one per measurement ("Unexpected
or duplicate measurement review"), or judged the definition ambiguous.

## First run, before the fixes of 2026-10-12

Run: 2026-10-12T13:06+00:00. Provider: mistral.

| Question | Succeeded | Sources | Connector gaps |
|---|---|---|---|
| Life expectancy for men and women by European country | no | - | - |
| Renewable electricity share in NL, DE and DK | no | - | - |
| Burned area in Spain, Portugal and Greece | no | - | - |
| Annual mean CO2 at Mauna Loa | no | - | - |
| Electricity storage in the Netherlands | no | - | - |
| Rhine discharge at Lobith | no | - | - |
| Coral cover on the Great Barrier Reef | no | - | - |

The first run failed on two connector bugs, since fixed. The meaning-review prompt carried every
source row's provenance (1.4 MB for a CBS package), so Mistral rejected it with HTTP 400 for
exceeding its context. CBS selections with more than one series dimension were rejected after the
download instead of being returned to the model for repair. Search terms also came back in Dutch
only, and the Eurostat candidates were unrelated.
