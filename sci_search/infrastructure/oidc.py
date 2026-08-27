"""Authlib-backed OpenID Connect adapter."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse

from sci_search.application.identity import ExternalIdentity, IdentityProfile

_AUTHLIB_FLOW_LOGGER = "authlib.integrations.base_client.sync_app"


def _require_secure_url(name: str, value: str, *, production: bool) -> None:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute URL")
    if production and parsed.scheme != "https":
        raise ValueError(f"production {name} must use HTTPS")


@dataclass(frozen=True, slots=True)
class OidcConfiguration:
    discovery_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    post_logout_redirect_uri: str
    production: bool = True

    def __post_init__(self) -> None:
        _require_secure_url("discovery URL", self.discovery_url, production=self.production)
        _require_secure_url("redirect URI", self.redirect_uri, production=self.production)
        _require_secure_url(
            "post-logout redirect URI",
            self.post_logout_redirect_uri,
            production=self.production,
        )
        if not self.client_id or not self.client_secret:
            raise ValueError("OIDC client credentials must not be empty")


@dataclass(frozen=True, slots=True)
class OidcPrincipal:
    identity: ExternalIdentity
    profile: IdentityProfile


class OidcProvider:
    """Authorization Code + PKCE client using Authlib protocol validation."""

    def __init__(self, configuration: OidcConfiguration) -> None:
        self._configuration = configuration
        # Authlib logs the PKCE verifier at DEBUG. It is an authorization secret,
        # so this specific dependency logger must never inherit a DEBUG root level.
        logging.getLogger(_AUTHLIB_FLOW_LOGGER).setLevel(logging.INFO)
        oauth = OAuth()
        oauth.register(
            "institution",
            client_id=configuration.client_id,
            client_secret=configuration.client_secret,
            server_metadata_url=configuration.discovery_url,
            client_kwargs={
                "scope": "openid profile email",
                "code_challenge_method": "S256",
                "token_endpoint_auth_method": "client_secret_basic",
            },
        )
        client = oauth.create_client("institution")
        if client is None:
            raise RuntimeError("could not configure OIDC client")
        self._client = client

    async def authorization_redirect(self, request: Request) -> RedirectResponse:
        return await self._client.authorize_redirect(
            request,
            redirect_uri=self._configuration.redirect_uri,
        )

    async def exchange_callback(self, request: Request) -> OidcPrincipal:
        metadata = await self._client.load_server_metadata()
        issuer = metadata.get("issuer")
        if not issuer:
            raise ValueError("OIDC discovery metadata did not contain an issuer")
        claims_options = {
            "iss": {"essential": True, "value": issuer},
            "sub": {"essential": True},
            "aud": {"essential": True, "value": self._configuration.client_id},
            "iat": {"essential": True},
            "exp": {"essential": True},
        }
        token = await self._client.authorize_access_token(
            request,
            claims_options=claims_options,
            leeway=0,
        )
        claims: dict[str, Any] | None = token.get("userinfo")
        if claims is None:
            raise ValueError("OIDC callback did not contain a validated ID token")
        identity = ExternalIdentity(str(claims["iss"]), str(claims["sub"]))
        profile = IdentityProfile(
            email=_optional_text(claims.get("email")),
            display_name=_optional_text(claims.get("name")),
            affiliation=_claim_text(claims.get("eduperson_affiliation")),
            institution=_claim_text(claims.get("schac_home_organization")),
        )
        return OidcPrincipal(identity, profile)

    async def logout_redirect(
        self,
        *,
        id_token_hint: str | None = None,
    ) -> RedirectResponse:
        result = await self._client.create_logout_url(
            post_logout_redirect_uri=self._configuration.post_logout_redirect_uri,
            id_token_hint=id_token_hint,
            client_id=self._configuration.client_id,
        )
        return RedirectResponse(result["url"], status_code=302)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _claim_text(value: object) -> str | None:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip()) or None
    return _optional_text(value)
