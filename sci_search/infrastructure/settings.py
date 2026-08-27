"""Fail-closed typed production settings with Docker/Kubernetes secret-file support."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import quote, urlsplit

_INSECURE = frozenset(
    {
        "password",
        "secret",
        "change-me",
        "changeme",
        "development",
        "development-secret",
        "sci-search",
    }
)
_SECRET_ENV = {
    "database_url": "SCI_SEARCH_DATABASE_URL",
    "redis_url": "SCI_SEARCH_REDIS_URL",
    "s3_access_key": "SCI_SEARCH_S3_ACCESS_KEY",
    "s3_secret_key": "SCI_SEARCH_S3_SECRET_KEY",
    "session_secret": "SCI_SEARCH_SESSION_SECRET",
    "oidc_client_secret": "SCI_SEARCH_OIDC_CLIENT_SECRET",
}


@dataclass(frozen=True, slots=True, repr=False)
class ProductionSettings:
    environment: str
    public_base_url: str
    allowed_origins: tuple[str, ...]
    database_url: str
    redis_url: str
    s3_endpoint: str
    s3_bucket: str
    s3_access_key: str
    s3_secret_key: str
    session_secret: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_callback_url: str
    development_auth_enabled: bool = False

    def __post_init__(self) -> None:
        if self.environment != "production":
            raise ValueError("ProductionSettings requires the production environment")
        _https_url("public base URL", self.public_base_url)
        _https_url("OIDC issuer", self.oidc_issuer)
        _https_url("OIDC callback URL", self.oidc_callback_url)
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("production requires explicit allowed origins")
        for origin in self.allowed_origins:
            _https_url("allowed origin", origin)
        if self.development_auth_enabled:
            raise ValueError("development authentication is forbidden in production")
        database = urlsplit(self.database_url)
        if database.scheme not in {"postgresql", "postgresql+psycopg"} or not database.hostname:
            raise ValueError("production database must be PostgreSQL")
        if not database.password or _insecure(database.password):
            raise ValueError("production database password is missing or insecure")
        redis = urlsplit(self.redis_url)
        if redis.scheme not in {"redis", "rediss"} or not redis.hostname or not redis.password:
            raise ValueError("production Redis must use an authenticated URL")
        if _insecure(redis.password):
            raise ValueError("production Redis password is insecure")
        endpoint = urlsplit(self.s3_endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
            raise ValueError("S3 endpoint must be an absolute HTTP(S) URL")
        if not self.s3_bucket.strip():
            raise ValueError("S3 bucket must not be empty")
        for name, secret, minimum in (
            ("S3 access key", self.s3_access_key, 12),
            ("S3 secret key", self.s3_secret_key, 24),
            ("session secret", self.session_secret, 48),
            ("OIDC client secret", self.oidc_client_secret, 16),
        ):
            if len(secret) < minimum or _insecure(secret):
                raise ValueError(f"{name} is missing or insecure")
        if not self.oidc_client_id.strip():
            raise ValueError("OIDC client ID must not be empty")
        callback = urlsplit(self.oidc_callback_url)
        public = urlsplit(self.public_base_url)
        if callback.netloc != public.netloc:
            raise ValueError("OIDC callback must use the public application host")

    def __repr__(self) -> str:
        secret_fields = set(_SECRET_ENV)
        values = []
        for item in fields(self):
            value = "<redacted>" if item.name in secret_fields else getattr(self, item.name)
            values.append(f"{item.name}={value!r}")
        return f"ProductionSettings({', '.join(values)})"

    @classmethod
    def from_environment(cls) -> ProductionSettings:
        return cls(
            environment=os.environ.get("SCI_SEARCH_ENVIRONMENT", ""),
            public_base_url=os.environ.get("SCI_SEARCH_PUBLIC_BASE_URL", ""),
            allowed_origins=tuple(
                item.strip()
                for item in os.environ.get("SCI_SEARCH_ALLOWED_ORIGINS", "").split(",")
                if item.strip()
            ),
            database_url=_secret("SCI_SEARCH_DATABASE_URL"),
            redis_url=_redis_url(),
            s3_endpoint=os.environ.get("SCI_SEARCH_S3_ENDPOINT", ""),
            s3_bucket=os.environ.get("SCI_SEARCH_S3_BUCKET", ""),
            s3_access_key=_secret("SCI_SEARCH_S3_ACCESS_KEY"),
            s3_secret_key=_secret("SCI_SEARCH_S3_SECRET_KEY"),
            session_secret=_secret("SCI_SEARCH_SESSION_SECRET"),
            oidc_issuer=os.environ.get("SCI_SEARCH_OIDC_ISSUER", ""),
            oidc_client_id=os.environ.get("SCI_SEARCH_OIDC_CLIENT_ID", ""),
            oidc_client_secret=_secret("SCI_SEARCH_OIDC_CLIENT_SECRET"),
            oidc_callback_url=os.environ.get("SCI_SEARCH_OIDC_CALLBACK_URL", ""),
            development_auth_enabled=_boolean("SCI_SEARCH_DEVELOPMENT_AUTH_ENABLED"),
        )


def _secret(name: str) -> str:
    direct = os.environ.get(name)
    file_name = os.environ.get(f"{name}_FILE")
    if direct is not None and file_name is not None:
        raise ValueError(f"configure either {name} or {name}_FILE, not both")
    if file_name is None:
        return (direct or "").strip()
    path = Path(file_name)
    if not path.is_file() or path.stat().st_size > 65_536:
        raise ValueError(f"{name}_FILE is not a small regular file")
    value = path.read_text(encoding="utf-8").strip()
    if "\x00" in value:
        raise ValueError(f"{name}_FILE contains invalid data")
    return value


def _redis_url() -> str:
    if (
        os.environ.get("SCI_SEARCH_REDIS_URL") is not None
        or os.environ.get("SCI_SEARCH_REDIS_URL_FILE") is not None
    ):
        return _secret("SCI_SEARCH_REDIS_URL")
    password = _secret("SCI_SEARCH_REDIS_PASSWORD")
    host = os.environ.get("SCI_SEARCH_REDIS_HOST", "").strip()
    port = os.environ.get("SCI_SEARCH_REDIS_PORT", "6379").strip()
    database = os.environ.get("SCI_SEARCH_REDIS_DATABASE", "0").strip()
    if not host or not port.isdigit() or not database.isdigit():
        raise ValueError("Redis password mode requires a host and numeric port/database")
    return f"redis://:{quote(password, safe='')}@{host}:{port}/{database}"


def _boolean(name: str) -> bool:
    value = os.environ.get(name, "false").strip().casefold()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1"}


def _https_url(name: str, value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"production {name} must be an absolute HTTPS URL")


def _insecure(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized in _INSECURE or len(normalized) < 12
