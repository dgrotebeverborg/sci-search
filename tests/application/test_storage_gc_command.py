from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.s3_blobs import S3BlobStore


def _load_command() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "storage_gc.py"
    spec = importlib.util.spec_from_file_location("storage_gc_command", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


storage_gc = _load_command()


def test_local_blob_root_selects_filesystem_storage(tmp_path: Path) -> None:
    arguments = storage_gc._parser().parse_args(
        ["--database-url", "sqlite:///test.db", "--blob-root", str(tmp_path)]
    )

    assert isinstance(storage_gc._blob_store(arguments), FilesystemBlobStore)


def test_production_mode_selects_s3_storage_without_oidc_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(storage_gc.boto3, "client", factory)
    arguments = storage_gc._parser().parse_args(
        [
            "--database-url",
            "postgresql://user:password@database/research",
            "--s3-endpoint",
            "http://minio:9000",
            "--s3-bucket",
            "scientific-documents",
            "--s3-access-key",
            "access-key",
            "--s3-secret-key",
            "secret-key",
        ]
    )

    store = storage_gc._blob_store(arguments)

    assert isinstance(store, S3BlobStore)
    factory.assert_called_once()


def test_storage_mode_requires_either_blob_root_or_complete_s3_configuration() -> None:
    arguments = storage_gc._parser().parse_args(["--database-url", "sqlite:///test.db"])

    with pytest.raises(ValueError, match="blob-root or complete S3 configuration"):
        storage_gc._blob_store(arguments)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (["--apply-plan", "plan-id"], "matching --confirm"),
        (["--apply-plan", "plan-id", "--confirm", "other"], "matching --confirm"),
        (["--apply-plan", "", "--confirm", ""], "non-empty UUID"),
        (["--confirm", "plan-id"], "requires --apply-plan"),
    ],
)
def test_apply_requires_an_exact_explicit_confirmation(values: list[str], message: str) -> None:
    arguments = storage_gc._parser().parse_args(
        ["--database-url", "sqlite:///test.db", "--blob-root", "/tmp/blobs", *values]
    )

    with pytest.raises(ValueError, match=message):
        storage_gc._validate_apply_arguments(arguments)
