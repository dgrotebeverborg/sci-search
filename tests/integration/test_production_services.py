from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.identity import ExternalIdentity, IdentityProfile, provision_user
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.production_services import (
    DatabaseProjectService,
    DatabaseResearchApiService,
    DatabaseSessionService,
)
from sci_search.infrastructure.repositories import SqlUnitOfWork
from sci_search.infrastructure.research_execution import ProductionResearchStage
from sci_search.infrastructure.tables import (
    ArtifactRow,
    DocumentRow,
    EvidenceRow,
    ProjectDocumentGrantRow,
)
from sci_search.worker import CancellationToken, StageInvocation
from tests.integration.test_migrations import DATABASE_URL, _configuration

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)


@pytest.fixture
def database() -> Database:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        yield database
    finally:
        database.dispose()


def test_database_session_and_project_services_survive_recomposition(database: Database) -> None:
    with database.transaction() as session:
        provisioned = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "persistent-user"),
            IdentityProfile(email="profile-only@example.test"),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    first_sessions = DatabaseSessionService(database, clock=lambda: NOW)
    issued = first_sessions.create(provisioned.user.id)

    recomposed_sessions = DatabaseSessionService(database, clock=lambda: NOW)
    assert recomposed_sessions.authenticate(issued.token).user_id == provisioned.user.id

    projects = DatabaseProjectService(database, clock=lambda: NOW)
    created = projects.create(
        provisioned.user.id,
        provisioned.workspace.id,
        "Persistent project",
        True,
    )
    recomposed_projects = DatabaseProjectService(database, clock=lambda: NOW)
    assert recomposed_projects.get(provisioned.user.id, created.id).name == "Persistent project"
    assert recomposed_projects.list_for_user(provisioned.user.id) == [created]


def test_research_run_is_idempotent_durable_and_queued(database: Database) -> None:
    with database.transaction() as session:
        provisioned = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "research-user"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        provisioned.user.id, provisioned.workspace.id, "Durable research", True
    )

    class UnusedBlobs:
        pass

    class Queue:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def enqueue(self, job_id: str, stage_name: str) -> None:
            self.messages.append((job_id, stage_name))

    queue = Queue()
    service = DatabaseResearchApiService(
        database,
        UnusedBlobs(),
        queue,
        clock=lambda: NOW,  # type: ignore[arg-type]
    )
    first = service.start_run(
        provisioned.user.id,
        project.id,
        question="How does grazing affect shrub regeneration?",
        review_depth="research",
        idempotency_key="request-1",
    )
    repeated = service.start_run(
        provisioned.user.id,
        project.id,
        question="How does grazing affect shrub regeneration?",
        review_depth="research",
        idempotency_key="request-1",
    )

    assert repeated.id == first.id
    assert first.status == "queued"
    assert (
        DatabaseResearchApiService(
            database,
            UnusedBlobs(),
            Queue(),
            clock=lambda: NOW,  # type: ignore[arg-type]
        ).get_run(provisioned.user.id, project.id, first.id)
        == first
    )
    assert queue.messages[0][1] == "research"


def test_production_research_stage_publishes_exact_evidence_and_artifacts_once(
    database: Database, tmp_path: Path
) -> None:
    with database.transaction() as session:
        provisioned = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "worker-user"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        provisioned.user.id, provisioned.workspace.id, "Worker project", True
    )

    class Queue:
        def enqueue(self, job_id: str, stage_name: str) -> None:
            del job_id, stage_name

    blobs = FilesystemBlobStore(tmp_path / "blobs")
    run = DatabaseResearchApiService(database, blobs, Queue(), clock=lambda: NOW).start_run(
        provisioned.user.id,
        project.id,
        question="How does grazing affect shrub regeneration?",
        review_depth="focused",
        idempotency_key="worker-run",
    )

    class Manager:
        def __init__(self, root: Path) -> None:
            self.root = root

        def run_sync(self, question: str, *, limits) -> dict:
            del limits
            corpus = self.root / "internal" / "corpus"
            (corpus / "papers").mkdir(parents=True)
            text = "Results\nGoat grazing reduced shrub seedling regeneration in the field plots."
            (corpus / "papers" / "study.txt").write_text(text, encoding="utf-8")
            (corpus / "manifest.json").write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "id": "publication:goat",
                                "title": "Grazing and shrub regeneration",
                                "doi": "10.0000/goat",
                                "path": "papers/study.txt",
                                "content_type": "text/plain",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return {
                "run_id": "internal",
                "status": "complete",
                "question": question,
                "result": {
                    "evidence": [
                        {
                            "publication_id": "publication:goat",
                            "statement": "Goat grazing reduced shrub seedling regeneration.",
                            "passage": "Goat grazing reduced shrub seedling regeneration in the field plots.",
                            "section": "Results",
                            "extraction_method": "extractive_scientific_evidence_v1",
                            "validation_checks": [{"name": "exact_source", "status": "passed"}],
                        }
                    ]
                },
            }

        def download_literature_review(self, run_id: str, output_format: str = "html"):
            del run_id, output_format
            return SimpleNamespace(content_type="application/pdf", body=b"%PDF-review")

        def download_research_package(self, run_id: str):
            del run_id
            return SimpleNamespace(content_type="application/zip", body=b"PK-package")

    stage = ProductionResearchStage(database, blobs, manager_factory=lambda root: Manager(root))
    invocation = StageInvocation(
        {
            "question": "How does grazing affect shrub regeneration?",
            "review_depth": "focused",
            "project_id": project.id,
            "run_id": run.id,
        },
        CancellationToken(lambda: False),
    )
    first = stage(invocation)
    repeated = stage(invocation)

    assert first.complete is True
    assert repeated.complete is True
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(DocumentRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectDocumentGrantRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceRow)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRow)) == 3
        evidence = session.scalar(select(EvidenceRow))
        assert evidence is not None
        assert evidence.source_passage == (
            "Goat grazing reduced shrub seedling regeneration in the field plots."
        )
