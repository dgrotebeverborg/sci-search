"""Content-addressed blob storage contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


class BlobError(RuntimeError):
    pass


class BlobTooLarge(BlobError):
    pass


class BlobHashMismatch(BlobError):
    pass


class BlobNotFound(BlobError):
    pass


class BlobTransientError(BlobError):
    pass


@dataclass(frozen=True, slots=True)
class BlobRef:
    sha256: str
    size: int
    content_type: str
    key: str


class BlobStore(Protocol):
    def put(
        self,
        stream: BinaryIO,
        maximum_bytes: int,
        *,
        content_type: str = "application/octet-stream",
        expected_sha256: str | None = None,
    ) -> BlobRef: ...

    def open(self, key: str) -> BinaryIO: ...

    def stat(self, key: str) -> BlobRef: ...

    def delete(self, key: str) -> None: ...
