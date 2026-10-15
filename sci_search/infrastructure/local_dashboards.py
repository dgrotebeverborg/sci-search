"""Saved dashboard and feedback operations for the durable laptop adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sci_search.application.authorization import Action, AuthorizationContext, ResourceNotFound
from sci_search.application.research_api import (
    DownloadRecord,
    EvidenceRecord,
    ResearchRunRecord,
    ResourceVersionConflict,
)
from sci_search.infrastructure.local_workspace import LocalCatalog, encode


class LocalDashboardOperations:
    def _restore_catalog(self):
        self.catalog = LocalCatalog(self.root)
        self._metadata = {}
        with self.catalog.connect() as db:
            for row in db.execute("SELECT * FROM saved_runs"):
                metadata = json.loads(row["payload"])
                record = metadata["run"]
                for field in ("created_at", "updated_at"):
                    record[field] = datetime.fromisoformat(record[field])
                run = ResearchRunRecord(**record)
                key = (run.project_id, run.id)
                self._runs[key] = run
                self._metadata[key] = metadata
                self._run_idempotency[(run.project_id, metadata["idempotency_key"])] = run.id
                self._scheduled.add(run.id)
            for row in db.execute("SELECT * FROM saved_evidence"):
                value = json.loads(row["payload"])
                value["created_at"] = datetime.fromisoformat(value["created_at"])
                record = EvidenceRecord(**value)
                self._evidence[(record.project_id, record.id)] = record
                self._evidence_runs[record.id] = row["run_id"]
            for row in db.execute("SELECT * FROM saved_downloads WHERE kind='export'"):
                path = self._object_path(row["path"])
                if path.is_file():
                    self._exports[(row["project_id"], row["id"])] = DownloadRecord(
                        row["filename"], row["content_type"], (path.read_bytes(),)
                    )
                    self._export_runs[row["id"]] = row["run_id"]
        for run in sorted(self._runs.values(), key=lambda r: (r.created_at, r.id)):
            self._latest_runs[run.project_id] = run.id
            if run.status in {"queued", "running", "cancel_requested"}:
                self._runs[(run.project_id, run.id)] = replace(
                    run,
                    status="cancelled" if run.status == "cancel_requested" else "failed",
                    updated_at=self._clock(),
                    version=run.version + 1,
                )
                self._persist_run((run.project_id, run.id))
        for key, metadata in self._metadata.items():
            if metadata.get("rebuild_status") in {"queued", "running"}:
                metadata["rebuild_status"] = "queued"
                self._executor.submit(self._rebuild, *key)
            if metadata.get("memory_status") == "pending":
                self._executor.submit(self._recover_memory, *key)

    def _persist_run(self, key, db=None):
        metadata = dict(self._metadata[key])
        metadata["run"] = asdict(self._runs[key])
        if db is None:
            with self.catalog.connect() as connection:
                self._persist_run(key, connection)
        else:
            db.execute("INSERT OR REPLACE INTO saved_runs VALUES(?,?,?)", (*key, encode(metadata)))

    def _object_path(self, path):
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ResourceNotFound
        return target

    def list_runs(self, user_id, project_id, *, query="", cursor=None, limit=30):
        self._require(Action.READ, user_id, project_id)
        query = query.strip().casefold()
        boundary = None
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if decoded["query"] != query or decoded["project"] != project_id:
                    raise ValueError
                boundary = (datetime.fromisoformat(decoded["created_at"]), decoded["id"])
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("invalid history cursor") from exc
        with self._lock:
            items = sorted(
                (
                    r
                    for (p, _), r in self._runs.items()
                    if p == project_id
                    and query in r.question.casefold()
                    and (boundary is None or (r.created_at, r.id) < boundary)
                ),
                key=lambda r: (r.created_at, r.id),
                reverse=True,
            )
            page = items[:limit]
            next_cursor = None
            if len(items) > limit:
                last = page[-1]
                next_cursor = base64.urlsafe_b64encode(
                    encode(
                        {
                            "query": query,
                            "project": project_id,
                            "created_at": last.created_at,
                            "id": last.id,
                        }
                    ).encode()
                ).decode()
            return {"items": [asdict(item) for item in page], "next_cursor": next_cursor}

    def get_dashboard(self, user_id, project_id, run_id, *, revision=None):
        grant = self._policy.require(Action.READ, AuthorizationContext(user_id), project_id)
        with self._lock:
            self.get_run(user_id, project_id, run_id)
            metadata = self._metadata[(project_id, run_id)]
            selected = revision or metadata.get("current_revision", 0)
            with self.catalog.connect() as db:
                row = db.execute(
                    "SELECT snapshot FROM dashboard_revisions WHERE project_id=? AND run_id=? AND revision=?",
                    (project_id, run_id, selected),
                ).fetchone()
            if row is None:
                raise ResourceNotFound
            result = json.loads(row["snapshot"])
            result.update(
                role=grant.role.value,
                feedback_sequence=metadata.get("feedback_sequence", 0),
                current_revision=metadata.get("current_revision", 0),
                rebuild_status=metadata.get("rebuild_status", "idle"),
            )
            if selected == metadata.get("current_revision"):
                for review in result.get("evidence_reviews", {}).values():
                    record = self._evidence.get((project_id, review["id"]))
                    if record:
                        review.update(
                            version=record.version,
                            review_decision=record.review_decision,
                            review_note=record.review_note,
                        )
            result["effective_decisions"] = self._effective(
                project_id,
                run_id,
                metadata.get("feedback_sequence", 0)
                if revision is None
                else result.get("applied_feedback_sequence", 0),
            )
            return result

    def list_revisions(self, user_id, project_id, run_id):
        self.get_run(user_id, project_id, run_id)
        with self.catalog.connect() as db:
            rows = db.execute(
                "SELECT revision,created_at,feedback_sequence FROM dashboard_revisions WHERE project_id=? AND run_id=? ORDER BY revision DESC",
                (project_id, run_id),
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    def _feedback_events(self, project_id):
        with self.catalog.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM article_feedback WHERE project_id=? ORDER BY run_id,sequence",
                    (project_id,),
                )
            ]

    def _effective(self, project_id, run_id, sequence):
        result = {}
        for event in self._feedback_events(project_id):
            if event["run_id"] != run_id or event["sequence"] > sequence:
                continue
            if event["decision"] == "reset":
                result.pop(event["publication_id"], None)
            else:
                result[event["publication_id"]] = event
        return result

    def record_article_feedback(
        self,
        user_id,
        project_id,
        run_id,
        publication_id,
        *,
        decision,
        reason,
        expected_sequence,
        idempotency_key,
        reviewed_revision=None,
    ):
        self._require(Action.REVIEW, user_id, project_id)
        if decision not in {"include", "background", "exclude", "reset"}:
            raise ValueError("invalid article decision")
        reason = " ".join(reason.split())
        key = (project_id, run_id)
        with self._lock:
            run = self.get_run(user_id, project_id, run_id)
            metadata = self._metadata[key]
            with self.catalog.connect() as db:
                existing = db.execute(
                    "SELECT payload,receipt FROM article_feedback WHERE project_id=? AND run_id=? AND actor=? AND idempotency_key=?",
                    (*key, user_id, idempotency_key),
                ).fetchone()
                if existing:
                    event = json.loads(existing["payload"])
                    if (
                        event["publication_id"],
                        event["decision"],
                        event["reason"],
                        event["expected_sequence"],
                        event.get("requested_revision"),
                    ) != (publication_id, decision, reason, expected_sequence, reviewed_revision):
                        raise ResourceVersionConflict
                    return json.loads(existing["receipt"])
                if reviewed_revision is not None and reviewed_revision != metadata.get(
                    "current_revision"
                ):
                    raise ResourceVersionConflict
                if metadata.get("feedback_sequence", 0) != expected_sequence:
                    raise ResourceVersionConflict
                row = db.execute(
                    "SELECT state FROM dashboard_revisions WHERE project_id=? AND run_id=? ORDER BY revision LIMIT 1",
                    key,
                ).fetchone()
                if not row:
                    raise ValueError("complete a review before deciding article relevance")
                state = json.loads(row[0])
                saved = db.execute(
                    "SELECT snapshot FROM dashboard_revisions WHERE project_id=? AND run_id=? AND revision=1",
                    key,
                ).fetchone()
                if json.loads(saved[0]).get("rebuild_available") is False:
                    raise ValueError("retained source ledger is unavailable for rebuilding")
                candidates = state.get("candidates") or state.get("result", {}).get(
                    "research_run", {}
                ).get("candidates", [])
                candidate = next(
                    (item for item in candidates if item.get("id") == publication_id), None
                )
                if candidate is None:
                    raise ResourceNotFound
                sequence = expected_sequence + 1
                event = {
                    "id": self._id_source(),
                    "project_id": project_id,
                    "run_id": run_id,
                    "publication_id": publication_id,
                    "user_id": user_id,
                    "actor_user_id": user_id,
                    "question": run.question,
                    "question_context": state.get("plan"),
                    "decision": decision,
                    "reason": reason,
                    "created_at": self._clock().isoformat(),
                    "sequence": sequence,
                    "expected_sequence": expected_sequence,
                    "reviewed_revision": metadata["current_revision"],
                    "requested_revision": reviewed_revision,
                    "source_fingerprint": hashlib.sha256(
                        encode(
                            [
                                row[0]
                                for row in db.execute(
                                    "SELECT path FROM saved_downloads WHERE project_id=? AND run_id=? AND kind='document' ORDER BY path",
                                    key,
                                )
                            ]
                        ).encode()
                    ).hexdigest(),
                    "doi": candidate.get("doi"),
                }
                receipt = {
                    "event_id": event["id"],
                    "feedback_sequence": sequence,
                    "rebuild_job_id": f"{run_id}:{sequence}",
                    "current_revision": metadata["current_revision"],
                    "rebuild_status": "queued",
                }
                db.execute(
                    "INSERT INTO article_feedback VALUES(?,?,?,?,?,?,?)",
                    (*key, sequence, user_id, idempotency_key, encode(event), encode(receipt)),
                )
                metadata.update(
                    feedback_sequence=sequence, rebuild_status="queued", rebuild_actor=user_id
                )
                self._persist_run(key, db)
            self._executor.submit(self._rebuild, *key)
            return receipt

    def retry_rebuild(self, user_id, project_id, run_id):
        self._require(Action.REVIEW, user_id, project_id)
        self.get_run(user_id, project_id, run_id)
        key = (project_id, run_id)
        with self._lock:
            metadata = self._metadata[key]
            if metadata.get("rebuild_status") != "failed":
                raise ValueError("only failed rebuilds can be retried")
            metadata["rebuild_status"] = "queued"
            metadata["rebuild_actor"] = user_id
            self._persist_run(key)
            self._executor.submit(self._rebuild, *key)
            return {"rebuild_status": "queued", "feedback_sequence": metadata["feedback_sequence"]}

    def _prepare_revision(self, run, state, manager, work_root, revision, sequence):
        from sci_search.dashboard import build_dashboard

        state["result"]["analysis_selection"] = run.analysis_selection
        investigation = dict(state["result"])
        investigation.setdefault("question", run.question)
        snapshot = build_dashboard(investigation, run_id=run.id, revision=revision)
        snapshot.update(
            project_id=run.project_id,
            applied_feedback_sequence=sequence,
            artifacts=[],
            documents={},
        )
        downloads = []
        payloads = [
            ("export", None, manager.download_literature_review(state["run_id"], "html")),
            ("export", None, manager.download_research_package(state["run_id"])),
        ]
        if hasattr(manager, "download_publication"):
            for candidate in state.get("candidates", []):
                try:
                    payloads.append(
                        (
                            "document",
                            candidate["id"],
                            manager.download_publication(state["run_id"], candidate["id"]),
                        )
                    )
                except (KeyError, ValueError, FileNotFoundError):
                    from sci_search.infrastructure.dashboard_import import RetainedArtifacts

                    try:
                        payloads.append(
                            (
                                "document",
                                candidate["id"],
                                RetainedArtifacts(
                                    Path(work_root) / state["run_id"], state
                                ).download_publication(state["run_id"], candidate["id"]),
                            )
                        )
                    except (KeyError, ValueError, FileNotFoundError):
                        continue
        # Keep acquired originals accessible even when their studies are excluded later.
        if revision > 1:
            with self.catalog.connect() as db:
                first = db.execute(
                    "SELECT snapshot FROM dashboard_revisions WHERE project_id=? AND run_id=? AND revision=1",
                    (run.project_id, run.id),
                ).fetchone()
            if first:
                snapshot["documents"] = json.loads(first[0]).get("documents", {})
        for kind, publication_id, payload in payloads:
            identifier = self._id_source()
            digest = hashlib.sha256(payload.body).hexdigest()
            relative = f"objects/{digest}"
            path = self._object_path(relative)
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                temporary = path.with_name(f".{digest}.{uuid4().hex}.tmp")
                temporary.write_bytes(payload.body)
                temporary.replace(path)
            downloads.append(
                (
                    run.project_id,
                    identifier,
                    run.id,
                    revision,
                    kind,
                    payload.filename,
                    payload.content_type,
                    relative,
                )
            )
            url = f"/api/v1/projects/{run.project_id}/{'exports' if kind == 'export' else 'documents'}/{identifier}"
            if kind == "export":
                snapshot["artifacts"].append(
                    {
                        "id": identifier,
                        "filename": payload.filename,
                        "url": url,
                        "content_type": payload.content_type,
                    }
                )
            else:
                snapshot["documents"][publication_id] = {"url": url, "title": payload.filename}
        return snapshot, downloads

    def _publish_revision(self, run, state, work_root, snapshot, downloads):
        key = (run.project_id, run.id)
        metadata = self._metadata[key]
        revision = snapshot["revision"]
        evidence = []
        snapshot["evidence_reviews"] = {}
        for item in state["result"].get("evidence", []):
            if not isinstance(item, dict) or not item.get("statement") or not item.get("passage"):
                continue
            record = EvidenceRecord(
                self._id_source(),
                run.project_id,
                str(item["statement"]),
                str(item["passage"]),
                item.get("section"),
                item.get("page"),
                1,
                self._clock(),
            )
            evidence.append(record)
            if item.get("id"):
                snapshot["evidence_reviews"][item["id"]] = {
                    "id": record.id,
                    "version": 1,
                    "review_decision": None,
                    "review_note": None,
                }
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO dashboard_revisions VALUES(?,?,?,?,?,?,?,?)",
                (
                    *key,
                    revision,
                    snapshot["applied_feedback_sequence"],
                    self._clock().isoformat(),
                    encode(snapshot),
                    encode(state),
                    str(Path(work_root).relative_to(self.root)),
                ),
            )
            db.executemany("INSERT INTO saved_downloads VALUES(?,?,?,?,?,?,?,?)", downloads)
            db.executemany(
                "INSERT INTO saved_evidence VALUES(?,?,?,?,?)",
                [
                    (run.project_id, item.id, run.id, revision, encode(asdict(item)))
                    for item in evidence
                ],
            )
            next_run = replace(
                self._runs[key],
                status="completed",
                updated_at=self._clock(),
                version=self._runs[key].version + 1,
            )
            next_metadata = {
                **metadata,
                "current_revision": revision,
                "rebuild_status": "idle",
                "memory_status": "pending",
                "run": asdict(next_run),
            }
            db.execute(
                "INSERT OR REPLACE INTO saved_runs VALUES(?,?,?)", (*key, encode(next_metadata))
            )
        self._runs[key] = next_run
        self._metadata[key] = next_metadata
        for item in evidence:
            self._evidence[(run.project_id, item.id)] = item
            self._evidence_runs[item.id] = run.id
        for p, identifier, run_id, _, kind, filename, content_type, relative in downloads:
            if kind == "export":
                self._exports[(p, identifier)] = DownloadRecord(
                    filename, content_type, (self._object_path(relative).read_bytes(),)
                )
                self._export_runs[identifier] = run_id

    def _rebuild(self, project_id, run_id):
        from sci_search.model_provider import analysis_scope

        with analysis_scope(self._runs[(project_id, run_id)].analysis_selection):
            self._rebuild_selected(project_id, run_id)

    def _rebuild_selected(self, project_id, run_id):
        from sci_search.infrastructure import local_research

        key = (project_id, run_id)
        sequence = None
        try:
            with self._lock:
                metadata = self._metadata[key]
                if metadata.get("rebuild_status") not in {"queued", "running"}:
                    return
                sequence = metadata["feedback_sequence"]
                actor = metadata.get("rebuild_actor", metadata["user_id"])
                self._require(Action.REVIEW, actor, project_id)
                run = self._runs[key]
                revision = metadata["current_revision"] + 1
                metadata["rebuild_status"] = "running"
                self._persist_run(key)
                decisions = self._effective(project_id, run_id, sequence)
                with self.catalog.connect() as db:
                    first = db.execute(
                        "SELECT state,work_root FROM dashboard_revisions WHERE project_id=? AND run_id=? AND revision=1",
                        key,
                    ).fetchone()
                state = json.loads(first["state"])
            internal = str(state["run_id"])
            if not internal or any(not (c.isalnum() or c in "-_") for c in internal):
                raise ValueError("invalid retained run identifier")
            source = self._object_path(str(Path(first["work_root"]) / internal))
            work_root = self.root / project_id / run_id / "rebuilds" / uuid4().hex
            shutil.copytree(source, work_root / state["run_id"])
            manager = local_research._manager(work_root)
            memory = self._attach_memory(manager, project_id, actor)
            manager.get(state["run_id"])
            manager._update(state["run_id"], review_decisions=decisions)
            manager._rebuild_evidence(state["run_id"])
            state = manager.get(state["run_id"])
            snapshot, downloads = self._prepare_revision(
                run, state, manager, work_root, revision, sequence
            )
            with self._lock:
                self._require(Action.REVIEW, actor, project_id)
                if self._metadata[key]["feedback_sequence"] != sequence:
                    self._metadata[key]["rebuild_status"] = "queued"
                    self._persist_run(key)
                    return
                self._publish_revision(run, state, work_root, snapshot, downloads)
            self._publish_memory(memory, revision, key)
        except Exception:
            local_research.logger.exception("Local dashboard rebuild failed: %s", run_id)
            with self._lock:
                self._metadata[key]["rebuild_status"] = (
                    "queued"
                    if sequence is not None and self._metadata[key]["feedback_sequence"] != sequence
                    else "failed"
                )
                self._persist_run(key)

    def _open_saved_download(self, user_id, project_id, identifier, kind):
        self._require(Action.DOWNLOAD, user_id, project_id)
        with self.catalog.connect() as db:
            row = db.execute(
                "SELECT * FROM saved_downloads WHERE project_id=? AND id=? AND kind=?",
                (project_id, identifier, kind),
            ).fetchone()
        if row is None:
            raise ResourceNotFound
        path = self._object_path(row["path"])
        if not path.is_file():
            raise ResourceNotFound
        return DownloadRecord(row["filename"], row["content_type"], (path.read_bytes(),))
