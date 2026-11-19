"""A small local web app for study plans: one page and a JSON API over the study service."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from sci_search.study.schema import SECTIONS, PlanError
from sci_search.study.service import Busy, Locked, StudyService, model_label

STATIC = Path(__file__).parent / "static"


def _source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        k: item.get(k) for k in ("id", "title", "url", "year", "publisher", "kind", "rationale")
    }


def create_app(service: StudyService) -> FastAPI:
    app = FastAPI(title="Sci-Search study plans", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    store = service.store

    def guarded(action):
        try:
            return action()
        except KeyError as error:
            raise HTTPException(404, "Study or version not found.") from error
        except (Busy, Locked) as error:
            raise HTTPException(409, str(error)) from error
        except (PlanError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(STATIC / "study.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        analyzer = service.analyzer_factory()
        provider = getattr(getattr(analyzer, "provider", None), "name", None)
        return {"model": model_label(analyzer), "datasets": provider in {"openai", "codex"}}

    @app.get("/api/studies")
    def studies() -> list[dict[str, Any]]:
        return [
            {k: s.get(k) for k in ("id", "question", "status", "created_at", "version")}
            for s in store.list()
        ]

    @app.post("/api/studies")
    def create(question: Annotated[str, Body(embed=True)]) -> dict[str, str]:
        return {"id": guarded(lambda: service.start(question))}

    @app.get("/api/studies/{study_id}")
    def detail(study_id: str) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            study = store.get(study_id)
            plan = store.version(study_id, study["version"])["plan"] if study["version"] else None
            scan = store.read_scan(study_id)
            return {
                "study": study,
                "plan": plan,
                "sections": list(SECTIONS),
                "scan_items": {
                    "publications": [_source(p) for p in scan.get("publications") or []],
                    "datasets": [_source(d) for d in scan.get("datasets") or []],
                },
                "scan_steps": scan.get("steps") or [],
            }

        return guarded(load)

    @app.get("/api/studies/{study_id}/versions")
    def versions(study_id: str) -> list[dict[str, Any]]:
        return guarded(lambda: store.versions(study_id))

    @app.get("/api/studies/{study_id}/versions/{number}")
    def version(study_id: str, number: int) -> dict[str, Any]:
        return guarded(lambda: store.version(study_id, number))

    @app.post("/api/studies/{study_id}/revise")
    def revise(
        study_id: str, section: Annotated[str, Body()], instruction: Annotated[str, Body()]
    ) -> dict[str, Any]:
        return guarded(lambda: service.revise(study_id, section, instruction))

    @app.post("/api/studies/{study_id}/edit")
    def edit(
        study_id: str, section: Annotated[str, Body()], value: Annotated[Any, Body()]
    ) -> dict[str, int]:
        return {"version": guarded(lambda: service.edit(study_id, section, value))}

    @app.post("/api/studies/{study_id}/search")
    def search(study_id: str, terms: Annotated[list[str], Body(embed=True)]) -> dict[str, bool]:
        guarded(lambda: service.search_more(study_id, terms))
        return {"started": True}

    @app.post("/api/studies/{study_id}/restore")
    def restore(study_id: str, version: Annotated[int, Body(embed=True)]) -> dict[str, int]:
        return {"version": guarded(lambda: service.restore(study_id, version))}

    @app.post("/api/studies/{study_id}/approve")
    def approve(study_id: str) -> dict[str, bool]:
        guarded(lambda: service.approve(study_id))
        return {"approved": True}

    @app.post("/api/studies/{study_id}/reopen")
    def reopen(study_id: str) -> dict[str, bool]:
        guarded(lambda: service.reopen(study_id))
        return {"approved": False}

    @app.get("/api/studies/{study_id}/plan.md")
    def markdown(study_id: str) -> PlainTextResponse:
        def read() -> str:
            store.get(study_id)
            path = store.root / study_id / "plan.md"
            if not path.is_file():
                raise KeyError(study_id)
            return path.read_text(encoding="utf-8")

        return PlainTextResponse(
            guarded(read),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="study-plan-{study_id}.md"'},
        )

    return app
