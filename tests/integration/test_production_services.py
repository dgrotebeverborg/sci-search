from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic import command
from pypdf import PdfWriter
from sqlalchemy import func, select

from sci_search.application.authorization import ResourceNotFound
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


def test_unauthorized_production_upload_does_not_write_blob(database: Database) -> None:
    with database.transaction() as session:
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "upload-owner"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
        unrelated = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "upload-unrelated"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        owner.user.id, owner.workspace.id, "Private uploads", True
    )
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = BytesIO()
    writer.write(pdf)
    blobs = Mock()
    service = DatabaseResearchApiService(database, blobs, Mock(), clock=lambda: NOW)

    with pytest.raises(ResourceNotFound):
        service.upload_document(
            unrelated.user.id,
            project.id,
            run_id="00000000-0000-0000-0000-000000000001",
            candidate_id="unauthorized",
            filename="paper.pdf",
            content_base64=base64.b64encode(pdf.getvalue()).decode("ascii"),
            authorization_confirmed=True,
        )

    blobs.put.assert_not_called()


def test_upload_to_missing_run_does_not_write_blob(database: Database) -> None:
    with database.transaction() as session:
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "missing-run-owner"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        owner.user.id, owner.workspace.id, "Upload validation", True
    )
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = BytesIO()
    writer.write(pdf)
    blobs = Mock()
    service = DatabaseResearchApiService(database, blobs, Mock(), clock=lambda: NOW)

    with pytest.raises(ResourceNotFound):
        service.upload_document(
            owner.user.id,
            project.id,
            run_id="00000000-0000-0000-0000-000000000001",
            candidate_id="missing-run",
            filename="paper.pdf",
            content_base64=base64.b64encode(pdf.getvalue()).decode("ascii"),
            authorization_confirmed=True,
        )

    blobs.put.assert_not_called()


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
        assert session.scalar(select(func.count()).select_from(ArtifactRow)) == 4
        evidence = session.scalar(select(EvidenceRow))
        assert evidence is not None
        assert evidence.source_passage == (
            "Goat grazing reduced shrub seedling regeneration in the field plots."
        )


def test_saved_dashboard_feedback_sequences_revisions_and_project_isolation(database, tmp_path):
    from sci_search.application.research_api import ResourceVersionConflict
    from sci_search.infrastructure.dashboard_repository import DashboardRepository
    from sci_search.infrastructure.feedback_repository import FeedbackRepository
    from sci_search.infrastructure.tables import ArticleFeedbackRow, DashboardRevisionRow

    with database.transaction() as session:
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "dash-owner"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
        other = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "dash-other"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        owner.user.id, owner.workspace.id, "Saved dashboards", True
    )
    queue = Mock()
    api = DatabaseResearchApiService(
        database, FilesystemBlobStore(tmp_path / "blobs"), queue, clock=lambda: NOW
    )
    run = api.start_run(
        owner.user.id,
        project.id,
        question="Why do shrubs recover?",
        review_depth="focused",
        idempotency_key="dashboard",
    )
    with database.transaction() as session:
        DashboardRepository(session).publish(
            project.id,
            run.id,
            {"candidate_ids": ["paper-a"], "blocks": [{"id": "answer", "data": "original"}]},
            feedback_sequence=0,
            created_at=NOW,
        )
    assert api.list_runs(owner.user.id, project.id)["items"][0]["run_id"] == run.id
    assert api.get_dashboard(owner.user.id, project.id, run.id)["blocks"][0]["data"] == "original"
    with pytest.raises(ResourceNotFound):
        api.get_dashboard(other.user.id, project.id, run.id)
    event = api.record_article_feedback(
        owner.user.id,
        project.id,
        run.id,
        "paper-a",
        decision="exclude",
        reason="Wrong population",
        expected_sequence=0,
        idempotency_key="exclude",
    )
    duplicate = api.record_article_feedback(
        owner.user.id,
        project.id,
        run.id,
        "paper-a",
        decision="exclude",
        reason="Wrong population",
        expected_sequence=0,
        idempotency_key="exclude",
    )
    assert event == duplicate
    with pytest.raises(ResourceVersionConflict):
        api.record_article_feedback(
            owner.user.id,
            project.id,
            run.id,
            "paper-a",
            decision="include",
            reason="",
            expected_sequence=0,
            idempotency_key="stale",
        )
    assert (
        api.get_dashboard(owner.user.id, project.id, run.id)["effective_decisions"]["paper-a"][
            "decision"
        ]
        == "exclude"
    )
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ArticleFeedbackRow)) == 1
        repo = DashboardRepository(session)
        assert (
            repo.publish(project.id, run.id, {"blocks": []}, feedback_sequence=0, created_at=NOW)
            is None
        )
        assert (
            repo.publish(
                project.id,
                run.id,
                {"candidate_ids": ["paper-a"], "blocks": [{"id": "answer", "data": "rebuilt"}]},
                feedback_sequence=1,
                created_at=NOW,
            )
            == 2
        )
    assert (
        api.get_dashboard(owner.user.id, project.id, run.id, revision=1)["blocks"][0]["data"]
        == "original"
    )
    assert api.get_dashboard(owner.user.id, project.id, run.id)["blocks"][0]["data"] == "rebuilt"
    api.record_article_feedback(
        owner.user.id,
        project.id,
        run.id,
        "paper-a",
        decision="reset",
        reason="",
        expected_sequence=1,
        idempotency_key="reset",
    )
    with database.transaction() as session:
        assert FeedbackRepository(session).effective(run.id, 2) == {}
        assert session.scalar(select(func.count()).select_from(DashboardRevisionRow)) == 2


