"""Public, bounded downloads with DNS pinning, including every redirect."""

import http.client
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit


def public_addresses(url):
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 80, 443}
    ):
        raise ValueError("Only public HTTP(S) dataset URLs are supported")
    host = parts.hostname
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Dataset URL targets a private host")
    addresses = list(
        dict.fromkeys(
            item[4][0]
            for item in socket.getaddrinfo(
                host,
                parts.port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        )
    )
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Dataset URL resolves to a non-public address")
    return addresses


def fetch_public(url, *, limit=50_000_000):
    for _ in range(5):
        addresses = public_addresses(url)
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = cls(parts.hostname, port, timeout=35)
        # Connect to the validated address, retaining hostname for TLS/SNI verification.
        connection._create_connection = (
            lambda address, timeout, *args, addresses=addresses, port=port: (
                socket.create_connection((addresses[0], port), timeout)
            )
        )
        try:
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request(
                "GET",
                path,
                headers={
                    "User-Agent": "Sci-Search/0.2 (public research data)",
                    "Accept-Encoding": "identity",
                    "Accept": "*/*",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise ValueError("Dataset redirect lacks a location")
                url = urljoin(url, target)
                continue
            if response.status != 200:
                raise ValueError(f"Dataset server returned HTTP {response.status}")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError(f"Dataset exceeds the {limit // 1_000_000} MB acquisition limit")
            return body, response.getheader("Content-Type", ""), url
        finally:
            connection.close()
    raise ValueError("Dataset exceeded the redirect limit")


class Page(HTMLParser):
    def __init__(self, url):
        super().__init__()
        self.url, self.links, self.text, self.skip = url, [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            target = urljoin(self.url, href)
            if href and target.startswith(("https://", "http://")) and target not in self.links:
                self.links.append(target)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


def is_html(body, content_type):
    prefix = body.lstrip()[:100].lower()
    return "html" in content_type.lower() or prefix.startswith((b"<!doctype html", b"<html"))


def inspect_page(body, url):
    page = Page(url)
    page.feed(body.decode("utf-8", errors="replace"))
    return {"text": " ".join(" ".join(page.text).split())[:40000], "links": page.links[:250]}


def fetch_scoped(url, scope, fetch, attempts):
    """Retry oversized observed Eurostat API downloads using documented parameters."""
    from urllib.parse import parse_qsl, urlencode

    try:
        return _await_eurostat(fetch(url), fetch, attempts)
    except ValueError as exc:
        parts = urlsplit(url)
        if (
            "acquisition limit" not in str(exc)
            or parts.hostname != "ec.europa.eu"
            or not parts.path.startswith("/eurostat/api/dissemination/sdmx/2.1/data/")
        ):
            raise
        parameters = dict(parse_qsl(parts.query, keep_blank_values=True))
        parameters.update(format="TSV", compressed="true")
        if scope.get("start_year") is not None:
            parameters["startPeriod"] = str(scope["start_year"])
        if scope.get("end_year") is not None:
            parameters["endPeriod"] = str(scope["end_year"])
        retry = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(parameters), ""))
        if retry == url:
            raise
        attempts.append(
            {
                "original_url": url,
                "url": retry,
                "status": "retried_with_requested_period",
                "reason": "Download exceeded the size limit; requested compressed data for the requested years.",
            }
        )
        return _await_eurostat(fetch(retry), fetch, attempts)


def eurostat_download_url(url, scope):
    """Resolve dataset IDs from observed official pages using the documented SDMX API."""
    import re
    from urllib.parse import urlencode

    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "ec.europa.eu":
        return None
    match = re.match(
        r"^/eurostat/(?:databrowser/view|web/products-datasets/-)/([a-zA-Z0-9_]+)(?:/|$)",
        parts.path,
    )
    if not match:
        return None
    parameters = {"format": "TSV", "compressed": "true"}
    for name, key in [("startPeriod", "start_year"), ("endPeriod", "end_year")]:
        if scope.get(key) is not None:
            parameters[name] = str(scope[key])
    return (
        "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
        + match[1]
        + "/?"
        + urlencode(parameters)
    )


def _await_eurostat(response, fetch, attempts):
    """Follow the documented Eurostat asynchronous delivery protocol, bounded to six checks."""
    import re
    import time
    from xml.etree import ElementTree

    body, content_type, url = response
    parts = urlsplit(url)
    if (
        parts.hostname != "ec.europa.eu"
        or not parts.path.startswith("/eurostat/api/dissemination/")
        or not body.lstrip().startswith(b"<")
        or b"queued" not in body[:10000]
    ):
        return response

    def parse(payload):
        if (
            len(payload) > 100000
            or b"<!DOCTYPE" in payload.upper()
            or b"<!ENTITY" in payload.upper()
        ):
            raise ValueError("Unsafe or oversized Eurostat status response")
        try:
            return ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise ValueError("Invalid Eurostat asynchronous status response") from exc

    queued = next(
        (item for item in parse(body).iter() if item.tag.split("}")[-1] == "queued"), None
    )
    if queued is None:
        return response
    key = next((item.text for item in queued if item.tag.split("}")[-1] == "id"), "")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", key or ""):
        raise ValueError("Invalid Eurostat asynchronous request identifier")
    base = "https://ec.europa.eu/eurostat/api/dissemination/1.0/async/"
    for index in range(6):
        payload, _, _ = fetch(base + "status/" + key)
        statuses = [
            item.text
            for item in parse(payload).iter()
            if item.tag.split("}")[-1] == "status" and item.text and item.text.strip()
        ]
        status = statuses[-1].strip() if statuses else "UNKNOWN"
        attempts.append(
            {
                "method": "eurostat_async_status",
                "request_id": key,
                "status": status,
                "original_url": url,
            }
        )
        if status == "AVAILABLE":
            return fetch(base + "data/" + key)
        if status not in {"SUBMITTED", "PROCESSING"}:
            raise ValueError("Eurostat asynchronous download status: " + status)
        if index < 5:
            time.sleep(2)
    raise ValueError(
        "Eurostat is still preparing the dataset after the bounded status checks; no observations were read"
    )
