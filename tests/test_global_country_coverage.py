"""Global country identities must neither lose observations nor merge neighbours."""

import pytest

from sci_search.data_research.coverage import evaluate


def covered(countries, labels):
    scope = {
        "measurements": ["indicator"],
        "countries": countries,
        "start_year": 2020,
        "end_year": 2020,
    }
    analysis = {
        "series": [
            {
                "label": "indicator",
                "entity": label,
                "unit": "persons",
                "annual": [{"year": 2020, "value": 1}],
            }
            for label in labels
        ]
    }
    return evaluate(scope, [analysis])


@pytest.mark.parametrize(
    "countries,labels",
    [
        (["USA", "CHN", "IND"], ["United States", "China", "India"]),
        (["KEN", "NGA", "ETH"], ["Kenya", "Nigeria", "Ethiopia"]),
        (["BRA", "AUS", "JPN", "FJI"], ["Brazil", "Australia", "Japan", "Fiji"]),
        (["US", "CN", "IN"], ["USA", "CHN", "IND"]),
        (["United States", "China", "India"], ["US", "CN", "IN"]),
        (["NLD", "DEU"], ["NL", "DE"]),
        (["RUS", "MDA", "VAT"], ["Russia", "Moldova", "Vatican City"]),
    ],
)
def test_global_country_names_and_codes_cover_the_same_entities(countries, labels):
    assert covered(countries, labels)["gaps"] == []


@pytest.mark.parametrize(
    "country,label",
    [
        ("COD", "Democratic Republic of the Congo"),
        ("COG", "Republic of the Congo"),
        ("KOR", "South Korea"),
        ("PRK", "North Korea"),
        ("PNG", "Papua New Guinea"),
        ("GNQ", "Equatorial Guinea"),
        ("SSD", "South Sudan"),
    ],
)
def test_qualified_country_name_is_not_a_combined_country_series(country, label):
    assert covered([country], [label])["gaps"] == []


@pytest.mark.parametrize(
    "country,label",
    [
        ("COD", "Congo"),
        ("COG", "Congo"),
        ("COG", "Democratic Republic of the Congo"),
        ("CHN", "China and India combined"),
        ("GIN", "Papua New Guinea"),
        ("SDN", "South Sudan"),
        ("IND", "Indiana"),
        ("NER", "Nigeria"),
    ],
)
def test_ambiguous_combined_or_substring_identities_do_not_cover_country(country, label):
    assert covered([country], [label])["gaps"]


def test_ordinary_words_are_not_iso_codes_inside_geography_labels():
    assert covered(["USA"], ["United States women in education and training"])["gaps"] == []


def test_city_parent_country_may_use_any_country_identity():
    scope = {
        "measurements": ["indicator"],
        "countries": ["FR"],
        "requirements": [{"measurement": "indicator", "entities": ["Paris"]}],
        "start_year": 2020,
        "end_year": 2020,
    }
    analysis = {
        "series": [
            {
                "label": "indicator",
                "entity": "Paris, France",
                "unit": "persons",
                "annual": [{"year": 2020, "value": 1}],
            }
        ]
    }
    assert evaluate(scope, [analysis])["gaps"] == []


@pytest.mark.parametrize(
    "territory,label,parent",
    [
        ("VIR", "US Virgin Islands", "USA"),
        ("VIR", "U.S. Virgin Islands", "USA"),
        ("VGB", "British Virgin Islands", "GBR"),
        ("UMI", "US Minor Outlying Islands", "USA"),
    ],
)
def test_territory_alias_cannot_cover_its_parent_country(territory, label, parent):
    assert covered([territory], [label])["gaps"] == []
    assert covered([parent], [label])["gaps"]
