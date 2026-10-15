"""Project-scoped graph projections and content-addressed memory checkpoints."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from sci_search.infrastructure.tables import Base


class MemoryStateRow(Base):
    __tablename__ = "memory_states"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class MemoryNodeRow(Base):
    __tablename__ = "memory_nodes"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(100), nullable=False)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MemoryEdgeRow(Base):
    __tablename__ = "memory_edges"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    edge_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MemoryCheckpointRow(Base):
    __tablename__ = "memory_checkpoints"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    projection_version: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
