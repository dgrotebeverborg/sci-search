from __future__ import annotations

from pathlib import Path

import pytest

import sci_search.cli as cli

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"


def test_serve_selects_fastapi_with_safe_loopback_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    application = object()
    monkeypatch.setattr(
        cli,
        "build_api_application",
        lambda corpus, **options: calls.append(("build", corpus, options)) or application,
    )
    monkeypatch.setattr(
        cli,
        "run_api_server",
        lambda app, host, port: calls.append(("serve", app, host, port)),
    )

    result = cli.main(("--corpus", str(CORPUS), "serve"))

    assert result == 0
    assert calls == [
        ("build", CORPUS, {"unsafe_development": False}),
        ("serve", application, "127.0.0.1", 8000),
    ]


def test_legacy_server_requires_two_explicit_opt_in_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        cli,
        "run_legacy_local_web",
        lambda host, port, corpora: calls.append((host, port, corpora)),
    )

    with pytest.raises(SystemExit):
        cli.main(("--corpus", str(CORPUS), "serve", "--legacy-local-web"))

    assert (
        cli.main(
            (
                "--corpus",
                str(CORPUS),
                "serve",
                "--legacy-local-web",
                "--unsafe-development",
            )
        )
        == 0
    )
    assert calls == [("127.0.0.1", 8000, (CORPUS,))]


def test_unsafe_development_mode_cannot_bind_beyond_loopback() -> None:
    with pytest.raises(SystemExit):
        cli.main(
            (
                "--corpus",
                str(CORPUS),
                "serve",
                "--host",
                "0.0.0.0",
                "--unsafe-development",
            )
        )
