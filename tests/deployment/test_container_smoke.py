from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "sci-search:program7-test"


def test_production_compose_only_publishes_caddy_ports() -> None:
    rendered = subprocess.run(
        ["docker", "compose", "-f", "compose.yml", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SCI_SEARCH_ALLOWED_ORIGINS": "https://search.example.test",
            "SCI_SEARCH_PUBLIC_BASE_URL": "https://search.example.test",
            "SCI_SEARCH_OIDC_ISSUER": "https://idp.example.test",
            "SCI_SEARCH_OIDC_CLIENT_ID": "test-client",
            "SCI_SEARCH_OIDC_CALLBACK_URL": "https://search.example.test/auth/callback",
            "SCI_SEARCH_HOSTNAME": "search.example.test",
            "SCI_SEARCH_REDIS_PASSWORD": "test-only-password",
        },
    )
    services = json.loads(rendered.stdout)["services"]
    assert services["caddy"]["ports"]
    for name in ("web", "worker", "postgres", "redis", "minio"):
        assert not services[name].get("ports"), name


@pytest.mark.skipif(
    os.environ.get("SCI_SEARCH_CONTAINER_TESTS") != "1",
    reason="set SCI_SEARCH_CONTAINER_TESTS=1 for the image smoke gate",
)
def test_image_is_non_root_and_contains_no_source_secrets_or_data() -> None:
    subprocess.run(["docker", "build", "--tag", IMAGE, "."], cwd=ROOT, check=True)
    user = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Config.User}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert user not in {"", "0", "root"}
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            IMAGE,
            "python",
            "-c",
            (
                "import importlib.util,pathlib,sci_search; "
                "root=pathlib.Path('/app'); "
                "assert importlib.util.find_spec('sci_search'); "
                "assert not (root/'.env.local').exists(); "
                "assert not (root/'data').exists()"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0


def test_dockerfile_pins_base_digest_and_declares_non_root_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.11-slim@sha256:" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "COPY --from=builder" in dockerfile
