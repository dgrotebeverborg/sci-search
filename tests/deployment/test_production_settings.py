from __future__ import annotations

from pathlib import Path

import pytest

from sci_search.api.bootstrap import build_api_application
from sci_search.infrastructure.settings import ProductionSettings


def _valid(**overrides: object) -> ProductionSettings:
    values: dict[str, object] = {
        "environment": "production",
        "public_base_url": "https://search.uu.nl",
        "allowed_origins": ("https://search.uu.nl",),
        "database_url": "postgresql+psycopg://sci_search:long-random-db-password@postgres/sci_search",
        "redis_url": "redis://:long-random-redis-password@redis:6379/0",
        "s3_endpoint": "http://minio:9000",
        "s3_bucket": "sci-search",
        "s3_access_key": "sci-search-production-access",
        "s3_secret_key": "long-random-object-storage-secret",
        "session_secret": "s" * 64,
        "oidc_issuer": "https://connect.surfconext.nl",
        "oidc_client_id": "sci-search-production",
        "oidc_client_secret": "long-random-oidc-secret",
        "oidc_callback_url": "https://search.uu.nl/auth/callback",
        "development_auth_enabled": False,
    }
    values.update(overrides)
    return ProductionSettings(**values)  # type: ignore[arg-type]


def test_literal_surfconext_style_configuration_is_valid_and_redacted() -> None:
    settings = _valid()
    rendered = repr(settings)
    assert settings.oidc_issuer == "https://connect.surfconext.nl"
    assert "long-random" not in rendered
    assert "ssssssss" not in rendered
    assert "<redacted>" in rendered


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_origins": ("*",)},
        {"allowed_origins": ("http://search.uu.nl",)},
        {"public_base_url": "http://search.uu.nl"},
        {"oidc_callback_url": "http://search.uu.nl/auth/callback"},
        {"oidc_issuer": "http://connect.surfconext.nl"},
        {"development_auth_enabled": True},
        {"session_secret": "change-me"},
        {"oidc_client_secret": "secret"},
        {"s3_secret_key": "password"},
        {"database_url": "sqlite:///local.db"},
        {"redis_url": "redis://redis:6379/0"},
        {"s3_bucket": ""},
    ],
)
def test_insecure_production_configuration_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _valid(**overrides)


def test_secret_files_are_loaded_without_placing_secret_values_in_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = {
        "SCI_SEARCH_DATABASE_URL": "postgresql+psycopg://sci_search:production-db-secret@postgres/sci_search",
        "SCI_SEARCH_REDIS_URL": "redis://:production-redis-secret@redis:6379/0",
        "SCI_SEARCH_S3_ACCESS_KEY": "production-access-key",
        "SCI_SEARCH_S3_SECRET_KEY": "production-object-secret",
        "SCI_SEARCH_SESSION_SECRET": "x" * 64,
        "SCI_SEARCH_OIDC_CLIENT_SECRET": "production-oidc-secret",
    }
    for name, value in secrets.items():
        path = tmp_path / name.casefold()
        path.write_text(value + "\n", encoding="utf-8")
        monkeypatch.setenv(f"{name}_FILE", str(path))
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "production")
    monkeypatch.setenv("SCI_SEARCH_PUBLIC_BASE_URL", "https://search.uu.nl")
    monkeypatch.setenv("SCI_SEARCH_ALLOWED_ORIGINS", "https://search.uu.nl")
    monkeypatch.setenv("SCI_SEARCH_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("SCI_SEARCH_S3_BUCKET", "sci-search")
    monkeypatch.setenv("SCI_SEARCH_OIDC_ISSUER", "https://connect.surfconext.nl")
    monkeypatch.setenv("SCI_SEARCH_OIDC_CLIENT_ID", "sci-search")
    monkeypatch.setenv("SCI_SEARCH_OIDC_CALLBACK_URL", "https://search.uu.nl/auth/callback")

    settings = ProductionSettings.from_environment()

    assert settings.database_url.endswith("@postgres/sci_search")
    assert settings.session_secret == "x" * 64
    assert all(name not in __import__("os").environ for name in secrets)


def _set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "production")
    monkeypatch.setenv("SCI_SEARCH_PUBLIC_BASE_URL", "https://search.uu.nl")
    monkeypatch.setenv("SCI_SEARCH_ALLOWED_ORIGINS", "https://search.uu.nl")
    monkeypatch.setenv(
        "SCI_SEARCH_DATABASE_URL",
        "postgresql+psycopg://sci_search:production-db-secret@postgres/sci_search",
    )
    monkeypatch.setenv("SCI_SEARCH_REDIS_URL", "redis://:production-redis-secret@redis:6379/0")
    monkeypatch.setenv("SCI_SEARCH_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("SCI_SEARCH_S3_BUCKET", "sci-search")
    monkeypatch.setenv("SCI_SEARCH_S3_ACCESS_KEY", "production-access-key")
    monkeypatch.setenv("SCI_SEARCH_S3_SECRET_KEY", "production-object-secret")
    monkeypatch.setenv("SCI_SEARCH_SESSION_SECRET", "x" * 64)
    monkeypatch.setenv("SCI_SEARCH_OIDC_ISSUER", "https://connect.surfconext.nl")
    monkeypatch.setenv("SCI_SEARCH_OIDC_CLIENT_ID", "sci-search")
    monkeypatch.setenv("SCI_SEARCH_OIDC_CLIENT_SECRET", "production-oidc-secret")
    monkeypatch.setenv("SCI_SEARCH_OIDC_CALLBACK_URL", "https://search.uu.nl/auth/callback")


def test_production_bootstrap_uses_validated_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_valid_environment(monkeypatch)

    app = build_api_application(tmp_path)

    assert app.state.api_settings.environment == "production"
    assert app.state.api_settings.allowed_origins == ("https://search.uu.nl",)
    assert app.state.api_settings.session_secret == "x" * 64
    assert app.state.api_settings.development_auth_enabled is False
    assert app.state.production_settings.s3_bucket == "sci-search"


def test_production_bootstrap_rejects_insecure_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_valid_environment(monkeypatch)
    monkeypatch.setenv("SCI_SEARCH_ALLOWED_ORIGINS", "*")

    with pytest.raises(ValueError, match="explicit allowed origins"):
        build_api_application(tmp_path)


def test_production_bootstrap_rejects_unsafe_development_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_valid_environment(monkeypatch)

    with pytest.raises(ValueError, match="development authentication"):
        build_api_application(tmp_path, unsafe_development=True)


def test_production_bootstrap_rejects_non_postgresql_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_valid_environment(monkeypatch)
    monkeypatch.setenv("SCI_SEARCH_DATABASE_URL", "sqlite:///unsafe.db")

    with pytest.raises(ValueError, match="database must be PostgreSQL"):
        build_api_application(tmp_path)
