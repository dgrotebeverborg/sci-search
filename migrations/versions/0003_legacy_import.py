"""Add the idempotent legacy import ledger.

Revision ID: 0003_legacy_import
Revises: 0002_research_storage
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_legacy_import"
down_revision: str | Sequence[str] | None = "0002_research_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legacy_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_root", sa.String(length=2000), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_legacy_imports_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_imports")),
        sa.UniqueConstraint(
            "project_id",
            "source_fingerprint",
            name=op.f("uq_legacy_imports_project_id"),
        ),
    )
    op.create_index(
        op.f("ix_legacy_imports_project_id"),
        "legacy_imports",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_legacy_imports_project_id"), table_name="legacy_imports")
    op.drop_table("legacy_imports")
