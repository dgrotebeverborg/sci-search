#!/usr/bin/env python3
"""Exercise production persistence with two users and ten concurrent sessions."""

from __future__ import annotations

import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sci_search.application.identity import (
    ExternalIdentity,
    IdentityProfile,
    provision_user,
)
from sci_search.application.quotas import JobQuotaLimits, QuotaExceeded
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.jobs import SqlJobRepository
from sci_search.infrastructure.production_services import (
    DatabaseProjectService,
    DatabaseSessionService,
)
from sci_search.infrastructure.repositories import SqlUnitOfWork
from sci_search.infrastructure.settings import ProductionSettings

SESSION_COUNT = 10
JOBS_PER_USER = 5


def _get_session(base_url: str, token: str) -> tuple[int, str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/session",
        headers={"Cookie": f"sci_search_session={token}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        payload = json.loads(response.read())
        return response.status, str(payload["user_id"])


def main() -> int:
    settings = ProductionSettings.from_environment()
    database = Database(settings.database_url)

    def clock() -> datetime:
        return datetime.now(UTC)

    session_service = DatabaseSessionService(database, clock=clock)
    project_service = DatabaseProjectService(database, clock=clock)
    issued: list[tuple[str, str]] = []
    try:
        users = []
        for number in (1, 2):
            with database.transaction() as session:
                provisioned = provision_user(
                    ExternalIdentity(settings.oidc_issuer, f"program7-smoke-user-{number}"),
                    IdentityProfile(
                        email=f"researcher-{number}@mit.example",
                        display_name=f"MIT smoke researcher {number}",
                    ),
                    SqlUnitOfWork(session).provisioning,
                    clock,
                )
            projects = project_service.list_for_user(provisioned.user.id)
            project = next(
                (item for item in projects if item.name == "Program 7 load smoke"),
                None,
            )
            if project is None:
                project = project_service.create(
                    provisioned.user.id,
                    provisioned.workspace.id,
                    "Program 7 load smoke",
                    True,
                )
            users.append((provisioned.user.id, project.id))

        for user_id, _project_id in users:
            for _ in range(SESSION_COUNT // len(users)):
                issued.append((user_id, session_service.create(user_id).token))

        base_url = os.environ.get("SCI_SEARCH_SMOKE_BASE_URL", "http://127.0.0.1:8000")
        with ThreadPoolExecutor(max_workers=SESSION_COUNT) as executor:
            responses = list(executor.map(lambda item: _get_session(base_url, item[1]), issued))
        if any(status != 200 for status, _user_id in responses):
            raise RuntimeError("a concurrent session request failed")
        expected_users = sorted(user_id for user_id, _token in issued)
        if sorted(user_id for _status, user_id in responses) != expected_users:
            raise RuntimeError("a concurrent session resolved to the wrong user")

        limits = JobQuotaLimits(
            global_active=10,
            global_queued=SESSION_COUNT,
            workspace_active=5,
            workspace_queued=JOBS_PER_USER,
            user_active=5,
            user_queued=JOBS_PER_USER,
        )
        jobs = []
        with database.transaction() as session:
            repository = SqlJobRepository(session)
            for user_number, (user_id, project_id) in enumerate(users, start=1):
                for job_number in range(1, JOBS_PER_USER + 1):
                    jobs.append(
                        repository.create(
                            project_id,
                            created_by_user_id=user_id,
                            idempotency_key=f"program7-smoke-{user_number}-{job_number}",
                            first_stage="research",
                            input_payload={"smoke": True},
                            created_at=clock(),
                            quota_limits=limits,
                        )
                    )
            try:
                repository.create(
                    users[0][1],
                    created_by_user_id=users[0][0],
                    idempotency_key="program7-smoke-over-limit",
                    first_stage="research",
                    input_payload={"smoke": True},
                    created_at=clock(),
                    quota_limits=limits,
                )
            except QuotaExceeded:
                quota_enforced = True
            else:
                quota_enforced = False
        if not quota_enforced:
            raise RuntimeError("the bounded job quota accepted an eleventh queued job")

        print(
            json.dumps(
                {
                    "users": len(users),
                    "concurrent_sessions": len(responses),
                    "queued_jobs": len(jobs),
                    "quota_enforced": quota_enforced,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        for _user_id, token in issued:
            session_service.revoke(token)
        database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
