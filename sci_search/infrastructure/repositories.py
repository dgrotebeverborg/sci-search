"""SQLAlchemy repository implementations for Program 2 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as OrmSession

from sci_search.application.authorization import ResourceNotFound
from sci_search.application.blobs import BlobRef
from sci_search.application.identity import (
    ExternalIdentity,
    IdentityRepository,
    ProvisioningRepositories,
    User,
)
from sci_search.application.projects import (
    Membership,
    Project,
    ProjectAuditRecord,
    ProjectRepository,
    ProjectRole,
    Workspace,
)
from sci_search.application.sessions import Session, SessionRepository
from sci_search.infrastructure.jobs import SqlJobRepository
from sci_search.infrastructure.tables import (
    ArtifactRow,
    AuditEventRow,
    DocumentRow,
    EvidenceRow,
    ExternalIdentityRow,
    ProjectDocumentGrantRow,
    ProjectMembershipRow,
    ProjectRow,
    PublicationDocumentRow,
    PublicationRow,
    ResearchRunRow,
    ReviewRevisionRow,
    RiskOfBiasRecordRow,
    RiskOfBiasRevisionRow,
    RunDocumentRow,
    SessionRow,
    UserRow,
    ValidationCheckRow,
    WorkspaceMembershipRow,
    WorkspaceRow,
)


class OptimisticConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("resource was modified by another transaction")


def _uuid(value: str) -> UUID:
    return UUID(value)


def _user(row: UserRow) -> User:
    return User(
        str(row.id),
        row.created_at,
        row.updated_at,
        row.email,
        row.display_name,
        row.affiliation,
        row.institution,
    )


def _workspace(row: WorkspaceRow) -> Workspace:
    return Workspace(
        str(row.id),
        row.name,
        str(row.owner_user_id),
        row.is_personal,
        row.created_at,
    )


def _project(row: ProjectRow) -> Project:
    return Project(
        str(row.id),
        str(row.workspace_id),
        row.name,
        str(row.owner_user_id),
        row.is_private,
        row.created_at,
        row.deleted_at,
    )


def _workspace_membership(row: WorkspaceMembershipRow) -> Membership:
    return Membership(
        str(row.id),
        str(row.user_id),
        ProjectRole(row.role),
        row.active,
        row.created_at,
        workspace_id=str(row.workspace_id),
    )


def _project_membership(row: ProjectMembershipRow) -> Membership:
    return Membership(
        str(row.id),
        str(row.user_id),
        ProjectRole(row.role),
        row.active,
        row.created_at,
        project_id=str(row.project_id),
    )


class SqlIdentityRepository(IdentityRepository):
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def user_for_identity(self, identity: ExternalIdentity) -> User | None:
        statement = (
            select(UserRow)
            .join(ExternalIdentityRow, ExternalIdentityRow.user_id == UserRow.id)
            .where(
                ExternalIdentityRow.issuer == identity.issuer,
                ExternalIdentityRow.subject == identity.subject,
            )
        )
        row = self._session.scalar(statement)
        return _user(row) if row is not None else None

    def add_user(self, user: User, identity: ExternalIdentity) -> None:
        user_row = UserRow(
            id=_uuid(user.id),
            email=user.email,
            display_name=user.display_name,
            affiliation=user.affiliation,
            institution=user.institution,
            created_at=user.created_at,
            updated_at=user.updated_at,
            version=1,
        )
        self._session.add(user_row)
        # These mappings intentionally avoid ORM relationships; flush the FK
        # parent explicitly so ordering never depends on mapper discovery.
        self._session.flush([user_row])
        self._session.add(
            ExternalIdentityRow(
                id=uuid4(),
                user_id=_uuid(user.id),
                issuer=identity.issuer,
                subject=identity.subject,
                created_at=user.created_at,
            )
        )

    def update_user(self, user: User) -> None:
        row = self._session.get(UserRow, _uuid(user.id))
        if row is None:
            raise KeyError("unknown user")
        row.email = user.email
        row.display_name = user.display_name
        row.affiliation = user.affiliation
        row.institution = user.institution
        row.updated_at = user.updated_at
        row.version += 1

    def list_users(self) -> list[User]:
        return [_user(row) for row in self._session.scalars(select(UserRow)).all()]


class SqlProjectRepository(ProjectRepository):
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def project_by_id(self, project_id: str) -> Project | None:
        row = self._session.get(ProjectRow, _uuid(project_id))
        return _project(row) if row is not None else None

    def personal_workspace_for(self, user_id: str) -> Workspace | None:
        row = self._session.scalar(
            select(WorkspaceRow).where(
                WorkspaceRow.owner_user_id == _uuid(user_id),
                WorkspaceRow.is_personal.is_(True),
            )
        )
        return _workspace(row) if row is not None else None

    def membership_for_workspace(self, workspace_id: str, user_id: str) -> Membership | None:
        row = self._session.scalar(
            select(WorkspaceMembershipRow).where(
                WorkspaceMembershipRow.workspace_id == _uuid(workspace_id),
                WorkspaceMembershipRow.user_id == _uuid(user_id),
            )
        )
        return _workspace_membership(row) if row is not None else None

    def membership_for_project(self, project_id: str, user_id: str) -> Membership | None:
        row = self._session.scalar(
            select(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == _uuid(project_id),
                ProjectMembershipRow.user_id == _uuid(user_id),
            )
        )
        return _project_membership(row) if row is not None else None

    def add_workspace(self, workspace: Workspace) -> None:
        row = WorkspaceRow(
            id=_uuid(workspace.id),
            name=workspace.name,
            owner_user_id=_uuid(workspace.owner_user_id),
            is_personal=workspace.is_personal,
            created_at=workspace.created_at,
            updated_at=workspace.created_at,
            version=1,
        )
        self._session.add(row)
        self._session.flush([row])

    def add_project(self, project: Project) -> None:
        row = ProjectRow(
            id=_uuid(project.id),
            workspace_id=_uuid(project.workspace_id),
            owner_user_id=_uuid(project.owner_user_id),
            name=project.name,
            is_private=project.is_private,
            created_at=project.created_at,
            updated_at=project.created_at,
            deleted_at=project.deleted_at,
            version=1,
        )
        self._session.add(row)
        self._session.flush([row])

    def add_membership(self, membership: Membership) -> None:
        values = {
            "id": _uuid(membership.id),
            "user_id": _uuid(membership.user_id),
            "role": membership.role.value,
            "active": membership.active,
            "created_at": membership.created_at,
            "updated_at": membership.created_at,
            "version": 1,
        }
        if membership.workspace_id is not None:
            self._session.add(
                WorkspaceMembershipRow(
                    workspace_id=_uuid(membership.workspace_id),
                    **values,
                )
            )
        elif membership.project_id is not None:
            self._session.add(
                ProjectMembershipRow(project_id=_uuid(membership.project_id), **values)
            )
        else:  # Membership validates this, but keep the persistence boundary defensive.
            raise ValueError("membership has no scope")

    def list_workspaces(self) -> list[Workspace]:
        self._session.flush()
        return [_workspace(row) for row in self._session.scalars(select(WorkspaceRow)).all()]

    def list_projects(self) -> list[Project]:
        self._session.flush()
        return [_project(row) for row in self._session.scalars(select(ProjectRow)).all()]

    def list_memberships(self) -> list[Membership]:
        self._session.flush()
        workspace_memberships = [
            _workspace_membership(row)
            for row in self._session.scalars(select(WorkspaceMembershipRow)).all()
        ]
        project_memberships = [
            _project_membership(row)
            for row in self._session.scalars(select(ProjectMembershipRow)).all()
        ]
        return workspace_memberships + project_memberships

    def update_project_membership_role(
        self,
        project_id: str,
        user_id: str,
        role: ProjectRole,
        *,
        expected_version: int,
    ) -> int:
        result = self._session.execute(
            update(ProjectMembershipRow)
            .where(
                ProjectMembershipRow.project_id == _uuid(project_id),
                ProjectMembershipRow.user_id == _uuid(user_id),
                ProjectMembershipRow.version == expected_version,
            )
            .values(
                role=role.value,
                version=expected_version + 1,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise OptimisticConflict
        return expected_version + 1

    def update_project(self, project: Project) -> None:
        row = self._session.get(ProjectRow, _uuid(project.id))
        if row is None:
            raise KeyError("unknown project")
        row.name = project.name
        row.is_private = project.is_private
        row.deleted_at = project.deleted_at
        row.version += 1

    def update_membership(self, membership: Membership) -> None:
        row: WorkspaceMembershipRow | ProjectMembershipRow | None
        if membership.workspace_id is not None:
            row = self._session.get(WorkspaceMembershipRow, _uuid(membership.id))
        else:
            row = self._session.get(ProjectMembershipRow, _uuid(membership.id))
        if row is None:
            raise KeyError("unknown membership")
        row.role = membership.role.value
        row.active = membership.active
        row.version += 1


def _session(row: SessionRow) -> Session:
    return Session(
        str(row.id),
        str(row.user_id),
        row.token_digest,
        row.created_at,
        row.last_seen_at,
        row.idle_expires_at,
        row.absolute_expires_at,
        row.revoked_at,
    )


class SqlSessionRepository(SessionRepository):
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def session_by_digest(self, token_digest: str) -> Session | None:
        row = self._session.scalar(
            select(SessionRow).where(SessionRow.token_digest == token_digest)
        )
        return _session(row) if row is not None else None

    def save_session(self, session: Session) -> None:
        row = self._session.get(SessionRow, _uuid(session.id))
        if row is None:
            self._session.add(
                SessionRow(
                    id=_uuid(session.id),
                    user_id=_uuid(session.user_id),
                    token_digest=session.token_digest,
                    created_at=session.created_at,
                    last_seen_at=session.last_seen_at,
                    idle_expires_at=session.idle_expires_at,
                    absolute_expires_at=session.absolute_expires_at,
                    revoked_at=session.revoked_at,
                    version=1,
                )
            )
            return
        row.last_seen_at = session.last_seen_at
        row.idle_expires_at = session.idle_expires_at
        row.absolute_expires_at = session.absolute_expires_at
        row.revoked_at = session.revoked_at
        row.version += 1

    def sessions_for_user(self, user_id: str) -> list[Session]:
        rows = self._session.scalars(
            select(SessionRow).where(SessionRow.user_id == _uuid(user_id))
        ).all()
        return [_session(row) for row in rows]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    occurred_at: datetime
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    actor_user_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None

    @classmethod
    def role_changed(
        cls,
        *,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
        occurred_at: datetime,
    ) -> AuditEvent:
        return cls(
            id=str(uuid4()),
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            project_id=project_id,
            action="project_membership.role_changed",
            entity_type="project_membership",
            entity_id=f"{project_id}:{subject_user_id}",
            payload={"subject_user_id": subject_user_id, "role": role.value},
        )


class SqlAuditRepository:
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(
            AuditEventRow(
                id=_uuid(event.id),
                occurred_at=event.occurred_at,
                actor_user_id=_uuid(event.actor_user_id) if event.actor_user_id else None,
                workspace_id=_uuid(event.workspace_id) if event.workspace_id else None,
                project_id=_uuid(event.project_id) if event.project_id else None,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=event.payload,
            )
        )


class SqlProjectAuditRepository:
    """Adapter from application project audit records to the shared audit table."""

    def __init__(self, session: OrmSession) -> None:
        self._audits = SqlAuditRepository(session)

    def add(self, event: ProjectAuditRecord) -> None:
        self._audits.add(
            AuditEvent(
                id=str(uuid4()),
                occurred_at=event.occurred_at,
                actor_user_id=event.actor_user_id,
                project_id=event.project_id,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=event.payload,
            )
        )


class SqlResearchRepository:
    """Project-scoped metadata for documents and provenance-bearing evidence."""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def grant_document(
        self,
        project_id: str,
        *,
        canonical_publication_key: str,
        title: str,
        blob: BlobRef,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        project_uuid = _uuid(project_id)
        if self._session.get(ProjectRow, project_uuid) is None:
            raise ResourceNotFound

        document = self._session.scalar(
            select(DocumentRow).where(DocumentRow.sha256 == blob.sha256)
        )
        if document is None:
            document = DocumentRow(
                id=uuid4(),
                sha256=blob.sha256,
                size=blob.size,
                content_type=blob.content_type,
                blob_key=blob.key,
            )
            self._session.add(document)
            self._session.flush([document])
        elif (
            document.size != blob.size
            or document.content_type != blob.content_type
            or document.blob_key != blob.key
        ):
            raise ValueError("blob metadata does not match the stored digest")

        publication = self._session.scalar(
            select(PublicationRow).where(PublicationRow.canonical_key == canonical_publication_key)
        )
        if publication is None:
            publication = PublicationRow(
                id=uuid4(),
                canonical_key=canonical_publication_key,
                title=title,
                metadata_json=metadata or {},
            )
            self._session.add(publication)
            self._session.flush([publication])

        link = self._session.scalar(
            select(PublicationDocumentRow).where(
                PublicationDocumentRow.publication_id == publication.id,
                PublicationDocumentRow.document_id == document.id,
            )
        )
        if link is None:
            self._session.add(
                PublicationDocumentRow(
                    id=uuid4(),
                    publication_id=publication.id,
                    document_id=document.id,
                )
            )

        grant = self._session.scalar(
            select(ProjectDocumentGrantRow).where(
                ProjectDocumentGrantRow.project_id == project_uuid,
                ProjectDocumentGrantRow.document_id == document.id,
            )
        )
        if grant is None:
            self._session.add(
                ProjectDocumentGrantRow(
                    id=uuid4(),
                    project_id=project_uuid,
                    document_id=document.id,
                    version=1,
                )
            )
        elif grant.revoked_at is not None:
            grant.revoked_at = None
            grant.version += 1
        return str(document.id)

    def resolve_blob_key(self, project_id: str, document_id: str) -> str:
        """Resolve only after an active project grant has been proven."""
        blob_key = self._session.scalar(
            select(DocumentRow.blob_key)
            .join(
                ProjectDocumentGrantRow,
                ProjectDocumentGrantRow.document_id == DocumentRow.id,
            )
            .where(
                ProjectDocumentGrantRow.project_id == _uuid(project_id),
                ProjectDocumentGrantRow.document_id == _uuid(document_id),
                ProjectDocumentGrantRow.revoked_at.is_(None),
            )
        )
        if blob_key is None:
            raise ResourceNotFound
        return blob_key

    def revoke_document(self, project_id: str, document_id: str, *, revoked_at: datetime) -> None:
        result = self._session.execute(
            update(ProjectDocumentGrantRow)
            .where(
                ProjectDocumentGrantRow.project_id == _uuid(project_id),
                ProjectDocumentGrantRow.document_id == _uuid(document_id),
                ProjectDocumentGrantRow.revoked_at.is_(None),
            )
            .values(
                revoked_at=revoked_at,
                version=ProjectDocumentGrantRow.version + 1,
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise ResourceNotFound

    def create_run(
        self,
        project_id: str,
        *,
        created_by_user_id: str,
        question: str,
        configuration: dict[str, Any],
        created_at: datetime,
        status: str = "created",
    ) -> str:
        project_uuid = _uuid(project_id)
        user_uuid = _uuid(created_by_user_id)
        if (
            self._session.get(ProjectRow, project_uuid) is None
            or self._session.get(UserRow, user_uuid) is None
        ):
            raise ResourceNotFound
        if not question.strip():
            raise ValueError("research question cannot be empty")
        run = ResearchRunRow(
            id=uuid4(),
            project_id=project_uuid,
            created_by_user_id=user_uuid,
            question=question,
            configuration_json=configuration,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            version=1,
        )
        self._session.add(run)
        self._session.flush([run])
        return str(run.id)

    def link_run_document(
        self,
        project_id: str,
        run_id: str,
        document_id: str,
        *,
        relation: str,
    ) -> str:
        run_uuid = self._require_run(project_id, run_id)
        self.resolve_blob_key(project_id, document_id)
        existing = self._session.scalar(
            select(RunDocumentRow).where(
                RunDocumentRow.run_id == run_uuid,
                RunDocumentRow.document_id == _uuid(document_id),
            )
        )
        if existing is not None:
            return str(existing.id)
        link = RunDocumentRow(
            id=uuid4(),
            run_id=run_uuid,
            document_id=_uuid(document_id),
            relation=relation,
        )
        self._session.add(link)
        self._session.flush([link])
        return str(link.id)

    def add_evidence(
        self,
        project_id: str,
        *,
        document_id: str,
        statement: str,
        source_passage: str,
        section: str | None,
        page: int | None,
        extraction_method: str,
        created_at: datetime,
        run_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        # Authorize the association before persisting scientific assertions.
        self.resolve_blob_key(project_id, document_id)
        run_uuid = self._require_run(project_id, run_id) if run_id else None
        if not statement.strip() or not source_passage.strip() or not extraction_method.strip():
            raise ValueError("evidence requires a statement, source passage, and extraction method")
        evidence = EvidenceRow(
            id=uuid4(),
            project_id=_uuid(project_id),
            document_id=_uuid(document_id),
            run_id=run_uuid,
            statement=statement,
            source_passage=source_passage,
            section=section,
            page=page,
            extraction_method=extraction_method,
            context_json=context or {},
            created_at=created_at,
            updated_at=created_at,
            version=1,
        )
        self._session.add(evidence)
        self._session.flush([evidence])
        return str(evidence.id)

    def add_validation_check(
        self,
        project_id: str,
        evidence_id: str,
        *,
        check_name: str,
        status: str,
        details: dict[str, Any],
        created_at: datetime,
    ) -> str:
        evidence_uuid = _uuid(evidence_id)
        evidence_exists = self._session.scalar(
            select(EvidenceRow.id).where(
                EvidenceRow.id == evidence_uuid,
                EvidenceRow.project_id == _uuid(project_id),
            )
        )
        if evidence_exists is None:
            raise ResourceNotFound
        check = ValidationCheckRow(
            id=uuid4(),
            evidence_id=evidence_uuid,
            check_name=check_name,
            status=status,
            details_json=details,
            created_at=created_at,
        )
        self._session.add(check)
        self._session.flush([check])
        return str(check.id)

    def add_artifact(
        self,
        project_id: str,
        *,
        run_id: str | None,
        kind: str,
        blob_key: str,
        input_fingerprint: str,
        generator_version: str,
        created_at: datetime,
        expires_at: datetime | None = None,
    ) -> str:
        project_uuid = _uuid(project_id)
        run_uuid = self._require_run(project_id, run_id) if run_id else None
        if run_uuid is None and self._session.get(ProjectRow, project_uuid) is None:
            raise ResourceNotFound
        artifact = ArtifactRow(
            id=uuid4(),
            project_id=project_uuid,
            run_id=run_uuid,
            kind=kind,
            blob_key=blob_key,
            input_fingerprint=input_fingerprint,
            generator_version=generator_version,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._session.add(artifact)
        self._session.flush([artifact])
        return str(artifact.id)

    def try_review(
        self,
        project_id: str,
        evidence_id: str,
        *,
        reviewer_user_id: str,
        expected_version: int,
        decision: str,
        note: str | None,
        reviewed_at: datetime,
    ) -> bool:
        result = self._session.execute(
            update(EvidenceRow)
            .where(
                EvidenceRow.id == _uuid(evidence_id),
                EvidenceRow.project_id == _uuid(project_id),
                EvidenceRow.version == expected_version,
            )
            .values(version=expected_version + 1, updated_at=reviewed_at)
        )
        accepted = result.rowcount == 1  # type: ignore[attr-defined]
        if accepted:
            revision = ReviewRevisionRow(
                id=uuid4(),
                evidence_id=_uuid(evidence_id),
                project_id=_uuid(project_id),
                reviewer_user_id=_uuid(reviewer_user_id),
                evidence_version=expected_version + 1,
                decision=decision,
                note=note,
                reviewed_at=reviewed_at,
            )
            self._session.add(revision)
            self._session.flush([revision])

        self._session.add(
            AuditEventRow(
                id=uuid4(),
                occurred_at=reviewed_at,
                actor_user_id=_uuid(reviewer_user_id),
                project_id=_uuid(project_id),
                action=("evidence.review_accepted" if accepted else "evidence.review_conflict"),
                entity_type="evidence",
                entity_id=evidence_id,
                payload={
                    "attempted_decision": decision,
                    "note": note,
                    "expected_version": expected_version,
                },
            )
        )
        return accepted

    def add_risk_of_bias(
        self,
        project_id: str,
        *,
        study_id: str,
        reviewer_user_id: str,
        tool: str,
        domain: str,
        judgment: str,
        rationale: str | None,
        source_evidence_ids: tuple[str, ...],
        reviewed_at: datetime,
    ) -> str:
        self._validate_risk_of_bias_inputs(
            project_id,
            study_id=study_id,
            judgment=judgment,
            rationale=rationale,
            source_evidence_ids=source_evidence_ids,
        )
        record = RiskOfBiasRecordRow(
            id=uuid4(),
            project_id=_uuid(project_id),
            study_id=_uuid(study_id),
            tool=tool,
            domain=domain,
            current_revision=1,
        )
        revision = RiskOfBiasRevisionRow(
            id=uuid4(),
            risk_of_bias_id=record.id,
            revision=1,
            judgment=judgment,
            rationale=rationale,
            source_evidence_ids=list(source_evidence_ids),
            reviewer_user_id=_uuid(reviewer_user_id),
            created_at=reviewed_at,
            previous_revision_id=None,
        )
        self._session.add_all((record, revision))
        self._session.flush((record, revision))
        self._risk_of_bias_audit(
            project_id,
            reviewer_user_id,
            record.id,
            "risk_of_bias.created",
            judgment,
            reviewed_at,
        )
        return str(record.id)

    def try_revise_risk_of_bias(
        self,
        project_id: str,
        record_id: str,
        *,
        reviewer_user_id: str,
        expected_revision: int,
        judgment: str,
        rationale: str | None,
        source_evidence_ids: tuple[str, ...],
        reviewed_at: datetime,
    ) -> bool:
        record_uuid = _uuid(record_id)
        record = self._session.scalar(
            select(RiskOfBiasRecordRow).where(
                RiskOfBiasRecordRow.id == record_uuid,
                RiskOfBiasRecordRow.project_id == _uuid(project_id),
            )
        )
        if record is None:
            raise ResourceNotFound
        self._validate_risk_of_bias_inputs(
            project_id,
            study_id=str(record.study_id),
            judgment=judgment,
            rationale=rationale,
            source_evidence_ids=source_evidence_ids,
        )
        predecessor = self._session.scalar(
            select(RiskOfBiasRevisionRow.id).where(
                RiskOfBiasRevisionRow.risk_of_bias_id == record_uuid,
                RiskOfBiasRevisionRow.revision == expected_revision,
            )
        )
        result = self._session.execute(
            update(RiskOfBiasRecordRow)
            .where(
                RiskOfBiasRecordRow.id == record_uuid,
                RiskOfBiasRecordRow.project_id == _uuid(project_id),
                RiskOfBiasRecordRow.current_revision == expected_revision,
            )
            .values(current_revision=expected_revision + 1)
        )
        accepted = result.rowcount == 1  # type: ignore[attr-defined]
        if accepted:
            if predecessor is None:
                raise RuntimeError("risk-of-bias revision lineage is missing")
            revision = RiskOfBiasRevisionRow(
                id=uuid4(),
                risk_of_bias_id=record_uuid,
                revision=expected_revision + 1,
                judgment=judgment,
                rationale=rationale,
                source_evidence_ids=list(source_evidence_ids),
                reviewer_user_id=_uuid(reviewer_user_id),
                created_at=reviewed_at,
                previous_revision_id=predecessor,
            )
            self._session.add(revision)
            self._session.flush([revision])
        self._risk_of_bias_audit(
            project_id,
            reviewer_user_id,
            record_uuid,
            "risk_of_bias.revised" if accepted else "risk_of_bias.revision_conflict",
            judgment,
            reviewed_at,
        )
        return accepted

    def _validate_risk_of_bias_inputs(
        self,
        project_id: str,
        *,
        study_id: str,
        judgment: str,
        rationale: str | None,
        source_evidence_ids: tuple[str, ...],
    ) -> None:
        if judgment not in {"unknown", "low", "some_concerns", "high"}:
            raise ValueError("invalid risk-of-bias judgment")
        if judgment != "unknown" and (not (rationale or "").strip() or not source_evidence_ids):
            raise ValueError("grounded rationale is required for a non-unknown judgment")
        accessible_study = self._session.scalar(
            select(PublicationDocumentRow.publication_id)
            .join(
                ProjectDocumentGrantRow,
                ProjectDocumentGrantRow.document_id == PublicationDocumentRow.document_id,
            )
            .where(
                PublicationDocumentRow.publication_id == _uuid(study_id),
                ProjectDocumentGrantRow.project_id == _uuid(project_id),
                ProjectDocumentGrantRow.revoked_at.is_(None),
            )
            .limit(1)
        )
        if accessible_study is None:
            raise ResourceNotFound
        if source_evidence_ids:
            source_uuids = {_uuid(item) for item in source_evidence_ids}
            found = set(
                self._session.scalars(
                    select(EvidenceRow.id).where(
                        EvidenceRow.project_id == _uuid(project_id),
                        EvidenceRow.id.in_(source_uuids),
                    )
                ).all()
            )
            if found != source_uuids:
                raise ResourceNotFound

    def _risk_of_bias_audit(
        self,
        project_id: str,
        reviewer_user_id: str,
        record_id: UUID,
        action: str,
        judgment: str,
        reviewed_at: datetime,
    ) -> None:
        self._session.add(
            AuditEventRow(
                id=uuid4(),
                occurred_at=reviewed_at,
                actor_user_id=_uuid(reviewer_user_id),
                project_id=_uuid(project_id),
                action=action,
                entity_type="risk_of_bias",
                entity_id=str(record_id),
                payload={"attempted_judgment": judgment},
            )
        )

    def _require_run(self, project_id: str, run_id: str) -> UUID:
        run_uuid = _uuid(run_id)
        exists = self._session.scalar(
            select(ResearchRunRow.id).where(
                ResearchRunRow.id == run_uuid,
                ResearchRunRow.project_id == _uuid(project_id),
            )
        )
        if exists is None:
            raise ResourceNotFound
        return run_uuid


class SqlUnitOfWork:
    """Repository bundle sharing the transaction owned by ``Database``."""

    def __init__(self, session: OrmSession) -> None:
        self.identities = SqlIdentityRepository(session)
        self.projects = SqlProjectRepository(session)
        self.sessions = SqlSessionRepository(session)
        self.audit = SqlAuditRepository(session)
        self.jobs = SqlJobRepository(session)
        self.research = SqlResearchRepository(session)
        self.provisioning = ProvisioningRepositories(self.identities, self.projects)
