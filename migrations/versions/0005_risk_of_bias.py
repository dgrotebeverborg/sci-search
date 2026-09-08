"""Add revisioned risk-of-bias records.

Revision ID: 0005_risk_of_bias
Revises: 0004_jobs
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_risk_of_bias"
down_revision: str | Sequence[str] | None = "0004_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_of_bias_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=200), nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_risk_of_bias_records_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["publications.id"],
            name=op.f("fk_risk_of_bias_records_study_id_publications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_of_bias_records")),
        sa.UniqueConstraint(
            "project_id",
            "study_id",
            "tool",
            "domain",
            name=op.f("uq_risk_of_bias_records_project_id"),
        ),
    )
    op.create_index(
        op.f("ix_risk_of_bias_records_project_id"),
        "risk_of_bias_records",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_of_bias_records_study_id"), "risk_of_bias_records", ["study_id"], unique=False
    )
    op.create_table(
        "risk_of_bias_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_of_bias_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("judgment", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "judgment IN ('unknown', 'low', 'some_concerns', 'high')",
            name=op.f("ck_risk_of_bias_revisions_valid_judgment"),
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["risk_of_bias_revisions.id"],
            name=op.f("fk_risk_of_bias_revisions_previous_revision_id_risk_of_bias_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name=op.f("fk_risk_of_bias_revisions_reviewer_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["risk_of_bias_id"],
            ["risk_of_bias_records.id"],
            name=op.f("fk_risk_of_bias_revisions_risk_of_bias_id_risk_of_bias_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_of_bias_revisions")),
        sa.UniqueConstraint(
            "risk_of_bias_id", "revision", name=op.f("uq_risk_of_bias_revisions_risk_of_bias_id")
        ),
    )
    op.create_index(
        op.f("ix_risk_of_bias_revisions_risk_of_bias_id"),
        "risk_of_bias_revisions",
        ["risk_of_bias_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_of_bias_revisions_reviewer_user_id"),
        "risk_of_bias_revisions",
        ["reviewer_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_risk_of_bias_revisions_reviewer_user_id"), table_name="risk_of_bias_revisions"
    )
    op.drop_index(
        op.f("ix_risk_of_bias_revisions_risk_of_bias_id"), table_name="risk_of_bias_revisions"
    )
    op.drop_table("risk_of_bias_revisions")
    op.drop_index(op.f("ix_risk_of_bias_records_study_id"), table_name="risk_of_bias_records")
    op.drop_index(op.f("ix_risk_of_bias_records_project_id"), table_name="risk_of_bias_records")
    op.drop_table("risk_of_bias_records")
