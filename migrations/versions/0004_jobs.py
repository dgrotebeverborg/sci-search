"""Add durable jobs, leases, attempts, and checkpoints.

Revision ID: 0004_jobs
Revises: 0003_legacy_import
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_jobs"
down_revision: str | Sequence[str] | None = "0003_legacy_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=100), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'cancelled', 'failed', 'completed')",
            name=op.f("ck_jobs_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_jobs_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_jobs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("project_id", "idempotency_key", name=op.f("uq_jobs_project_id")),
    )
    op.create_index(op.f("ix_jobs_project_id"), "jobs", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_jobs_created_by_user_id"), "jobs", ["created_by_user_id"], unique=False
    )
    op.create_index(op.f("ix_jobs_lease_expires_at"), "jobs", ["lease_expires_at"], unique=False)
    op.create_table(
        "job_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("stage_name", sa.String(length=100), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("implementation_version", sa.String(length=100), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_checkpoints_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_checkpoints")),
        sa.UniqueConstraint(
            "job_id",
            "stage_name",
            "input_fingerprint",
            "implementation_version",
            name=op.f("uq_job_checkpoints_job_id"),
        ),
    )
    op.create_index(op.f("ix_job_checkpoints_job_id"), "job_checkpoints", ["job_id"], unique=False)
    op.create_table(
        "stage_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("stage_name", sa.String(length=100), nullable=False),
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_stage_attempts_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_attempts")),
        sa.UniqueConstraint("job_id", "attempt_number", name=op.f("uq_stage_attempts_job_id")),
    )
    op.create_index(op.f("ix_stage_attempts_job_id"), "stage_attempts", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stage_attempts_job_id"), table_name="stage_attempts")
    op.drop_table("stage_attempts")
    op.drop_index(op.f("ix_job_checkpoints_job_id"), table_name="job_checkpoints")
    op.drop_table("job_checkpoints")
    op.drop_index(op.f("ix_jobs_lease_expires_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_created_by_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_project_id"), table_name="jobs")
    op.drop_table("jobs")
