import pytest

from sci_search.data_research import retrieval


def test_html_download_follows_observed_directories_to_table(tmp_path):
    from sci_search.data_research.navigation import resolve_table_download

    calls = []
    payloads = {
        "https://example.org/archive/river/": (
            b'<html><a href="annual.csv">Annual discharge m3/s</a></html>',
            "text/html",
        ),
        "https://example.org/archive/river/annual.csv": (
            b"Year,Discharge m3/s\n2000,1200\n",
            "text/csv",
        ),
    }

    def fetch(url):
        calls.append(url)
        b, t = payloads[url]
        return b, t, url

    assessment = {}
    result = resolve_table_download(
        b'<html><a href="river/">River discharge</a></html>',
        "text/html",
        "https://example.org/archive/",
        question="Annual river discharge",
        scope={},
        fetch=fetch,
        complete=lambda *args: {"link_index": 0, "reason": "Follow the observed discharge link"},
        folder=tmp_path,
        assessment=assessment,
        check_cancelled=lambda: None,
    )
    assert result[0] == b"Year,Discharge m3/s\n2000,1200\n"
    assert calls == [
        "https://example.org/archive/river/",
        "https://example.org/archive/river/annual.csv",
    ]
    assert len(assessment["download_navigation"]) == 2
    assert "Annual discharge m3/s" in result[3]
    assert (tmp_path / "navigation-1.html").is_file()
    assert (tmp_path / "navigation-2.html").is_file()


@pytest.mark.parametrize(
    "choice",
    [
        {"link_index": -1, "reason": "Interactive viewer only"},
        {"link_index": 4, "reason": "Guess"},
        {"link_index": True, "reason": "Bad type"},
    ],
)
def test_invalid_or_unavailable_link_never_fetches(tmp_path, choice):
    from sci_search.data_research.navigation import resolve_table_download

    def fetch(url):
        pytest.fail("No unobserved URL may be fetched")

    with pytest.raises(ValueError):
        resolve_table_download(
            b'<html><a href="data/">data</a></html>',
            "text/html",
            "https://example.org/",
            question="Question",
            scope={},
            fetch=fetch,
            complete=lambda *a: choice,
            folder=tmp_path,
            assessment={},
            check_cancelled=lambda: None,
        )


def test_navigation_stops_cycles_and_keeps_recovery_links(tmp_path):
    from sci_search.data_research.navigation import resolve_table_download

    assessment = {}
    with pytest.raises(ValueError, match="repeated"):
        resolve_table_download(
            b'<html><a href="#top">top</a></html>',
            "text/html",
            "https://example.org/",
            question="Question",
            scope={},
            fetch=lambda url: pytest.fail("Cycle must not be fetched"),
            complete=lambda *a: {"link_index": 0, "reason": "repeat"},
            folder=tmp_path,
            assessment=assessment,
            check_cancelled=lambda: None,
        )
    assert assessment["recovery_links"] == ["https://example.org/#top"]


def test_navigation_enforces_hop_budget(tmp_path):
    from sci_search.data_research.navigation import resolve_table_download

    calls = []

    def fetch(url):
        calls.append(url)
        return b'<html><a href="next/">next</a></html>', "text/html", url

    with pytest.raises(ValueError, match="navigation limit"):
        resolve_table_download(
            b'<html><a href="next/">next</a></html>',
            "text/html",
            "https://example.org/",
            question="Question",
            scope={},
            fetch=fetch,
            complete=lambda *a: {"link_index": 0, "reason": "nested"},
            folder=tmp_path,
            assessment={},
            check_cancelled=lambda: None,
        )
    assert len(calls) == 3


def test_xml_is_not_mistaken_for_html():
    assert not retrieval.is_html(b'<?xml version="1.0"?><root/>', "application/xml")
    assert retrieval.is_html(b" \n<!DOCTYPE HTML><html></html>", "application/octet-stream")
