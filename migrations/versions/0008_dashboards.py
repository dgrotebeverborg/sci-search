"""Persist immutable dashboards and contextual researcher feedback."""

from alembic import op

from sci_search.infrastructure.tables import ArticleFeedbackRow, DashboardRevisionRow

revision = "0008_dashboards"
down_revision = "0007_storage_gc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    DashboardRevisionRow.__table__.create(op.get_bind())
    ArticleFeedbackRow.__table__.create(op.get_bind())


def downgrade() -> None:
    ArticleFeedbackRow.__table__.drop(op.get_bind())
    DashboardRevisionRow.__table__.drop(op.get_bind())
