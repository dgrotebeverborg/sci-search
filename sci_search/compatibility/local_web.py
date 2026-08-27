"""Temporary explicit adapter for the pre-FastAPI local researcher interface."""

from __future__ import annotations

import os
from pathlib import Path

from sci_search.research_runs import ResearchRunManager
from sci_search.scientific_memory import ScientificMemory
from sci_search.web import CorpusCatalogService, run_server


def run_legacy_local_web(host: str, port: int, corpora: tuple[Path, ...]) -> None:
    if os.environ.get("OPENALEX_API_KEY"):
        memory = ScientificMemory(Path("data/scientific_memory"))
        memory.bootstrap_runs(Path("data/research_runs"))
        for corpus in corpora:
            memory.bootstrap_corpus(corpus, corpus_id=corpus.name)
        run_manager = ResearchRunManager(Path("data/research_runs"), memory=memory)
    else:
        run_manager = None
    service = CorpusCatalogService(corpora, run_manager=run_manager)
    run_server(host, port, service)
