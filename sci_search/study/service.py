"""Study actions: background scans, plan versions, approval, and one piece of model work at a time."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from sci_search.study.planner import edit_plan, revise_plan, write_plan
from sci_search.study.scan import extend_scan, run_scan
from sci_search.study.store import StudyStore

MAX_QUESTION = 2000
INTERRUPTED = "Interrupted; start the plan again."


class Busy(RuntimeError):
    """Another scan or revision is running."""


class Locked(RuntimeError):
    """The plan is approved; reopen it to change it."""


def _default_analyzer():
    from sci_search.model_provider import configured_analyzer

    return configured_analyzer()


def model_label(analyzer) -> str | None:
    if analyzer is None:
        return None
    provider = getattr(getattr(analyzer, "provider", None), "name", None)
    return " · ".join(str(p) for p in (provider, analyzer.model) if p)


class StudyService:
    def __init__(
        self,
        store: StudyStore,
        *,
        analyzer_factory: Callable[[], Any] = _default_analyzer,
        scan: Callable[..., dict[str, Any]] = run_scan,
        extend: Callable[..., dict[str, Any]] = extend_scan,
        background: bool = True,
    ) -> None:
        self.store = store
        self.analyzer_factory = analyzer_factory
        self.scan = scan
        self.extend = extend
        self.background = background
        self._work = threading.Lock()
        self._thread: threading.Thread | None = None

    def recover(self) -> None:
        for study in self.store.list():
            if study["status"] == "scanning" or study.get("working"):
                self.store.update(
                    study["id"],
                    status="failed" if study["status"] == "scanning" else study["status"],
                    working=False,
                    error=INTERRUPTED,
                )

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _analyzer(self):
        analyzer = self.analyzer_factory()
        if analyzer is None:
            raise ValueError("No AI model is configured.")
        return analyzer

    def _claim(self) -> None:
        if not self._work.acquire(blocking=False):
            raise Busy("Another study is being worked on; wait until it has finished.")

    def _run(self, job: Callable[[], None]) -> None:
        """Runs a claimed job inline or in the background and always releases the claim."""

        def wrapped() -> None:
            try:
                job()
            finally:
                self._work.release()

        if self.background:
            self._thread = threading.Thread(target=wrapped, daemon=True)
            self._thread.start()
        else:
            wrapped()

    def _editable(self, study_id: str) -> dict[str, Any]:
        study = self.store.get(study_id)
        if study["status"] == "approved":
            raise Locked("The plan is approved. Reopen it to change it.")
        if not study["version"]:
            raise ValueError("This study has no plan yet.")
        return study

    def _plan(self, study_id: str) -> dict[str, Any]:
        return self.store.version(study_id, self.store.get(study_id)["version"])["plan"]

    def start(self, question: str) -> str:
        question = " ".join(str(question or "").split())
        if not question:
            raise ValueError("Enter a research question.")
        if len(question) > MAX_QUESTION:
            raise ValueError(f"Keep the question under {MAX_QUESTION} characters.")
        analyzer = self._analyzer()
        self._claim()
        try:
            study_id = self.store.create(question, model_label(analyzer))
        except BaseException:
            self._work.release()
            raise

        def job() -> None:
            try:
                self.store.update(study_id, working=True)
                scan = self.scan(question, progress=lambda m: self.store.add_progress(study_id, m))
                self.store.write_scan(study_id, scan)
                self.store.add_progress(study_id, "Writing the study plan.")
                plan, _notes = write_plan(question, scan, analyzer)
                self.store.add_version(study_id, plan, "initial", None)
                self.store.update(study_id, status="draft", working=False, error=None)
                self.store.add_progress(study_id, "Study plan ready.")
            except Exception as error:  # the study records any failure for the page
                self.store.update(study_id, status="failed", working=False, error=str(error))

        self._run(job)
        return study_id

    def revise(self, study_id: str, section: str, instruction: str) -> dict[str, Any]:
        self._editable(study_id)
        analyzer = self._analyzer()
        self._claim()
        try:
            plan, changed = revise_plan(
                self._plan(study_id), section, instruction, self.store.read_scan(study_id), analyzer
            )
            version = self.store.add_version(
                study_id, plan, f"instruction: {instruction.strip()}", section
            )
            self.store.update(study_id, notice=None)
            return {"version": version, "changed": changed}
        finally:
            self._work.release()

    def edit(self, study_id: str, section: str, value: Any) -> int:
        self._editable(study_id)
        plan = edit_plan(self._plan(study_id), section, value, self.store.read_scan(study_id))
        return self.store.add_version(study_id, plan, "edit", section)

    def search_more(self, study_id: str, terms: list[str]) -> None:
        self._editable(study_id)
        terms = [str(t).strip() for t in terms or [] if str(t).strip()]
        if not terms:
            raise ValueError("Give at least one search term.")
        self._claim()

        def job() -> None:
            try:
                self.store.update(study_id, working=True, error=None, notice=None)
                before = self.store.read_scan(study_id)
                scan = self.extend(
                    before, terms, progress=lambda m: self.store.add_progress(study_id, m)
                )
                self.store.write_scan(study_id, scan)
                papers = len(scan.get("publications") or []) - len(before.get("publications") or [])
                sets = len(scan.get("datasets") or []) - len(before.get("datasets") or [])
                notice = (
                    f"Extra search found {papers} new publication{'' if papers == 1 else 's'} "
                    f"and {sets} new dataset{'' if sets == 1 else 's'}. "
                    "Ask for a change in a section to use them."
                )
                self.store.add_progress(study_id, notice)
                self.store.update(study_id, working=False, notice=notice)
            except Exception as error:  # recorded for the page; the plan is unchanged
                self.store.update(study_id, working=False, error=str(error))

        self._run(job)

    def restore(self, study_id: str, number: int) -> int:
        self._editable(study_id)
        plan = self.store.version(study_id, number)["plan"]
        return self.store.add_version(study_id, plan, f"restore v{int(number)}", None)

    def approve(self, study_id: str) -> None:
        study = self._editable(study_id)
        self.store.update(study_id, status="approved", approved_version=study["version"])

    def reopen(self, study_id: str) -> None:
        if self.store.get(study_id)["status"] != "approved":
            raise ValueError("Only an approved plan can be reopened.")
        self.store.update(study_id, status="draft", approved_version=None)
