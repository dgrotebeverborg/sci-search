import json

import pytest

from sci_search.data_research import retrieval


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status, self._body, self._headers = status, body, headers or {}

    def read(self, n):
        return self._body[:n]

    def getheader(self, name, default=None):
        return self._headers.get(name, default)


class FakeConnection:
    calls = []
    response = FakeResponse(200, b'{"ok": true}', {"Content-Type": "application/json"})

    def __init__(self, host, port, timeout):
        self.host = host

    def request(self, method, path, body=None, headers=None):
        FakeConnection.calls.append((method, self.host, path, body, headers))

    def getresponse(self):
        return FakeConnection.response

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    FakeConnection.calls = []
    FakeConnection.response = FakeResponse(
        200, b'{"ok": true}', {"Content-Type": "application/json"}
    )
    monkeypatch.setattr(retrieval, "public_addresses", lambda url: ["203.0.113.5"])
    monkeypatch.setattr(retrieval.http.client, "HTTPSConnection", FakeConnection)
    return FakeConnection


def test_post_sends_json_body_to_validated_host(fake):
    body, content_type, url = retrieval.post_public(
        "https://data.ssb.no/api/v0/en/table/07459",
        {"query": [], "response": {"format": "json-stat2"}},
    )
    method, host, path, sent, headers = fake.calls[0]
    assert (method, host, path) == ("POST", "data.ssb.no", "/api/v0/en/table/07459")
    assert json.loads(sent) == {"query": [], "response": {"format": "json-stat2"}}
    assert headers["Content-Type"] == "application/json"
    assert body == b'{"ok": true}' and content_type == "application/json"


def test_post_refuses_redirects(fake):
    fake.response = FakeResponse(302, headers={"Location": "https://elsewhere.example/"})
    with pytest.raises(ValueError, match="POST redirect refused"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {})


def test_post_enforces_size_limits(fake):
    fake.response = FakeResponse(200, b"x" * 11)
    with pytest.raises(ValueError, match="acquisition limit"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {}, limit=10)
    with pytest.raises(ValueError, match="64 KB"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {"x": "y" * 70_000})


def test_post_rejects_private_targets(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        retrieval.post_public("https://data.ssb.no/api/v0/en/table/1", {})
