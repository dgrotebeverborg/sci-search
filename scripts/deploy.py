#!/usr/bin/env python3
"""Execute Sci-Search's backup-first, drain-safe production deployment sequence."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from scripts.backup import _command


class DeploymentError(RuntimeError):
    pass


class CommandExecutor(Protocol):
    def run(self, command: list[str], *, timeout: float | None = None) -> None: ...

    def ready(self, url: str, *, timeout: float) -> bool: ...


@dataclass(frozen=True, slots=True)
class DeployConfig:
    environment: str
    hostname: str
    confirmation: str
    compose_command: tuple[str, ...]
    backup_command: tuple[str, ...]
    readiness_url: str
    drain_timeout_seconds: int
    readiness_timeout_seconds: float
    readiness_attempts: int
    state_file: Path
    previous_image: str | None
    migration_rollback_revision: str | None
    readiness_interval_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.environment != "production":
            raise ValueError("deployment state machine is production-only")
        if not self.hostname or not self.compose_command or not self.backup_command:
            raise ValueError("hostname, Compose command, and backup command are required")
        if self.drain_timeout_seconds <= 0 or self.drain_timeout_seconds > 3600:
            raise ValueError("drain timeout must be between 1 and 3600 seconds")
        if self.readiness_timeout_seconds <= 0 or self.readiness_timeout_seconds > 60:
            raise ValueError("readiness timeout must be between 0 and 60 seconds")
        if self.readiness_attempts <= 0 or self.readiness_attempts > 120:
            raise ValueError("readiness attempts must be between 1 and 120")
        if self.readiness_interval_seconds < 0 or self.readiness_interval_seconds > 60:
            raise ValueError("readiness interval must be between 0 and 60 seconds")


@dataclass(frozen=True, slots=True)
class DeployResult:
    status: str
    rollback_eligible: bool
    state_file: Path


def deploy(
    config: DeployConfig,
    *,
    executor: CommandExecutor | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> DeployResult:
    expected = f"DEPLOY {config.hostname}"
    if config.confirmation != expected:
        raise DeploymentError(f"production confirmation must be exactly {expected!r}")
    runner = executor or SubprocessExecutor()
    rollback_eligible = bool(config.previous_image and config.migration_rollback_revision)
    state = {
        "environment": config.environment,
        "hostname": config.hostname,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "starting",
        "previous_image": config.previous_image,
        "migration_rollback_revision": config.migration_rollback_revision,
        "rollback_eligible": rollback_eligible,
    }
    _write_state(config.state_file, state)
    try:
        _advance(config.state_file, state, "backing_up")
        runner.run(list(config.backup_command), timeout=None)

        _advance(config.state_file, state, "draining_workers")
        runner.run(
            [
                *config.compose_command,
                "stop",
                "--timeout",
                str(config.drain_timeout_seconds),
                "worker",
            ],
            timeout=config.drain_timeout_seconds + 30,
        )

        _advance(config.state_file, state, "migrating")
        runner.run(
            [*config.compose_command, "--profile", "admin", "run", "--rm", "migrate"],
            timeout=None,
        )

        _advance(config.state_file, state, "starting_web")
        runner.run([*config.compose_command, "up", "--detach", "--no-deps", "web"], timeout=300)

        _advance(config.state_file, state, "checking_readiness")
        for attempt in range(config.readiness_attempts):
            if runner.ready(config.readiness_url, timeout=config.readiness_timeout_seconds):
                break
            if attempt + 1 < config.readiness_attempts:
                sleeper(config.readiness_interval_seconds)
        else:
            raise DeploymentError("new web process did not pass readiness checks")

        _advance(config.state_file, state, "releasing_workers")
        runner.run([*config.compose_command, "up", "--detach", "worker"], timeout=300)
        _advance(config.state_file, state, "released")
    except BaseException:
        _advance(config.state_file, state, "failed")
        raise
    return DeployResult("released", rollback_eligible, config.state_file)


def _advance(path: Path, state: dict[str, object], status: str) -> None:
    state["status"] = status
    state["updated_at"] = datetime.now(UTC).isoformat()
    _write_state(path, state)


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


class SubprocessExecutor:
    def run(self, command: list[str], *, timeout: float | None = None) -> None:
        subprocess.run(command, check=True, timeout=timeout)

    def ready(self, url: str, *, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.status == 200
        except OSError:
            return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--confirm-production", required=True)
    parser.add_argument("--compose-command", type=_command, default=("docker", "compose"))
    parser.add_argument("--backup-command", type=_command, required=True)
    parser.add_argument("--readiness-url", required=True)
    parser.add_argument("--drain-timeout", type=int, default=300)
    parser.add_argument("--readiness-timeout", type=float, default=5)
    parser.add_argument("--readiness-attempts", type=int, default=30)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--previous-image")
    parser.add_argument("--migration-rollback-revision")
    arguments = parser.parse_args()
    result = deploy(
        DeployConfig(
            environment="production",
            hostname=arguments.hostname,
            confirmation=arguments.confirm_production,
            compose_command=arguments.compose_command,
            backup_command=arguments.backup_command,
            readiness_url=arguments.readiness_url,
            drain_timeout_seconds=arguments.drain_timeout,
            readiness_timeout_seconds=arguments.readiness_timeout,
            readiness_attempts=arguments.readiness_attempts,
            state_file=arguments.state_file,
            previous_image=arguments.previous_image,
            migration_rollback_revision=arguments.migration_rollback_revision,
        )
    )
    print(json.dumps(asdict(result), default=str, sort_keys=True))


if __name__ == "__main__":
    main()
