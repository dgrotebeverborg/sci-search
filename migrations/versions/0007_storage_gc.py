"""Add persistent storage garbage-collection plans.

Revision ID: 0007_storage_gc
Revises: 0006_legacy_import_checkpoints
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_storage_gc"
down_revision: str | Sequence[str] | None = "0006_legacy_import_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_gc_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_gc_plans")),
    )
    op.create_table(
        "storage_gc_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("object_kind", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("blob_key", sa.String(length=1000), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("reference_count", sa.Integer(), nullable=False),
        sa.Column("project_ids_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["storage_gc_plans.id"],
            name=op.f("fk_storage_gc_items_plan_id_storage_gc_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_gc_items")),
        sa.UniqueConstraint(
            "plan_id",
            "object_kind",
            "object_id",
            name=op.f("uq_storage_gc_items_plan_id"),
        ),
    )
    op.create_index(
        op.f("ix_storage_gc_items_plan_id"), "storage_gc_items", ["plan_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_storage_gc_items_plan_id"), table_name="storage_gc_items")
    op.drop_table("storage_gc_items")
    op.drop_table("storage_gc_plans")
