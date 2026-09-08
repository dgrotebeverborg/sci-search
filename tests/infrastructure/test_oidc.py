import json
import logging
import threading
import time
from base64 import urlsafe_b64encode
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from joserfc import jwt
from joserfc.jwk import ECKey, RSAKey
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from sci_search.infrastructure.oidc import OidcConfiguration, OidcProvider


class FakeOidcServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FakeOidcHandler)
        self.issuer = f"http://127.0.0.1:{self.server_port}"
        self.signing_key = RSAKey.generate_key(2048, private=True, auto_kid=True)
        self.wrong_key = RSAKey.generate_key(2048, private=True, auto_kid=True)
        self.unsupported_algorithm_key = ECKey.generate_key("P-256", auto_kid=True)
        self.claim_overrides: dict[str, object] = {}
        self.omitted_claims: set[str] = set()
        self.algorithm = "RS256"
        self.use_wrong_key = False
        self.expected_nonce = ""
        self.expected_challenge = ""
        self.last_token_request: dict[str, list[str]] = {}
        self.last_id_token = ""

    def id_token(self) -> str:
        now = int(time.time())
        claims: dict[str, object] = {
            "iss": self.issuer,
            "sub": "stable-subject",
            "aud": "sci-search-client",
            "iat": now,
            "exp": now + 300,
            "nonce": self.expected_nonce,
            "email": "researcher@example.test",
            "name": "Researcher",
        }
        claims.update(self.claim_overrides)
        for name in self.omitted_claims:
            claims.pop(name, None)
        if self.algorithm == "ES256":
            key = self.unsupported_algorithm_key
        else:
            key = self.wrong_key if self.use_wrong_key else self.signing_key
        return jwt.encode(
            {"alg": self.algorithm, "kid": self.signing_key.thumbprint()},
            claims,
            key,
        )