def test_feedback_rebuild_uses_retained_sources_and_preserves_previous_revision(database, tmp_path):
    from sci_search.fulltext_acquisition import AcquisitionOutcome
    from sci_search.infrastructure.dashboard_rebuild import ProductionDashboardRebuildStage
    from sci_search.research_runs import ResearchRunManager
    from tests.test_online_discovery import QUESTION, FakeProvider

    with database.transaction() as session:
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "rebuild-owner"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        owner.user.id, owner.workspace.id, "Rebuild", True
    )
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    api = DatabaseResearchApiService(database, blobs, Mock(), clock=lambda: NOW)
    run = api.start_run(
        owner.user.id,
        project.id,
        question=QUESTION,
        review_depth="focused",
        idempotency_key="real-rebuild",
    )

    def acquire(item, corpus):
        (corpus / "papers").mkdir(parents=True, exist_ok=True)
        text = "## Results\n\nGoat foraging behaviour changed with vegetation structure: goats selected taller woody plant species during the dry season.\n"
        (corpus / "papers" / "relevant.txt").write_text(text)
        return AcquisitionOutcome(
            item.id,
            "acquired",
            "fixture",
            "papers/relevant.txt",
            "text/plain",
            len(text),
            len(text),
        )

    stage = ProductionResearchStage(
        database,
        blobs,
        manager_factory=lambda root: ResearchRunManager(
            root, providers=(FakeProvider(),), acquirer=acquire, openalex_api_key="test-key"
        ),
    )
    stage(
        StageInvocation(
            {
                "question": QUESTION,
                "review_depth": "focused",
                "project_id": project.id,
                "run_id": run.id,
            },
            CancellationToken(lambda: False),
        )
    )
    first = api.get_dashboard(owner.user.id, project.id, run.id)
    source_evidence = next(b["data"] for b in first["blocks"] if b["id"] == "evidence")[0]
    review = first["evidence_reviews"][source_evidence["id"]]
    api.review_evidence(
        owner.user.id,
        project.id,
        review["id"],
        expected_version=review["version"],
        decision="rejected",
        note="Check context",
    )
    refreshed = api.get_dashboard(owner.user.id, project.id, run.id)
    assert refreshed["evidence_reviews"][source_evidence["id"]]["review_decision"] == "rejected"
    assert refreshed["evidence_reviews"][source_evidence["id"]]["version"] == 2
    assert (
        api.get_dashboard(owner.user.id, project.id, run.id, revision=1).get("evidence_reviews", {})
        == {}
    )
    assert first["documents"]["publication:relevant"]["url"].startswith("/api/v1/")
    api.record_article_feedback(
        owner.user.id,
        project.id,
        run.id,
        "publication:relevant",
        decision="exclude",
        reason="Wrong population",
        expected_sequence=0,
        idempotency_key="exclude",
    )
    rebuild = ProductionDashboardRebuildStage(database, blobs)
    rebuilt = rebuild(
        StageInvocation(
            {"project_id": project.id, "run_id": run.id, "feedback_sequence": 1},
            CancellationToken(lambda: False),
        )
    )
    assert rebuilt.output["revision"] == 2
    second = api.get_dashboard(owner.user.id, project.id, run.id)
    assert next(b["data"] for b in second["blocks"] if b["id"] == "evidence") == []
    from sci_search.application.research_api import ResourceVersionConflict

    with pytest.raises(ResourceVersionConflict):
        api.review_evidence(
            owner.user.id,
            project.id,
            review["id"],
            expected_version=2,
            decision="accepted",
            note="",
        )

    assert (
        api.get_dashboard(owner.user.id, project.id, run.id, revision=1)["blocks"]
        == first["blocks"]
    )
    api.record_article_feedback(
        owner.user.id,
        project.id,
        run.id,
        "publication:relevant",
        decision="reset",
        reason="",
        expected_sequence=1,
        idempotency_key="reset",
    )
    restored = rebuild(
        StageInvocation(
            {"project_id": project.id, "run_id": run.id, "feedback_sequence": 2},
            CancellationToken(lambda: False),
        )
    )
    assert restored.output["revision"] == 3
    assert next(
        b["data"]
        for b in api.get_dashboard(owner.user.id, project.id, run.id)["blocks"]
        if b["id"] == "evidence"
    )


