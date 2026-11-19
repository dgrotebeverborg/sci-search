"""Study folders on disk: status, scan, immutable plan versions and a readable export."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[0-9a-f]{12}$")
_HEADINGS = {
    "question": "Question as understood",
    "definitions": "Definitions",
    "subquestions": "Sub-questions",
    "scope": "Scope and assumptions",
    "out_of_reach": "Out of reach",
    "existing_work": "Existing studies and models",
    "data": "Data",
    "chapters": "Chapters",
    "limits": "Limits of this plan",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StudyStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Status and progress are written from the background thread and the web requests.
        self._lock = threading.RLock()

    def _folder(self, study_id: str) -> Path:
        if not isinstance(study_id, str) or not _ID.match(study_id):
            raise KeyError(study_id)
        folder = self.root / study_id
        if not (folder / "study.json").is_file():
            raise KeyError(study_id)
        return folder

    def _write(self, path: Path, data: Any) -> None:
        text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(text)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _read(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, question: str, model: str | None) -> str:
        study_id = uuid.uuid4().hex[:12]
        folder = self.root / study_id
        folder.mkdir()
        now = _now()
        self._write(
            folder / "study.json",
            {
                "id": study_id,
                "question": question,
                "status": "scanning",
                "version": 0,
                "approved_version": None,
                "model": model,
                "progress": [],
                "error": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        return study_id

    def get(self, study_id: str) -> dict[str, Any]:
        return self._read(self._folder(study_id) / "study.json")

    def list(self) -> list[dict[str, Any]]:
        studies = []
        for folder in self.root.iterdir():
            if _ID.match(folder.name) and (folder / "study.json").is_file():
                studies.append(self._read(folder / "study.json"))
        return sorted(studies, key=lambda s: s["created_at"], reverse=True)

    def update(self, study_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            study = {**self.get(study_id), **fields, "updated_at": _now()}
            self._write(self._folder(study_id) / "study.json", study)
            return study

    def add_progress(self, study_id: str, message: str) -> None:
        with self._lock:
            progress = [*self.get(study_id)["progress"], {"at": _now(), "message": message}]
            self.update(study_id, progress=progress[-50:])

    def write_scan(self, study_id: str, scan: dict[str, Any]) -> None:
        self._write(self._folder(study_id) / "scan.json", scan)

    def read_scan(self, study_id: str) -> dict[str, Any]:
        path = self._folder(study_id) / "scan.json"
        return self._read(path) if path.is_file() else {}

    def add_version(
        self, study_id: str, plan: dict[str, Any], origin: str, section: str | None
    ) -> int:
        with self._lock:
            folder = self._folder(study_id)
            number = self.get(study_id)["version"] + 1
            path = folder / f"plan-v{number}.json"
            if path.exists():
                raise FileExistsError(path)
            self._write(
                path,
                {
                    "version": number,
                    "origin": origin,
                    "section": section,
                    "created_at": _now(),
                    "plan": plan,
                },
            )
            study = self.update(study_id, version=number)
            self._write(
                folder / "plan.md",
                render_markdown(study["question"], plan, self.read_scan(study_id)),
            )
            return number

    def version(self, study_id: str, number: int) -> dict[str, Any]:
        path = self._folder(study_id) / f"plan-v{int(number)}.json"
        if not path.is_file():
            raise KeyError(number)
        return self._read(path)

    def versions(self, study_id: str) -> list[dict[str, Any]]:
        folder = self._folder(study_id)
        items = []
        for number in range(1, self.get(study_id)["version"] + 1):
            path = folder / f"plan-v{number}.json"
            if path.is_file():
                record = self._read(path)
                items.append({k: record[k] for k in ("version", "origin", "section", "created_at")})
        return items


def render_markdown(question: str, plan: dict[str, Any], scan: dict[str, Any]) -> str:
    sources = {
        str(item.get("id")): item
        for pool in ("publications", "datasets")
        for item in scan.get(pool) or []
    }

    def source(scan_id: str) -> str:
        item = sources.get(scan_id) or {}
        title = item.get("title") or scan_id
        return f"[{title}]({item['url']})" if item.get("url") else str(title)

    lines = [f"# Study plan: {question}", ""]
    for section, heading in _HEADINGS.items():
        value = plan.get(section)
        lines += [f"## {heading}", ""]
        if section == "question":
            lines.append(str(value or ""))
        elif section == "definitions":
            lines += [f"- **{d['term']}**: {d['definition']}" for d in value or []]
        elif section == "subquestions":
            lines += [f"- {q['id']}. {q['text']}" for q in value or []]
        elif section == "out_of_reach":
            lines += [f"- {o['item']} — {o['reason']}" for o in value or []]
        elif section == "existing_work":
            lines += [f"- {source(w['scan_id'])}: {w['why']}" for w in value or []]
        elif section == "data":
            lines += [f"- {source(d['scan_id'])}: {d['provides']}" for d in value or []]
        elif section == "chapters":
            for number, chapter in enumerate(value or [], 1):
                lines += [
                    f"### {number}. {chapter['title']} ({chapter['method']})",
                    "",
                    f"Goal: {chapter['goal']}",
                    f"Answers: {', '.join(chapter['answers'])}",
                    f"Output: {chapter['output']}",
                    "",
                ]
        else:
            lines += [f"- {item}" for item in value or []]
        if not value:
            lines.append("_None._")
        lines.append("")
    return "\n".join(lines)
