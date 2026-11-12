"""Non-geographic category values must never acquire ISO country aliases."""

import pytest

from sci_search.data_research.coverage import evaluate


@pytest.mark.parametrize(
    "requested,published,complete",
    [("No", "No", True), ("in", "in", True), ("No", "Norway", False)],
)
def test_country_codes_do_not_reinterpret_other_breakdown_values(requested, published, complete):
    scope = {
        "measurements": ["population"],
        "countries": ["NLD"],
        "start_year": 2020,
        "end_year": 2020,
        "requirements": [
            {
                "measurement": "population",
                "breakdowns": [{"dimension": "smoker", "values": [requested]}],
            }
        ],
    }
    analyses = [
        {
            "series": [
                {
                    "label": "population",
                    "entity": "Netherlands",
                    "unit": "persons",
                    "identity": {"geography": "Netherlands", "dimensions": {"smoker": published}},
                    "annual": [{"year": 2020, "value": 100}],
                }
            ]
        }
    ]
    assert (evaluate(scope, analyses)["cells"][0]["status"] == "complete") is complete


def test_explicit_country_breakdown_keeps_country_aliases():
    scope = {
        "measurements": ["population"],
        "countries": ["NLD"],
        "start_year": 2020,
        "end_year": 2020,
        "requirements": [
            {
                "measurement": "population",
                "breakdowns": [{"dimension": "country of birth", "values": ["DEU"]}],
            }
        ],
    }
    analyses = [
        {
            "series": [
                {
                    "label": "population",
                    "entity": "Netherlands",
                    "unit": "persons",
                    "identity": {
                        "geography": "Netherlands",
                        "dimensions": {"country of birth": "Germany"},
                    },
                    "annual": [{"year": 2020, "value": 100}],
                }
            ]
        }
    ]
    assert evaluate(scope, analyses)["cells"][0]["status"] == "complete"
