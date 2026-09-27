"""Add project-scoped scientific graph projections and memory object references."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_memory"
down_revision: str | Sequence[str] | None = "0008_dashboards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _project():
    return sa.Column(
        "project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )


def upgrade() -> None:
    op.create_table(
        "memory_states",
        _project(),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "memory_nodes",
        _project(),
        sa.Column("node_id", sa.String(500), primary_key=True),
        sa.Column("node_type", sa.String(100), nullable=False),
        sa.Column("properties_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "memory_edges",
        _project(),
        sa.Column("edge_id", sa.String(500), primary_key=True),
        sa.Column("source_id", sa.String(500), nullable=False),
        sa.Column("relation_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(500), nullable=False),
        sa.Column("properties_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_memory_edges_source_id", "memory_edges", ["source_id"])
    op.create_index("ix_memory_edges_target_id", "memory_edges", ["target_id"])
    op.create_table(
        "memory_checkpoints",
        _project(),
        sa.Column("run_id", sa.String(500), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("projection_version", sa.String(100), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("memory_checkpoints")
    op.drop_index("ix_memory_edges_target_id", "memory_edges")
    op.drop_index("ix_memory_edges_source_id", "memory_edges")
    op.drop_table("memory_edges")
    op.drop_table("memory_nodes")
    op.drop_table("memory_states")
