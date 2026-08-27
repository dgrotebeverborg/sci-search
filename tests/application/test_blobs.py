from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest

from sci_search.application.blobs import BlobHashMismatch, BlobTooLarge
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore


def test_identical_bytes_deduplicate_and_round_trip(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")

    first = store.put(BytesIO(b"scientific paper"), maximum_bytes=1024)
    second = store.put(BytesIO(b"scientific paper"), maximum_bytes=1024)

    assert first == second
    assert first.size == len(b"scientific paper")
    assert first.key == f"objects/{first.sha256[:2]}/{first.sha256[2:4]}/{first.sha256}"
    assert store.stat(first.key) == first
    with store.open(first.key) as stream:
        assert stream.read() == b"scientific paper"
    assert len(list((tmp_path / "blobs" / "objects").rglob(first.sha256))) == 1


def test_oversized_stream_aborts_without_visible_partial_blob(tmp_path) -> None:
    root = tmp_path / "blobs"
    store = FilesystemBlobStore(root)

    with pytest.raises(BlobTooLarge, match="maximum"):
        store.put(BytesIO(b"too large"), maximum_bytes=3)

    assert list((root / "objects").rglob("*")) == []
    assert list((root / ".tmp").iterdir()) == []


def test_mismatched_expected_hash_aborts_without_blob(tmp_path) -> None:
    root = tmp_path / "blobs"
    store = FilesystemBlobStore(root)

    with pytest.raises(BlobHashMismatch, match="SHA-256"):
        store.put(
            BytesIO(b"paper"),
            maximum_bytes=100,
            expected_sha256="0" * 64,
        )

    assert list((root / "objects").rglob("*")) == []
    assert list((root / ".tmp").iterdir()) == []


def test_blob_key_contains_no_source_filename_or_project_identifier(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")

    reference = store.put(
        BytesIO(b"paper"),
        maximum_bytes=100,
        content_type="application/pdf",
    )

    assert "sensitive-paper.pdf" not in reference.key
    assert "private-project" not in reference.key
    assert reference.content_type == "application/pdf"


def test_concurrent_identical_puts_publish_one_final_object(tmp_path) -> None:
    root = tmp_path / "blobs"
    store = FilesystemBlobStore(root)

    with ThreadPoolExecutor(max_workers=8) as executor:
        references = list(
            executor.map(
                lambda _: store.put(BytesIO(b"same bytes"), maximum_bytes=100),
                range(24),
            )
        )

    assert len(set(references)) == 1
    reference = references[0]
    assert len(list((root / "objects").rglob(reference.sha256))) == 1
    assert list((root / ".tmp").iterdir()) == []
