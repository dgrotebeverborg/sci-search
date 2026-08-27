from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from scripts.deploy import DeployConfig, DeploymentError, SubprocessExecutor, deploy
from scripts.migrate import migrate_with_lock


class Recorder:
    def __init__(self, *, readiness_failures: int = 0) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.probes: list[str] = []
        self.readiness_failures = readiness_failures

    def run(self, command: list[str], *, timeout: float | None = None) -> None:
        del timeout
        self.commands.append(tuple(command))

    def ready(self, url: str, *, timeout: float) -> bool:
        del timeout
        self.probes.append(url)
        if self.readiness_failures:
            self.readiness_failures -= 1
            return False
        return True


def _config(tmp_path: Path, **overrides: object) -> DeployConfig:
    values: dict[str, object] = {
        "environment": "production",
        "hostname": "search.uu.nl",
        "confirmation": "DEPLOY search.uu.nl",
        "compose_command": ("docker", "compose"),
        "backup_command": ("backup-now",),
        "readiness_url": "https://search.uu.nl/health/ready",
        "drain_timeout_seconds": 30,
        "readiness_timeout_seconds": 10,
        "readiness_attempts": 3,
        "state_file": tmp_path / "deployment-state.json",
        "previous_image": "registry.example/sci-search@sha256:" + "a" * 64,
        "migration_rollback_revision": "0005_risk_of_bias",
    }
    values.update(overrides)
    return DeployConfig(**values)  # type: ignore[arg-type]


def test_deploy_order_is_backup_drain_migrate_start_ready_release(tmp_path: Path) -> None:
    recorder = Recorder(readiness_failures=1)

    result = deploy(_config(tmp_path), executor=recorder, sleeper=lambda _seconds: None)

    assert recorder.commands == [
        ("backup-now",),
        ("docker", "compose", "stop", "--timeout", "30", "worker"),
        ("docker", "compose", "--profile", "admin", "run", "--rm", "migrate"),
        ("docker", "compose", "up", "--detach", "--no-deps", "web"),
        ("docker", "compose", "up", "--detach", "worker"),
    ]
    assert recorder.probes == [
        "https://search.uu.nl/health/ready",
        "https://search.uu.nl/health/ready",
    ]
    assert result.status == "released"
    assert result.rollback_eligible is True
    assert result.state_file.is_file()


@pytest.mark.parametrize("confirmation", ["", "yes", "DEPLOY other.example"])
def test_production_requires_literal_host_confirmation(tmp_path: Path, confirmation: str) -> None:
    recorder = Recorder()
    with pytest.raises(DeploymentError, match="confirmation"):
        deploy(
            _config(tmp_path, confirmation=confirmation),
            executor=recorder,
            sleeper=lambda _seconds: None,
        )
    assert recorder.commands == []


def test_readiness_failure_does_not_release_workers(tmp_path: Path) -> None:
    recorder = Recorder(readiness_failures=10)
    with pytest.raises(DeploymentError, match="readiness"):
        deploy(
            _config(tmp_path, readiness_attempts=2),
            executor=recorder,
            sleeper=lambda _seconds: None,
        )
    assert recorder.commands[-1] == (
        "docker",
        "compose",
        "up",
        "--detach",
        "--no-deps",
        "web",
    )
    assert all(command[-1] != "worker" for command in recorder.commands[3:])


def test_deploy_rejects_unbounded_timeouts_and_missing_rollback_metadata(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        _config(tmp_path, drain_timeout_seconds=0)
    recorder = Recorder()
    result = deploy(
        _config(tmp_path, previous_image=None, migration_rollback_revision=None),
        executor=recorder,
        sleeper=lambda _seconds: None,
    )
    assert result.rollback_eligible is False


def test_migration_holds_and_releases_a_database_advisory_lock(tmp_path: Path) -> None:
    events: list[str] = []

    class Connection:
        def execute(self, statement, parameters=None) -> None:
            del parameters
            events.append(str(statement))

        def __enter__(self):
            events.append("connected")
            return self

        def __exit__(self, *args: object) -> None:
            events.append("disconnected")

    class Engine:
        def connect(self) -> Connection:
            return Connection()

        def dispose(self) -> None:
            events.append("disposed")

    migrate_with_lock(
        "postgresql://user:secret@postgres/sci_search",
        tmp_path / "alembic.ini",
        engine_factory=lambda _url: Engine(),
        upgrade=lambda configuration, revision: events.append(
            f"upgrade:{configuration.get_main_option('sqlalchemy.url')}:{revision}"
        ),
    )

    assert "pg_advisory_lock" in events[1]
    assert events[2] == "upgrade:postgresql://user:secret@postgres/sci_search:head"
    assert "pg_advisory_unlock" in events[3]
    assert events[-2:] == ["disconnected", "disposed"]


@pytest.mark.skipif(
    os.environ.get("SCI_SEARCH_DEPLOY_REHEARSAL") != "1",
    reason="set SCI_SEARCH_DEPLOY_REHEARSAL=1 for the isolated Compose rehearsal",
)
def test_real_test_stack_deployment_and_rollback_rehearsal(tmp_path: Path) -> None:
    compose = tmp_path / "compose.rehearsal.yml"
    compose.write_text(
        """services:
  web:
    image: sci-search:program7-test
    entrypoint: ["python", "-m", "http.server", "58999", "--bind", "0.0.0.0"]
    ports: ["127.0.0.1:58999:58999"]
  worker:
    image: sci-search:program7-test
    entrypoint: ["python", "-c", "import time; time.sleep(600)"]
  migrate:
    image: sci-search:program7-test
    entrypoint: ["python", "-c", "print('migration lock rehearsal')"]
    profiles: ["admin"]
""",
        encoding="utf-8",
    )
    compose_command = (
        "docker",
        "compose",
        "--project-name",
        "sci-search-deploy-rehearsal",
        "--file",
        str(compose),
    )
    executor = SubprocessExecutor()
    try:
        executor.run([*compose_command, "up", "--detach", "worker"], timeout=60)
        result = deploy(
            _config(
                tmp_path,
                compose_command=compose_command,
                backup_command=(
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(tmp_path / 'backup.complete')!r}).write_text('ok')",
                ),
                readiness_url="http://127.0.0.1:58999/",
                readiness_interval_seconds=0.1,
                readiness_attempts=20,
            ),
            executor=executor,
        )
        assert result.status == "released"
        assert (tmp_path / "backup.complete").is_file()

        executor.run([*compose_command, "stop", "--timeout", "10", "worker"], timeout=30)
        executor.run([*compose_command, "up", "--detach", "--no-deps", "web"], timeout=60)
        with urllib.request.urlopen("http://127.0.0.1:58999/", timeout=5) as response:
            assert response.status == 200
        executor.run([*compose_command, "up", "--detach", "worker"], timeout=60)
    finally:
        subprocess.run([*compose_command, "down", "--volumes"], check=False, timeout=60)