def test_legacy_result_recovers_dashboard_without_rediscovery(database, tmp_path):
    from sci_search.infrastructure.repositories import SqlResearchRepository

    with database.transaction() as session:
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "legacy-dash"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    project = DatabaseProjectService(database, clock=lambda: NOW).create(
        owner.user.id, owner.workspace.id, "Legacy", True
    )
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    api = DatabaseResearchApiService(database, blobs, Mock(), clock=lambda: NOW)
    run = api.start_run(
        owner.user.id,
        project.id,
        question="Legacy research?",
        review_depth="focused",
        idempotency_key="legacy",
    )
    body = json.dumps(
        {
            "candidates": [{"id": "p"}],
            "result": {
                "question": "Legacy research?",
                "evidence": [
                    {"statement": "Retained exact claim", "passage": "Retained exact claim"}
                ],
            },
        }
    ).encode()
    blob = blobs.put(BytesIO(body), len(body), content_type="application/json")
    with database.transaction() as session:
        SqlResearchRepository(session).add_artifact(
            project.id,
            run_id=run.id,
            kind="research-run.json",
            blob_key=blob.key,
            input_fingerprint="legacy",
            generator_version="old",
            created_at=NOW,
        )
    recovered = api.get_dashboard(owner.user.id, project.id, run.id)
    assert recovered["question"] == "Legacy research?"
    assert recovered["rebuild_available"] is False
    assert len(api.list_revisions(owner.user.id, project.id, run.id)["items"]) == 1
    with pytest.raises(ValueError, match="source ledger"):
        api.record_article_feedback(
            owner.user.id,
            project.id,
            run.id,
            "p",
            decision="exclude",
            reason="",
            expected_sequence=0,
            idempotency_key="blocked",
        )


def test_revoked_review_permission_prevents_dashboard_publication(database, tmp_path):
    from sci_search.application.projects import ProjectRole
    from sci_search.infrastructure.dashboard_repository import DashboardRepository
    from sci_search.infrastructure.tables import ArticleFeedbackRow

    with database.transaction() as session:
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "auth-owner"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
        reviewer = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", "auth-reviewer"),
            IdentityProfile(),
            SqlUnitOfWork(session).provisioning,
            clock=lambda: NOW,
        )
    projects = DatabaseProjectService(database, clock=lambda: NOW)
    project = projects.create(owner.user.id, owner.workspace.id, "Review authorization", True)
    projects.add_member(owner.user.id, project.id, reviewer.user.id, ProjectRole.REVIEWER)
    api = DatabaseResearchApiService(
        database, FilesystemBlobStore(tmp_path / "blobs"), Mock(), clock=lambda: NOW
    )
    run = api.start_run(
        owner.user.id,
        project.id,
        question="Which population?",
        review_depth="focused",
        idempotency_key="auth",
    )
    with database.transaction() as session:
        DashboardRepository(session).publish(
            project.id,
            run.id,
            {"candidate_ids": ["p"], "source_archive_key": "sha256/sources", "blocks": []},
            feedback_sequence=0,
            created_at=NOW,
        )
    api.record_article_feedback(
        reviewer.user.id,
        project.id,
        run.id,
        "p",
        decision="exclude",
        reason="Wrong population",
        expected_sequence=0,
        idempotency_key="correction",
    )
    with database.transaction() as session:
        event = session.scalar(select(ArticleFeedbackRow))
        assert event.reviewed_revision == 1
        assert event.context_json["question"] == "Which population?"
        assert event.source_fingerprint == "sha256/sources"
    from sci_search.application.research_api import ResourceVersionConflict

    with pytest.raises(ResourceVersionConflict):
        api.record_article_feedback(
            reviewer.user.id,
            project.id,
            run.id,
            "p",
            decision="include",
            reason="",
            expected_sequence=1,
            idempotency_key="stale-view",
            reviewed_revision=99,
        )
    projects.change_member_role(owner.user.id, project.id, reviewer.user.id, ProjectRole.VIEWER)
    with database.transaction() as session, pytest.raises(ResourceNotFound):
        DashboardRepository(session).publish(
            project.id, run.id, {"blocks": []}, feedback_sequence=1, created_at=NOW
        )
    assert api.get_dashboard(owner.user.id, project.id, run.id)["revision"] == 1
