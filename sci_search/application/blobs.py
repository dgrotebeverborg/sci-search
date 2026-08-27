"""Content-addressed blob storage contracts."""

from __future__ import annotations

import re
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


def content_addressed_key(digest: str) -> str:
    normalized = digest.casefold()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError("SHA-256 digest must contain 64 hexadecimal characters")
    return f"objects/{normalized[:2]}/{normalized[2:4]}/{normalized}"