class FakeOidcHandler(BaseHTTPRequestHandler):
    server: FakeOidcServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/.well-known/openid-configuration":
            self._json(
                {
                    "issuer": self.server.issuer,
                    "authorization_endpoint": f"{self.server.issuer}/authorize",
                    "token_endpoint": f"{self.server.issuer}/token",
                    "jwks_uri": f"{self.server.issuer}/jwks",
                    "end_session_endpoint": f"{self.server.issuer}/logout",
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "code_challenge_methods_supported": ["S256"],
                }
            )
            return
        if self.path == "/jwks":
            public_key = self.server.signing_key.as_dict(private=False)
            public_key.update({"kid": self.server.signing_key.thumbprint(), "use": "sig"})
            self._json({"keys": [public_key]})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/token":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("content-length", "0"))).decode()
        form = parse_qs(body)
        self.server.last_token_request = form
        verifier = form.get("code_verifier", [""])[0]
        challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if (
            form.get("redirect_uri") != ["https://app.example.test/auth/callback"]
            or not verifier
            or challenge != self.server.expected_challenge
        ):
            self._json({"error": "invalid_grant"}, status=400)
            return
        self.server.last_id_token = self.server.id_token()
        self._json(
            {
                "access_token": "provider-access-token",
                "token_type": "Bearer",
                "id_token": self.server.last_id_token,
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, value: object, *, status: int = 200) -> None:
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def fake_oidc() -> FakeOidcServer:
    server = FakeOidcServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def oidc_client(fake_oidc: FakeOidcServer) -> tuple[TestClient, FakeOidcServer]:
    provider = OidcProvider(
        OidcConfiguration(
            discovery_url=f"{fake_oidc.issuer}/.well-known/openid-configuration",
            client_id="sci-search-client",
            client_secret="client-secret",
            redirect_uri="https://app.example.test/auth/callback",
            post_logout_redirect_uri="https://app.example.test/",
            production=False,
        )
    )

    async def login(request: Request):
        return await provider.authorization_redirect(request)

    async def callback(request: Request):
        principal = await provider.exchange_callback(request)
        return JSONResponse(
            {
                "issuer": principal.identity.issuer,
                "subject": principal.identity.subject,
                "email": principal.profile.email,
            }
        )

    app = Starlette(routes=[Route("/login", login), Route("/auth/callback", callback)])
    app.add_middleware(SessionMiddleware, secret_key="test-session-signing-key", https_only=True)
    with TestClient(
        app, base_url="https://app.example.test", raise_server_exceptions=True
    ) as client:
        yield client, fake_oidc


def _start_login(client: TestClient, server: FakeOidcServer) -> dict[str, list[str]]:
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    server.expected_nonce = query["nonce"][0]
    server.expected_challenge = query["code_challenge"][0]
    return query


def test_authorization_code_flow_uses_state_nonce_pkce_and_exact_redirect_uri(
    oidc_client: tuple[TestClient, FakeOidcServer],
) -> None:
    client, server = oidc_client
    query = _start_login(client, server)

    assert query["redirect_uri"] == ["https://app.example.test/auth/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"][0]
    assert query["nonce"][0]

    response = client.get(f"/auth/callback?code=valid&state={query['state'][0]}")

    assert response.status_code == 200
    assert response.json() == {
        "issuer": server.issuer,
        "subject": "stable-subject",
        "email": "researcher@example.test",
    }
    assert server.last_token_request["redirect_uri"] == ["https://app.example.test/auth/callback"]
    assert server.last_token_request["code_verifier"][0]


def test_pkce_verifier_is_not_written_to_debug_logs(
    oidc_client: tuple[TestClient, FakeOidcServer],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, server = oidc_client
    caplog.set_level(logging.DEBUG)

    _start_login(client, server)

    assert "code_verifier" not in caplog.text


def test_provider_tokens_and_client_secret_are_not_written_to_logs(
    oidc_client: tuple[TestClient, FakeOidcServer],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, server = oidc_client
    caplog.set_level(logging.DEBUG)
    query = _start_login(client, server)

    response = client.get(f"/auth/callback?code=valid&state={query['state'][0]}")

    assert response.status_code == 200
    assert "provider-access-token" not in caplog.text
    assert "client-secret" not in caplog.text
    assert server.last_id_token not in caplog.text


def test_callback_rejects_mismatched_state(
    oidc_client: tuple[TestClient, FakeOidcServer],
) -> None:
    client, server = oidc_client
    _start_login(client, server)

    with pytest.raises(Exception, match="state"):
        client.get("/auth/callback?code=valid&state=wrong-state")


def test_production_configuration_rejects_insecure_callback_url() -> None:
    with pytest.raises(ValueError, match="production redirect URI must use HTTPS"):
        OidcConfiguration(
            discovery_url="https://idp.example.test/.well-known/openid-configuration",
            client_id="client",
            client_secret="secret",
            redirect_uri="http://app.example.test/auth/callback",
            post_logout_redirect_uri="https://app.example.test/",
        )


def test_production_configuration_rejects_local_login_fallback() -> None:
    with pytest.raises(ValueError, match="local login is forbidden in production"):
        OidcConfiguration(
            discovery_url="https://idp.example.test/.well-known/openid-configuration",
            client_id="client",
            client_secret="secret",
            redirect_uri="https://app.example.test/auth/callback",
            post_logout_redirect_uri="https://app.example.test/",
            local_login_enabled=True,
        )


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("nonce", "nonce"),
        ("issuer", "iss"),
        ("audience", "aud"),
        ("signature", "signature"),
        ("algorithm", "algorithm"),
        ("issued-at", "iat"),
        ("expiry", "exp"),
    ],
)
def test_callback_rejects_invalid_id_tokens(
    oidc_client: tuple[TestClient, FakeOidcServer],
    failure: str,
    message: str,
) -> None:
    client, server = oidc_client
    query = _start_login(client, server)
    if failure == "nonce":
        server.claim_overrides["nonce"] = "wrong-nonce"
    elif failure == "issuer":
        server.claim_overrides["iss"] = "https://wrong-issuer.example"
    elif failure == "audience":
        server.claim_overrides["aud"] = "different-client"
    elif failure == "signature":
        server.use_wrong_key = True
    elif failure == "algorithm":
        server.algorithm = "ES256"
    elif failure == "issued-at":
        server.omitted_claims.add("iat")
    elif failure == "expiry":
        server.claim_overrides["exp"] = int(time.time()) - 10

    with pytest.raises(Exception, match=message):
        client.get(f"/auth/callback?code=valid&state={query['state'][0]}")
