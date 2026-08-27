from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.authorization import ResourceNotFound
from sci_search.application.blobs import BlobRef
from sci_search.application.identity import ExternalIdentity, IdentityProfile, provision_user
from sci_search.application.projects import Project
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.repositories import SqlResearchRepository, SqlUnitOfWork
from sci_search.infrastructure.tables import (
    ArtifactRow,
    AuditEventRow,
    DocumentRow,
    EvidenceRow,
    ProjectDocumentGrantRow,
    PublicationDocumentRow,
    ResearchRunRow,
    ReviewRevisionRow,
    RiskOfBiasRecordRow,
    RiskOfBiasRevisionRow,
    RunDocumentRow,
    ValidationCheckRow,
)
from tests.integration.test_migrations import DATABASE_URL, _configuration

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


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


def _project(database: Database, subject: str) -> tuple[str, str]:
    with database.transaction() as session:
        repositories = SqlUnitOfWork(session)
        owner = provision_user(
            ExternalIdentity("https://connect.surfconext.nl", subject),
            IdentityProfile(email=f"{subject}@example.test"),
            repositories.provisioning,
            clock=lambda: NOW,
        )
        project = Project(
            str(uuid4()), owner.workspace.id, f"{subject} project", owner.user.id, True, NOW
        )
        repositories.projects.add_project(project)
        return project.id, owner.user.id


def test_one_digest_can_be_granted_and_revoked_per_project(database: Database) -> None:
    alice_project, _ = _project(database, "alice")
    bob_project, _ = _project(database, "bob")
    blob = BlobRef("a" * 64, 1234, "application/pdf", f"objects/aa/aa/{'a' * 64}")

    with database.transaction() as session:
        research = SqlResearchRepository(session)
        alice_document = research.grant_document(
            alice_project,
            canonical_publication_key="doi:10.1234/example",
            title="Shared paper",
            blob=blob,
        )
        bob_document = research.grant_document(
            bob_project,
            canonical_publication_key="doi:10.1234/example",
            title="Shared paper",
            blob=blob,
        )

    assert alice_document == bob_document
    with database.transaction() as session:
        research = SqlResearchRepository(session)
        assert research.resolve_blob_key(alice_project, alice_document) == blob.key
        assert research.resolve_blob_key(bob_project, bob_document) == blob.key
        research.revoke_document(alice_project, alice_document, revoked_at=NOW)

    with database.transaction() as session:
        research = SqlResearchRepository(session)
        with pytest.raises(ResourceNotFound):
            research.resolve_blob_key(alice_project, alice_document)
        assert research.resolve_blob_key(bob_project, bob_document) == blob.key
        assert session.scalar(select(func.count()).select_from(DocumentRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectDocumentGrantRow)) == 2


