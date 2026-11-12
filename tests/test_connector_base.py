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
    # A non-empty body with a wrong digest is refetched.
    (tmp_path / "eurostat-2026-10-13.bin").write_bytes(b"tampered")
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 13))
    assert len(calls) == 4
    # A non-UTF-8 digest file is a cache miss, not a crash.
    (tmp_path / "eurostat-2026-10-13.sha256").write_bytes(b"\xff\xfe\x00")
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 13))
    assert len(calls) == 5


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


def test_unwritable_catalogue_cache_still_returns_the_fetched_body(tmp_path):
    (tmp_path / "eurostat-2026-10-12.bin").mkdir()

    def fetch(url):
        return b"<catalogue/>", "application/xml", url

    body, digest = base.catalogue(
        "eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12)
    )
    assert body == b"<catalogue/>" and len(digest) == 64
    assert sorted(p.name for p in tmp_path.iterdir()) == ["eurostat-2026-10-12.bin"]


def test_catalogue_cache_is_replaced_atomically(tmp_path, monkeypatch):
    def fetch(url):
        return b"<new/>", "application/xml", url

    cached = tmp_path / "eurostat-2026-10-12.bin"
    cached.write_bytes(b"<old/>")
    (tmp_path / "eurostat-2026-10-12.sha256").write_text("stale")

    def interrupted(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(base.os, "replace", interrupted)
    body, _ = base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12))
    # A failed write never leaves a partial cache file or a stray temporary file behind.
    assert body == b"<new/>" and cached.read_bytes() == b"<old/>"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "eurostat-2026-10-12.bin",
        "eurostat-2026-10-12.sha256",
    ]
    monkeypatch.undo()
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12))
    assert cached.read_bytes() == b"<new/>"
    assert len(list(tmp_path.iterdir())) == 2


def test_score_matches_whole_words_in_the_real_eurostat_catalogue():
    from pathlib import Path
    from xml.etree import ElementTree

    path = Path("tests/fixtures/data_research/connectors/eurostat/dataflows.xml")
    from sci_search.data_research.connectors import eurostat

    flows = [
        (flow.get("id", "").lower(), eurostat._name(flow))
        for flow in ElementTree.parse(path).getroot().iter()
        if flow.tag.endswith("}Dataflow")
    ]

    def ranked(terms):
        scores = [(base.score(title, terms), dataset) for dataset, title in flows]
        return [dataset for points, dataset in sorted(scores, reverse=True) if points]

    assert ranked(["life expectancy"])[0] == "demo_mlexpec"
    assert ranked(["life expectancies"])[0] == "demo_mlexpec"  # inflection by prefix
    # Fragments match nothing: "art" is only part of "part-time" and "partners" here.
    assert ranked(["art"]) == []
    assert base.score("Gross non-performing loans", ["Mauna Loa"]) == 0
    assert base.score("Life expectancy", ["", "the and"]) == 0  # empty terms and stop words
    assert base.score("Rates of employment", ["rate"]) == 0  # short tokens need the whole word


@pytest.mark.parametrize(
    "title, term",
    [
        ("Batterijopslag; capaciteit", "opslag"),
        ("Zonnestroom; vermogen en vermogensklasse", "stroom"),
        ("Windenergie op land; productie", "energie"),
        ("Broeikasgasemissies door de economie", "emissies"),
        ("Energieverbruik; sectoren", "energie"),
    ],
)
def test_dutch_compounds_match_their_parts(title, term):
    # Dutch puts the head noun last in a compound: "opslag" in "Batterijopslag".
    assert base.score(title, [term]) > 0


def test_compound_matching_needs_five_characters():
    assert base.score("Gross non-performing loans", ["loa"]) == 0  # short: whole words only
    # A term of five or more characters matches a word ending with it, even a different
    # compound such as "uitstroom" (outflow) for "stroom"; the model then judges relevance.
    assert base.score("Uitstroom uit het onderwijs", ["stroom"]) > 0


def test_a_new_catalogue_removes_that_connectors_older_days(tmp_path):
    def fetch(url):
        return b"<catalogue/>", "application/xml", url

    for name in ("eurostat-2026-10-10", "eurostat-2026-10-11", "cbs-2026-10-11"):
        (tmp_path / f"{name}.bin").write_bytes(b"old")
        (tmp_path / f"{name}.sha256").write_text("0" * 64)
    (tmp_path / "notes.txt").write_text("kept")
    base.catalogue("eurostat", "https://x/cat", fetch, tmp_path, today=date(2026, 10, 12))
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "cbs-2026-10-11.bin",
        "cbs-2026-10-11.sha256",
        "eurostat-2026-10-12.bin",
        "eurostat-2026-10-12.sha256",
        "notes.txt",
    ]


def test_selection_evidence_names_each_selected_code_under_its_dimension_label():
    text = base.selection_evidence(description(), selection())
    assert "Dataset: Life expectancy (eurostat:demo_mlexpec)" in text
    assert "Publisher: Eurostat" in text
    assert "Years with data in the requested period: 2000-2024" in text
    assert "Sex: F = Females" in text and "Sex: M = Males" in text
    assert "Country: NL = Netherlands" in text
    assert "Unit: YR = Year" in text
    assert "Total" not in text  # unselected codes are left out


def test_selection_evidence_states_a_geography_the_connector_establishes():
    from dataclasses import replace

    national = replace(description(), extra={"geography": "Netherlands (national table)"})
    assert "Geography: Netherlands (national table)" in base.selection_evidence(
        national, selection()
    )
    assert "Geography" not in base.selection_evidence(description(), selection())


def test_missing_publisher_unit_is_reported_before_arithmetic():
    with pytest.raises(base.SelectionError, match="does not declare a unit"):
        base.series_mapping(b"Year,Series,Value,Unit,Status\n2020,NL,17407585,,\n", "population")
