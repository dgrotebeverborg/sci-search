"""Transactional laptop workspace catalog; sessions remain short-lived credentials."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sci_search.application.projects import (
    InMemoryProjectRepository,
    Membership,
    Project,
    ProjectRole,
    Workspace,
)


def encode(value) -> str:
    return json.dumps(value, default=lambda item: item.isoformat(), ensure_ascii=False)


class LocalCatalog:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "workspace.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entities(
                    kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS saved_runs(
                    project_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(project_id,id));
                CREATE TABLE IF NOT EXISTS dashboard_revisions(
                    project_id TEXT NOT NULL, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    feedback_sequence INTEGER NOT NULL, created_at TEXT NOT NULL,
                    snapshot TEXT NOT NULL, state TEXT NOT NULL, work_root TEXT NOT NULL,
                    PRIMARY KEY(project_id,run_id,revision));
                CREATE TABLE IF NOT EXISTS article_feedback(
                    project_id TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    actor TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload TEXT NOT NULL,
                    receipt TEXT NOT NULL,
                    PRIMARY KEY(project_id,run_id,sequence),
                    UNIQUE(project_id,run_id,actor,idempotency_key));
                CREATE TABLE IF NOT EXISTS saved_downloads(
                    project_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
                    content_type TEXT NOT NULL, path TEXT NOT NULL,
                    PRIMARY KEY(project_id,id));
                CREATE TABLE IF NOT EXISTS saved_evidence(
                    project_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(project_id,id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def put_entity(self, kind, item):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO entities VALUES(?,?,?)",
                (kind, item.id, encode(asdict(item))),
            )


class LocalProjectRepository(InMemoryProjectRepository):
    """Persist project ownership and membership through normal repository mutations."""

    def __init__(self, root: Path):
        super().__init__()
        self.catalog = LocalCatalog(root)
        with self.catalog.connect() as db:
            rows = db.execute("SELECT kind,payload FROM entities").fetchall()
        for row in rows:
            value = json.loads(row["payload"])
            value["created_at"] = datetime.fromisoformat(value["created_at"])
            if row["kind"] == "workspace":
                item = Workspace(**value)
                self._workspaces[item.id] = item
            elif row["kind"] == "project":
                if value.get("deleted_at"):
                    value["deleted_at"] = datetime.fromisoformat(value["deleted_at"])
                item = Project(**value)
                self._projects[item.id] = item
            elif row["kind"] == "membership":
                value["role"] = ProjectRole(value["role"])
                item = Membership(**value)
                self._memberships[item.id] = item

    def add_workspace(self, workspace):
        super().add_workspace(workspace)
        self.catalog.put_entity("workspace", workspace)

    def add_project(self, project):
        super().add_project(project)
        self.catalog.put_entity("project", project)

    def add_membership(self, membership):
        super().add_membership(membership)
        self.catalog.put_entity("membership", membership)

    def update_project(self, project):
        super().update_project(project)
        self.catalog.put_entity("project", project)

    def update_membership(self, membership):
        super().update_membership(membership)
        self.catalog.put_entity("membership", membership)
