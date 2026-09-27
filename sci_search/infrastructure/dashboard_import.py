"""Explicit-owner, non-destructive recovery of retained local research artifacts."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sci_search.application.authorization import Action
from sci_search.application.research_api import InMemoryResearchApiService
from sci_search.literature_review import build_literature_review, render_review_html
from sci_search.research_runs import DownloadPayload


class RetainedArtifacts:
    def __init__(self, source: Path, state: dict):
        self.source, self.state = source, state

    def download_literature_review(self, run_id, output_format="html"):
        result = self.state["result"]
        report = result.get("literature_review_report") or build_literature_review(result)
        return DownloadPayload("review.html", "text/html", render_review_html(report).encode())

    def download_research_package(self, run_id):
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("review.html", self.download_literature_review(run_id).body)
            for path in sorted(self.source.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    relative = path.relative_to(self.source)
                    if path.suffix.lower() in {".json", ".pdf", ".xml", ".nxml", ".txt", ".md"}:
                        archive.write(path, str(relative))
        return DownloadPayload("research.zip", "application/zip", buffer.getvalue())

    def download_publication(self, run_id, publication_id):
        acquisition = next(
            (
                item
                for item in self.state.get("acquisitions", [])
                if item.get("publication_id") == publication_id and item.get("relative_path")
            ),
            None,
        )
        if acquisition is None:
            raise KeyError(publication_id)
        corpus = (self.source / "corpus").resolve()
        path = (
            corpus / (acquisition.get("download_relative_path") or acquisition["relative_path"])
        ).resolve()
        if not path.is_relative_to(corpus):
            raise ValueError("source document leaves retained corpus")
        return DownloadPayload(
            path.name,
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            path.read_bytes(),
        )


def import_local_run(
    service, user_id: str, project_id: str, source: Path, *, dry_run=False
) -> dict:
    """Retain original files and explicitly grant the supplied project a recovered run."""
    service._require(Action.MANAGE_RUNS, user_id, project_id)
    source = Path(source).resolve()
    if not (source / "run.json").is_file():
        raise ValueError("source directory must contain run.json")
    state = json.loads((source / "run.json").read_text())
    internal = str(state.get("run_id") or source.name)
    if not internal or any(not (c.isalnum() or c in "-_") for c in internal):
        raise ValueError("invalid retained run identifier")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("retained source must not contain symbolic links")
    question = str(state.get("question") or "Recovered research")
    fingerprint = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if path.is_file():
            fingerprint.update(str(path.relative_to(source)).encode())
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    fingerprint.update(chunk)
    import_key = "import:" + fingerprint.hexdigest()
    complete = isinstance(state.get("result"), dict)
    if dry_run:
        return {
            "status": "ready" if complete else "incomplete",
            "question": question,
            "fingerprint": fingerprint.hexdigest(),
            "project_id": project_id,
        }
    with service._lock:
        for key, metadata in service._metadata.items():
            if key[0] == project_id and metadata["idempotency_key"] == import_key:
                if metadata.get("current_revision", 0) or metadata.get("import_complete"):
                    return {"status": "already_imported", "run_id": key[1]}
        run = InMemoryResearchApiService.start_run(
            service,
            user_id,
            project_id,
            question=question,
            review_depth="focused",
            idempotency_key=import_key,
        )
        key = (project_id, run.id)
        service._metadata[key] = {
            "user_id": user_id,
            "idempotency_key": import_key,
            "current_revision": 0,
            "feedback_sequence": 0,
            "rebuild_status": "idle",
        }
        service._latest_runs[project_id] = run.id
        service._scheduled.add(run.id)
        service._runs[key] = replace(run, status="failed")
        service._metadata[key]["recovery_note"] = (
            "Import has not completed; rerun the import command to resume."
        )
        service._persist_run(key)
        work_root = service.root / project_id / run.id / "imports" / uuid4().hex
        target = work_root / internal
        shutil.copytree(source, target)
        if not complete:
            service._runs[key] = replace(run, status="failed")
            service._metadata[key]["recovery_note"] = "Retained research lacks a complete result."
            service._metadata[key]["import_complete"] = True
            service._persist_run(key)
            return {"status": "incomplete", "run_id": run.id}
        state["run_id"] = internal
        state["result"].setdefault("question", question)
        artifacts = RetainedArtifacts(target, state)
        snapshot, downloads = service._prepare_revision(run, state, artifacts, work_root, 1, 0)
        snapshot["rebuild_available"] = (target / "corpus" / "manifest.json").is_file()
        service._publish_revision(run, state, work_root, snapshot, downloads)
        return {"status": "imported", "run_id": run.id}
