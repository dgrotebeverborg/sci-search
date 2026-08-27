"""Bounded content-addressed storage on a local filesystem."""

from __future__ import annotations

import json
import os
import re
import tempfile
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import BinaryIO

from sci_search.application.blobs import (
    BlobHashMismatch,
    BlobNotFound,
    BlobRef,
    BlobTooLarge,
)

_KEY_PATTERN = re.compile(r"objects/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})")
_EXPECTED_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_CHUNK_SIZE = 1024 * 1024


class FilesystemBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._objects = self._root / "objects"
        self._temporary = self._root / ".tmp"
        self._objects.mkdir(parents=True, exist_ok=True)
        self._temporary.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        stream: BinaryIO,
        maximum_bytes: int,
        *,
        content_type: str = "application/octet-stream",
        expected_sha256: str | None = None,
    ) -> BlobRef:
        if maximum_bytes < 0:
            raise ValueError("maximum bytes must not be negative")
        expected = expected_sha256.lower() if expected_sha256 is not None else None
        if expected is not None and not _EXPECTED_HASH_PATTERN.fullmatch(expected):
            raise ValueError("expected SHA-256 must contain 64 hexadecimal characters")

        digest = sha256()
        size = 0
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self._temporary, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := stream.read(_CHUNK_SIZE):
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise BlobTooLarge(f"blob exceeds maximum of {maximum_bytes} bytes")
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())

            actual = digest.hexdigest()
            if expected is not None and not compare_digest(actual, expected):
                raise BlobHashMismatch("blob SHA-256 does not match expected value")

            key = self._key(actual)
            destination = self._path(key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                temporary_path.unlink()
            else:
                os.replace(temporary_path, destination)
            temporary_path = None
            self._write_metadata(destination, content_type)
            return BlobRef(actual, size, self._read_content_type(destination), key)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        try:
            return path.open("rb")
        except FileNotFoundError as error:
            raise BlobNotFound("blob not found") from error

    def stat(self, key: str) -> BlobRef:
        path = self._path(key)
        try:
            size = path.stat().st_size
        except FileNotFoundError as error:
            raise BlobNotFound("blob not found") from error
        digest = _KEY_PATTERN.fullmatch(key).group(3)  # type: ignore[union-attr]
        return BlobRef(digest, size, self._read_content_type(path), key)

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        self._metadata_path(path).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        match = _KEY_PATTERN.fullmatch(key)
        if (
            match is None
            or match.group(1) != match.group(3)[:2]
            or match.group(2) != match.group(3)[2:4]
        ):
            raise BlobNotFound("blob not found")
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise BlobNotFound("blob not found")
        return path

    @staticmethod
    def _key(digest: str) -> str:
        return f"objects/{digest[:2]}/{digest[2:4]}/{digest}"

    @staticmethod
    def _metadata_path(path: Path) -> Path:
        return path.with_name(f"{path.name}.metadata.json")

    def _write_metadata(self, path: Path, content_type: str) -> None:
        metadata_path = self._metadata_path(path)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=metadata_path.parent,
                encoding="utf-8",
                delete=False,
            ) as metadata:
                temporary_path = Path(metadata.name)
                json.dump({"content_type": content_type}, metadata)
                metadata.flush()
                os.fsync(metadata.fileno())
            try:
                os.link(temporary_path, metadata_path)
            except FileExistsError:
                pass
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _read_content_type(self, path: Path) -> str:
        try:
            with self._metadata_path(path).open(encoding="utf-8") as metadata:
                value = json.load(metadata).get("content_type")
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            value = None
        return str(value) if value else "application/octet-stream"
