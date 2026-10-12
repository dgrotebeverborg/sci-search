# tests/test_connector_base.py
from datetime import date

import pytest

from sci_search.data_research.connectors import base


def description():
    return base.DatasetDescription(
        candidate=base.DatasetCandidate("eurostat", "demo_mlexpec", "Life expectancy", "annual"),
        dimensions=(
            base.Dimension("sex", "Sex", {"F": "Females", "M": "Males", "T": "Total"}),
            base.Dimension("geo", "Country", {"NL": "Netherlands", "DE": "Germany"}),
            base.Dimension("unit", "Unit", {"YR": "Year"}),
        ),
        years=(2000, 2024),
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        definitions="Life expectancy at birth",
        publisher="Eurostat",
    )


def selection(**updates):
    value = {
        "filters": {"sex": ["F", "M"], "geo": ["NL", "DE"], "unit": ["YR"]},
        "series_dimensions": ["sex", "geo"],
        "reason": "Requested",
    }
    return value | updates


def test_valid_selection_is_normalised():
    assert base.validate_selection(description(), selection())["filters"]["geo"] == ["NL", "DE"]


def test_unobserved_code_is_a_repairable_selection_error():
    with pytest.raises(base.SelectionError) as info:
        base.validate_selection(
            description(), selection(filters={"sex": ["X"], "geo": ["NL"], "unit": ["YR"]})
        )
    assert info.value.facts["valid_codes"]["sex"] == ["F", "M", "T"]


def test_every_dimension_needs_a_filter_and_fixed_dimensions_one_code():
    with pytest.raises(base.SelectionError, match="every dimension"):
        base.validate_selection(description(), selection(filters={"sex": ["F"], "geo": ["NL"]}))
    with pytest.raises(base.SelectionError, match="one code"):
        base.validate_selection(description(), selection(series_dimensions=["geo"]))


def test_entity_limit():
    many = base.DatasetDescription(
        **{
            **description().__dict__,
            "dimensions": (base.Dimension("geo", "Country", {f"C{i}": str(i) for i in range(61)}),),
        }
    )
    with pytest.raises(base.SelectionError, match="60"):
        base.validate_selection(
            many,
            {
                "filters": {"geo": [f"C{i}" for i in range(61)]},
                "series_dimensions": ["geo"],
                "reason": "",
            },
        )


def test_series_mapping_requires_one_unit():
    table = b"Year,Series,Value,Unit,Status\n2000,a,1,YR,\n2001,a,2,YR,\n"
    mapping = base.series_mapping(table, "life expectancy")
    assert mapping["entities"] == ["a"] and mapping["unit"] == "YR"
    mixed = b"Year,Series,Value,Unit,Status\n2000,a,1,YR,\n2000,b,2,PC,\n"
    with pytest.raises(base.SelectionError, match="Select one unit"):
        base.series_mapping(mixed, "x")


def test_catalogue_cache_is_daily_and_refetches_corrupt_files(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return b"<catalogue/>", "application/xml", url

    body, digest = base.catalogue(
        "eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12)
    )
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12))
    assert len(calls) == 1 and body == b"<catalogue/>" and len(digest) == 64
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 13))
    assert len(calls) == 2
    (tmp_path / "eurostat-2026-10-13.bin").write_bytes(b"")
    (tmp_path / "eurostat-2026-10-13.sha256").write_text("0" * 64)
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 13))
    assert len(calls) == 3


def test_annual_codes_and_scoring():
    assert [base.annual(c) for c in ("2024", "2024 ", "2024JJ00", "2024M01", "2024Q1")] == [
        2024,
        2024,
        2024,
        None,
        None,
    ]
    assert base.score("Life expectancy by age and sex", ["life expectancy", "sex"]) > base.score(
        "Population", ["life expectancy"]
    )


def test_connectors_can_be_disabled(monkeypatch):
    from sci_search.data_research import connectors

    monkeypatch.delenv("SCI_SEARCH_DATA_CONNECTORS", raising=False)
    assert connectors.enabled()
    for value in ("0", "false", "no"):
        monkeypatch.setenv("SCI_SEARCH_DATA_CONNECTORS", value)
        assert not connectors.enabled()
