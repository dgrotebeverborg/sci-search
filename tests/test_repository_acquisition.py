from dataclasses import replace

import pytest

from sci_search.fulltext_acquisition import acquire_full_text
from sci_search.scholarly_providers import _openalex_candidate


def source():
    return _openalex_candidate(
        {
            "id": "https://openalex.org/W4409664854",
            "display_name": "Hydrogen production costs",
            "doi": "https://doi.org/10.1016/j.apenergy.2025.125947",
            "open_access": {"is_oa": True},
            "locations": [
                {
                    "is_oa": True,
                    "source": {"type": "repository"},
                    "landing_page_url": "https://repository.example/item/123",
                },
                {
                    "is_oa": False,
                    "source": {"type": "repository"},
                    "landing_page_url": "https://closed.example/item/123",
                },
                {
                    "is_oa": True,
                    "source": {"type": "journal"},
                    "landing_page_url": "https://publisher.example/item/123",
                },
            ],
        },
        "q1",
    )


def test_openalex_preserves_only_explicitly_open_repository_locations():
    assert source().oa_landing_urls == ("https://repository.example/item/123",)


@pytest.mark.parametrize(
    "html",
    [
        '<meta name="citation_pdf_url" content="/paper.pdf">',
        '<a href="/paper.pdf">Download full text</a>',
    ],
)
def test_repository_pdf_acquired_without_openalex_content(tmp_path, html):
    responses = {
        "https://repository.example/item/123": (html.encode(), "text/html"),
        "https://repository.example/paper.pdf": (b"%PDF-1.7 test", "application/pdf"),
    }
    result = acquire_full_text(
        source(), tmp_path, openalex_api_key="", fetch_bytes=lambda url, params: responses[url]
    )
    assert result.status == "acquired"
    assert result.source == "repository_oa_pdf"
    assert (tmp_path / result.relative_path).read_bytes() == b"%PDF-1.7 test"
    assert result.source_url == "https://repository.example/paper.pdf"


@pytest.mark.parametrize(
    "html",
    [
        "<html>No download available</html>",
        '<meta name="citation_pdf_url" content="http://127.0.0.1/private.pdf">',
        '<meta name="citation_pdf_url" content="https://user:secret@repository.example/paper.pdf">',
        '<meta name="citation_pdf_url" content="file:///etc/passwd">',
        '<meta name="citation_pdf_url" content="https://unrelated.example/paper.pdf">',
        '<a href="/one.pdf">PDF</a><a href="/two.pdf">PDF</a>',
        '<a href="/supplement.pdf">Supplementary material</a>',
        '<meta name="citation_doi" content="10.1234/other"><meta name="citation_pdf_url" content="/paper.pdf">',
        '<meta name="citation_title" content="Unrelated study"><meta name="citation_pdf_url" content="/paper.pdf">',
    ],
)
def test_repository_rejects_missing_ambiguous_unrelated_or_unsafe_pdf(tmp_path, html):
    def fetch(url, params):
        assert url == "https://repository.example/item/123"
        return html.encode(), "text/html"

    result = acquire_full_text(source(), tmp_path, openalex_api_key="", fetch_bytes=fetch)
    assert result.status == "failed"
    assert not list((tmp_path / "papers").iterdir())


def test_non_oa_candidate_cannot_use_repository_landing(tmp_path):
    def fetch(url, params):
        pytest.fail("Closed-access candidate must not be fetched")

    result = acquire_full_text(
        replace(source(), is_open_access=False), tmp_path, openalex_api_key="", fetch_bytes=fetch
    )
    assert result.status == "failed"


def test_supplementary_link_text_is_not_article(tmp_path):
    result = acquire_full_text(
        source(),
        tmp_path,
        openalex_api_key="",
        fetch_bytes=lambda url, params: (
            b'<a href="/attachment.pdf">Supplementary material</a>',
            "text/html",
        ),
    )
    assert result.status == "failed"
    assert "no unambiguous article PDF" in result.error


def test_repository_attempts_are_bounded(tmp_path):
    count = 0

    def fetch(url, params):
        nonlocal count
        count += 1
        return b"<html>No PDF</html>", "text/html"

    candidate = replace(
        source(), oa_landing_urls=tuple(f"https://repository.example/item/{i}" for i in range(10))
    )
    outcome = acquire_full_text(candidate, tmp_path, openalex_api_key="", fetch_bytes=fetch)
    assert outcome.status == "failed"
    assert count == 3


def test_existing_direct_pdf_remains_preferred(tmp_path):
    def fetch(url, params):
        assert url == "https://publisher.example/direct.pdf"
        return b"%PDF-1.7 original", "application/pdf"

    outcome = acquire_full_text(
        replace(source(), full_text_url="https://publisher.example/direct.pdf"),
        tmp_path,
        openalex_api_key="",
        fetch_bytes=fetch,
    )
    assert outcome.source == "publisher_oa_pdf"


def test_private_dns_target_rejected(monkeypatch):
    from sci_search.fulltext_acquisition import _validate_repository_url

    monkeypatch.setattr("socket.getaddrinfo", lambda *args: [(2, 1, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        _validate_repository_url("https://repository.example/paper.pdf", resolve=True)


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_dspace_shell_resolves_only_matching_article(tmp_path, wrong_identity):
    import json

    base = "https://repository.example"
    responses = {
        base + "/handle/1874/123": b"<html><title>DSpace</title><ds-app></ds-app></html>",
        base + "/server/api/pid/find?id=1874%2F123": json.dumps(
            {
                "metadata": {
                    "dc.identifier.doi": [
                        {
                            "value": "10.1234/wrong"
                            if wrong_identity
                            else "https://doi.org/10.1016/j.apenergy.2025.125947"
                        }
                    ],
                    "dc.title": [{"value": "Hydrogen production costs"}],
                },
                "_links": {"bundles": {"href": base + "/bundles"}},
            }
        ).encode(),
        base + "/bundles": json.dumps(
            {
                "_embedded": {
                    "bundles": [
                        {
                            "name": "ORIGINAL",
                            "_links": {"bitstreams": {"href": base + "/bitstreams"}},
                        }
                    ]
                }
            }
        ).encode(),
        base + "/bitstreams": json.dumps(
            {
                "_embedded": {
                    "bitstreams": [
                        {"name": "article.pdf", "_links": {"content": {"href": base + "/content"}}}
                    ]
                }
            }
        ).encode(),
        base + "/content": b"%PDF-1.7 article",
    }

    def fetch(url, params):
        if wrong_identity:
            assert url not in {base + "/bundles", base + "/bitstreams", base + "/content"}
        return responses[url], "application/octet-stream"

    result = acquire_full_text(
        replace(source(), oa_landing_urls=(base + "/handle/1874/123",)),
        tmp_path,
        openalex_api_key="",
        fetch_bytes=fetch,
    )
    assert result.status == ("failed" if wrong_identity else "acquired")
    if not wrong_identity:
        assert result.source_url == base + "/content"


def test_malformed_dspace_metadata_fails_acquisition_cleanly(tmp_path):
    candidate = replace(source(), oa_landing_urls=("https://repository.example/handle/1874/123",))

    def fetch(url, params):
        if "/handle/" in url:
            return b"<ds-app></ds-app>", "text/html"
        return b'{"metadata": null}', "application/json"

    outcome = acquire_full_text(candidate, tmp_path, openalex_api_key="", fetch_bytes=fetch)
    assert outcome.status == "failed"
