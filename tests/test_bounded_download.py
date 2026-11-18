import pytest

from sci_search.data_research import retrieval


class _Slow:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, size):
        return self.chunks.pop(0) if self.chunks else b""


def test_download_stops_at_overall_deadline(monkeypatch):
    clock = iter(range(0, 1000, 100))
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="exceeded 180 seconds"):
        retrieval._read_bounded(_Slow([b"a"] * 10), limit=1000)


def test_download_size_limit_and_complete_read():
    with pytest.raises(ValueError, match="acquisition limit"):
        retrieval._read_bounded(_Slow([b"abcdef"]), limit=5)
    assert retrieval._read_bounded(_Slow([b"ab", b"cd"]), limit=10) == b"abcd"


def test_google_drive_viewer_links_resolve_to_file_export():
    from sci_search.data_research.retrieval import direct_download_url

    assert (
        direct_download_url(
            "https://drive.google.com/file/d/0B_QoCd-1jkVXRGdUMTlkYTNiNGc/edit?usp=sharing&amp;usp=x"
        )
        == "https://drive.google.com/uc?export=download&id=0B_QoCd-1jkVXRGdUMTlkYTNiNGc"
    )
    assert direct_download_url("https://example.org/file/d/abcdefghijk/view") == (
        "https://example.org/file/d/abcdefghijk/view"
    )
