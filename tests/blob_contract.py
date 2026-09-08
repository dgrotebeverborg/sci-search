"""Behavioral assertions shared by every BlobStore implementation."""

from io import BytesIO

import pytest

from sci_search.application.blobs import BlobHashMismatch, BlobStore, BlobTooLarge


def assert_round_trip_and_deduplication(store: BlobStore) -> None:
    first = store.put(
        BytesIO(b"scientific paper"),
        maximum_bytes=1024,
        content_type="application/pdf",
    )
    second = store.put(
        BytesIO(b"scientific paper"),
        maximum_bytes=1024,
        content_type="application/pdf",
    )
    assert first == second
    assert store.stat(first.key) == first
    with store.open(first.key) as stream:
        assert stream.read() == b"scientific paper"


def assert_bounded_and_hash_verified_put(store: BlobStore) -> None:
    with pytest.raises(BlobTooLarge):
        store.put(BytesIO(b"too large"), maximum_bytes=3)
    with pytest.raises(BlobHashMismatch):
        store.put(BytesIO(b"paper"), maximum_bytes=100, expected_sha256="0" * 64)
