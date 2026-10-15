"""Append-only contextual article decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sci_search.application.research_api import ResourceVersionConflict
from sci_search.infrastructure.dashboard_repository import DashboardRepository
from sci_search.infrastructure.tables import ArticleFeedbackRow


class FeedbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        project_id: str,
        run_id: str,
        user_id: str,
        publication_id: str,
        *,
        decision: str,
        reason: str,
        expected_sequence: int,
        idempotency_key: str,
        created_at: datetime,
        reviewed_revision: int | None = None,
    ) -> ArticleFeedbackRow:
        if decision not in {"include", "exclude", "background", "reset"} or not idempotency_key:
            raise ValueError("invalid article feedback")
        dashboards = DashboardRepository(self.session)
        run = dashboards.lock_run(project_id, run_id)
        previous = self.session.scalar(
            select(ArticleFeedbackRow).where(
                ArticleFeedbackRow.run_id == UUID(run_id),
                ArticleFeedbackRow.idempotency_key == idempotency_key,
            )
        )
        if previous:
            if (
                str(previous.user_id),
                previous.publication_id,
                previous.decision,
                previous.reason,
                previous.context_json.get("requested_reviewed_revision"),
                previous.sequence - 1,
            ) != (user_id, publication_id, decision, reason, reviewed_revision, expected_sequence):
                raise ResourceVersionConflict
            return previous
        if dashboards.sequence(run_id) != expected_sequence:
            raise ResourceVersionConflict
        reviewed = dashboards.get(project_id, run_id)
        if reviewed_revision is not None and reviewed_revision != reviewed.revision:
            raise ResourceVersionConflict
        row = ArticleFeedbackRow(
            run_id=UUID(run_id),
            project_id=UUID(project_id),
            user_id=UUID(user_id),
            publication_id=publication_id,
            decision=decision,
            reason=reason,
            reviewed_revision=reviewed.revision,
            context_json={
                "question": run.question,
                "requested_reviewed_revision": reviewed_revision,
                "configuration": {
                    key: value
                    for key, value in run.configuration_json.items()
                    if key == "review_depth"
                },
            },
            source_fingerprint=reviewed.snapshot_json.get("source_archive_key"),
            sequence=expected_sequence + 1,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def effective(self, run_id: str, sequence: int) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for event in self.session.scalars(
            select(ArticleFeedbackRow)
            .where(
                ArticleFeedbackRow.run_id == UUID(run_id), ArticleFeedbackRow.sequence <= sequence
            )
            .order_by(ArticleFeedbackRow.sequence)
        ):
            if event.decision == "reset":
                result.pop(event.publication_id, None)
            else:
                result[event.publication_id] = {
                    "decision": event.decision,
                    "reason": event.reason,
                    "source": "researcher",
                    "decided_at": event.created_at.isoformat(),
                }
        return result