def test_optimistic_review_conflict_preserves_attempt_audits_without_overwrite(
    database: Database,
) -> None:
    project_id, reviewer_id = _project(database, "reviewer")
    blob = BlobRef("b" * 64, 500, "application/pdf", f"objects/bb/bb/{'b' * 64}")
    with database.transaction() as session:
        research = SqlResearchRepository(session)
        document_id = research.grant_document(
            project_id,
            canonical_publication_key="doi:10.9999/review",
            title="Evidence paper",
            blob=blob,
        )
        evidence_id = research.add_evidence(
            project_id,
            document_id=document_id,
            statement="The measured value is 70%.",
            source_passage="Round-trip efficiency was measured as 70%.",
            section="Results",
            page=7,
            extraction_method="manual-test",
            created_at=NOW,
        )

    with database.transaction() as session:
        accepted = SqlResearchRepository(session).try_review(
            project_id,
            evidence_id,
            reviewer_user_id=reviewer_id,
            expected_version=1,
            decision="accepted",
            note="Exact source match",
            reviewed_at=NOW,
        )
    with database.transaction() as session:
        conflicted = SqlResearchRepository(session).try_review(
            project_id,
            evidence_id,
            reviewer_user_id=reviewer_id,
            expected_version=1,
            decision="rejected",
            note="Stale competing review",
            reviewed_at=NOW,
        )

    assert accepted is True
    assert conflicted is False
    with database.transaction() as session:
        evidence = session.get(EvidenceRow, UUID(evidence_id))
        assert evidence is not None
        assert evidence.version == 2
        assert session.scalar(select(func.count()).select_from(ReviewRevisionRow)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 2
        actions = set(session.scalars(select(AuditEventRow.action)).all())
        assert actions == {"evidence.review_accepted", "evidence.review_conflict"}


def test_run_validation_and_artifact_records_stay_inside_project(database: Database) -> None:
    project_id, researcher_id = _project(database, "researcher")
    other_project_id, _ = _project(database, "outsider")
    blob = BlobRef("c" * 64, 700, "application/pdf", f"objects/cc/cc/{'c' * 64}")

    with database.transaction() as session:
        research = SqlResearchRepository(session)
        document_id = research.grant_document(
            project_id,
            canonical_publication_key="doi:10.9999/scoped",
            title="Scoped paper",
            blob=blob,
        )
        run_id = research.create_run(
            project_id,
            created_by_user_id=researcher_id,
            question="What does this paper establish?",
            configuration={"profile": "generic"},
            created_at=NOW,
        )
        research.link_run_document(project_id, run_id, document_id, relation="included")
        evidence_id = research.add_evidence(
            project_id,
            document_id=document_id,
            run_id=run_id,
            statement="A supported statement.",
            source_passage="The exact supporting source passage.",
            section="Results",
            page=3,
            extraction_method="manual-test",
            created_at=NOW,
        )
        research.add_validation_check(
            project_id,
            evidence_id,
            check_name="source_grounding",
            status="passed",
            details={"quote_exact": True},
            created_at=NOW,
        )
        research.add_artifact(
            project_id,
            run_id=run_id,
            kind="literature_review_pdf",
            blob_key="objects/reports/report-digest",
            input_fingerprint="fingerprint-v1",
            generator_version="report-v1",
            created_at=NOW,
        )

    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ResearchRunRow)) == 1
        assert session.scalar(select(func.count()).select_from(RunDocumentRow)) == 1
        assert session.scalar(select(func.count()).select_from(ValidationCheckRow)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRow)) == 1
        research = SqlResearchRepository(session)
        with pytest.raises(ResourceNotFound):
            research.link_run_document(other_project_id, run_id, document_id, relation="included")
        with pytest.raises(ResourceNotFound):
            research.add_validation_check(
                other_project_id,
                evidence_id,
                check_name="source_grounding",
                status="passed",
                details={},
                created_at=NOW,
            )


def test_risk_of_bias_revisions_are_grounded_and_optimistically_persisted(
    database: Database,
) -> None:
    project_id, reviewer_id = _project(database, "bias-reviewer")
    blob = BlobRef("d" * 64, 800, "application/pdf", f"objects/dd/dd/{'d' * 64}")
    with database.transaction() as session:
        research = SqlResearchRepository(session)
        document_id = research.grant_document(
            project_id,
            canonical_publication_key="doi:10.9999/risk-bias",
            title="Risk of bias paper",
            blob=blob,
        )
        publication_id = str(
            session.scalar(
                select(PublicationDocumentRow.publication_id).where(
                    PublicationDocumentRow.document_id == UUID(document_id)
                )
            )
        )
        evidence_id = research.add_evidence(
            project_id,
            document_id=document_id,
            statement="Season was not adjusted for.",
            source_passage="The analysis did not adjust for seasonal vegetation availability.",
            section="Methods",
            page=4,
            extraction_method="manual-test",
            created_at=NOW,
        )
        record_id = research.add_risk_of_bias(
            project_id,
            study_id=publication_id,
            reviewer_user_id=reviewer_id,
            tool="ROBINS-I",
            domain="confounding",
            judgment="some_concerns",
            rationale="Seasonal vegetation was not adjusted for.",
            source_evidence_ids=(evidence_id,),
            reviewed_at=NOW,
        )

    with database.transaction() as session:
        accepted = SqlResearchRepository(session).try_revise_risk_of_bias(
            project_id,
            record_id,
            reviewer_user_id=reviewer_id,
            expected_revision=1,
            judgment="high",
            rationale="The unadjusted seasonal factor directly affects the outcome.",
            source_evidence_ids=(evidence_id,),
            reviewed_at=NOW,
        )
    with database.transaction() as session:
        conflicted = SqlResearchRepository(session).try_revise_risk_of_bias(
            project_id,
            record_id,
            reviewer_user_id=reviewer_id,
            expected_revision=1,
            judgment="low",
            rationale="A stale competing assessment.",
            source_evidence_ids=(evidence_id,),
            reviewed_at=NOW,
        )

    assert accepted is True
    assert conflicted is False
    with database.transaction() as session:
        record = session.get(RiskOfBiasRecordRow, UUID(record_id))
        assert record is not None
        assert record.current_revision == 2
        assert session.scalar(select(func.count()).select_from(RiskOfBiasRevisionRow)) == 2
