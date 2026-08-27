"""Add resumable checkpoints to the legacy import ledger.

Revision ID: 0006_legacy_import_checkpoints
Revises: 0005_risk_of_bias
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_legacy_import_checkpoints"
down_revision: str | Sequence[str] | None = "0005_risk_of_bias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "legacy_imports",
        sa.Column("status", sa.String(length=32), server_default="completed", nullable=False),
    )
    op.add_column(
        "legacy_imports",
        sa.Column("checkpoint_json", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "legacy_imports",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "legacy_imports",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE legacy_imports SET completed_at = applied_at WHERE status = 'completed'")


def downgrade() -> None:
    op.drop_column("legacy_imports", "completed_at")
    op.drop_column("legacy_imports", "updated_at")
    op.drop_column("legacy_imports", "checkpoint_json")
    op.drop_column("legacy_imports", "status")
