"""Private S3-compatible content-addressed blob storage."""

from __future__ import annotations

import re
import tempfile
from hashlib import sha256
from hmac import compare_digest
from typing import Any, BinaryIO, Never

from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError

from sci_search.application.blobs import (
    BlobError,
    BlobHashMismatch,
    BlobNotFound,
    BlobRef,
    BlobTooLarge,
    BlobTransientError,
)

_KEY_PATTERN = re.compile(r"objects/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})")
_EXPECTED_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_CHUNK_SIZE = 1024 * 1024
_MULTIPART_SIZE = 8 * 1024 * 1024


class S3BlobStore:
    def __init__(self, client: Any, bucket: str) -> None:
        if not bucket:
            raise ValueError("bucket must not be empty")
        self._client = client
        self._bucket = bucket
        self._transfer = TransferConfig(
            multipart_threshold=_MULTIPART_SIZE,
            multipart_chunksize=_MULTIPART_SIZE,
            max_concurrency=4,
            use_threads=True,
        )

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
        with tempfile.SpooledTemporaryFile(max_size=_MULTIPART_SIZE, mode="w+b") as temporary:
            while chunk := stream.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > maximum_bytes:
                    raise BlobTooLarge(f"blob exceeds maximum of {maximum_bytes} bytes")
                digest.update(chunk)
                temporary.write(chunk)
            actual = digest.hexdigest()
            if expected is not None and not compare_digest(actual, expected):
                raise BlobHashMismatch("blob SHA-256 does not match expected value")
            key = self._key(actual)
            existing = self._head_or_none(key)
            if existing is None:
                temporary.seek(0)
                try:
                    self._client.upload_fileobj(
                        temporary,
                        self._bucket,
                        key,
                        ExtraArgs={
                            "ContentType": content_type,
                            "Metadata": {"sha256": actual, "size": str(size)},
                        },
                        Config=self._transfer,
                    )
                except (BotoCoreError, ClientError) as error:
                    self._raise_storage_error(error)
            reference = self.stat(key)
            if reference.sha256 != actual or reference.size != size:
                raise BlobError("stored blob metadata failed verification")
            return reference

    def open(self, key: str) -> BinaryIO:
        self._validate_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            self._raise_storage_error(error)
        return response["Body"]

    def stat(self, key: str) -> BlobRef:
        digest = self._validate_key(key)
        response = self._head_or_none(key)
        if response is None:
            raise BlobNotFound("blob not found")
        metadata = response.get("Metadata", {})
        if metadata.get("sha256") != digest:
            raise BlobError("stored blob digest metadata is invalid")
        try:
            recorded_size = int(metadata["size"])
            actual_size = int(response["ContentLength"])
        except (KeyError, TypeError, ValueError) as error:
            raise BlobError("stored blob size metadata is invalid") from error
        if recorded_size != actual_size:
            raise BlobError("stored blob size metadata failed verification")
        return BlobRef(
            digest,
            actual_size,
            str(response.get("ContentType") or "application/octet-stream"),
            key,
        )

    def delete(self, key: str) -> None:
        self._validate_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            self._raise_storage_error(error)

    def _head_or_none(self, key: str) -> dict[str, Any] | None:
        try:
            return self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = error.response.get("Error", {}).get("Code")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            self._raise_storage_error(error)
        except BotoCoreError as error:
            self._raise_storage_error(error)

    @staticmethod
    def _key(digest: str) -> str:
        return f"objects/{digest[:2]}/{digest[2:4]}/{digest}"

    @staticmethod
    def _validate_key(key: str) -> str:
        match = _KEY_PATTERN.fullmatch(key)
        if (
            match is None
            or match.group(1) != match.group(3)[:2]
            or match.group(2) != match.group(3)[2:4]
        ):
            raise BlobNotFound("blob not found")
        return match.group(3)

    @staticmethod
    def _raise_storage_error(error: BotoCoreError | ClientError) -> Never:
        if isinstance(error, ClientError):
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            code = error.response.get("Error", {}).get("Code")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                raise BlobNotFound("blob not found") from error
            if status == 429 or status >= 500:
                raise BlobTransientError("temporary blob storage failure") from error
            raise BlobError("blob storage request failed") from error
        raise BlobTransientError("temporary blob storage failure") from error
