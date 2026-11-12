"""Immutable dashboard revisions serialized by their parent research run."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sci_search.application.authorization import ResourceNotFound
from sci_search.infrastructure.tables import (
    ArticleFeedbackRow,
    DashboardRevisionRow,
    ResearchRunRow,
)


class DashboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_run(self, project_id: str, run_id: str) -> ResearchRunRow:
        row = self.session.scalar(
            select(ResearchRunRow)
            .where(ResearchRunRow.project_id == UUID(project_id), ResearchRunRow.id == UUID(run_id))
            .with_for_update()
        )
        if row is None:
            raise ResourceNotFound
        return row

    def sequence(self, run_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.max(ArticleFeedbackRow.sequence)).where(
                    ArticleFeedbackRow.run_id == UUID(run_id)
                )
            )
            or 0
        )

    def get(
        self, project_id: str, run_id: str, revision: int | None = None
    ) -> DashboardRevisionRow:
        statement = select(DashboardRevisionRow).where(
            DashboardRevisionRow.project_id == UUID(project_id),
            DashboardRevisionRow.run_id == UUID(run_id),
        )
        if revision is not None:
            statement = statement.where(DashboardRevisionRow.revision == revision)
        row = self.session.scalar(statement.order_by(DashboardRevisionRow.revision.desc()).limit(1))
        if row is None:
            raise ResourceNotFound
        return row

    def require_reviewer(self, project_id: str, run_id: str, sequence: int) -> str:
        from sci_search.application.authorization import Action, AuthorizationContext, ProjectPolicy
        from sci_search.infrastructure.repositories import SqlProjectRepository

        event = self.session.scalar(
            select(ArticleFeedbackRow).where(
                ArticleFeedbackRow.project_id == UUID(project_id),
                ArticleFeedbackRow.run_id == UUID(run_id),
                ArticleFeedbackRow.sequence == sequence,
            )
        )
        if event is None:
            raise ResourceNotFound
        actor = str(event.user_id)
        ProjectPolicy(SqlProjectRepository(self.session)).require(
            Action.REVIEW, AuthorizationContext(actor), project_id
        )
        return actor

    def publish(
        self,
        project_id: str,
        run_id: str,
        snapshot: dict[str, Any],
        *,
        feedback_sequence: int,
        created_at: datetime,
    ) -> int | None:
        run = self.lock_run(project_id, run_id)
        if self.sequence(run_id) != feedback_sequence:
            return None
        if feedback_sequence:
            self.require_reviewer(project_id, run_id, feedback_sequence)
        existing = self.session.scalar(
            select(DashboardRevisionRow).where(
                DashboardRevisionRow.run_id == UUID(run_id),
                DashboardRevisionRow.feedback_sequence == feedback_sequence,
            )
        )
        if existing:
            return existing.revision
        revision = (
            int(
                self.session.scalar(
                    select(func.max(DashboardRevisionRow.revision)).where(
                        DashboardRevisionRow.run_id == UUID(run_id)
                    )
                )
                or 0
            )
            + 1
        )
        self.session.add(
            DashboardRevisionRow(
                run_id=UUID(run_id),
                project_id=UUID(project_id),
                revision=revision,
                feedback_sequence=feedback_sequence,
                snapshot_json={**snapshot, "revision": revision},
                created_at=created_at,
            )
        )
        run.configuration_json = {**run.configuration_json, "dashboard_revision": revision}
        self.session.flush()
        return revision
