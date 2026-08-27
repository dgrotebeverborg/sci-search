"""Command-line entry point for the first Sci-Search vertical slice."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from sci_search.comparison import comparison_report
from sci_search.configuration import load_env_file, load_legacy_mistral_key
from sci_search.corpus import load_corpus
from sci_search.discovery_evaluation import evaluate_discovery
from sci_search.evaluation import evaluate_results
from sci_search.generic_evaluation import evaluate_generic
from sci_search.generic_reporting import (
    render_generic_html,
    render_generic_json,
    render_generic_markdown,
)
from sci_search.generic_research import GenericResearchEngine
from sci_search.investigation import investigate
from sci_search.models import dataclass_to_dict
from sci_search.pipeline import build_evidence_store
from sci_search.reporting import render_html, render_json, render_markdown
from sci_search.research_runs import REVIEW_PROFILES, ResearchLimits, ResearchRunManager
from sci_search.scientific_memory import ScientificMemory
from sci_search.web import CorpusCatalogService, run_server


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file(Path(".env.local"))
    parser = argparse.ArgumentParser(
        description="Build and query a local scientific evidence corpus"
    )
    parser.add_argument("--corpus", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare = subparsers.add_parser("compare", help="compare contextual measurements")
    compare.add_argument("--metric", default="round_trip_efficiency")
    export = subparsers.add_parser("export", help="write an evidence or graph artifact")
    export.add_argument("--format", choices=("evidence", "graph"), default="evidence")
    export.add_argument("--output", type=Path, required=True)
    evaluate = subparsers.add_parser("evaluate", help="evaluate extraction against a gold fixture")
    evaluate.add_argument("--gold", type=Path, required=True)
    evaluate_generic_parser = subparsers.add_parser(
        "evaluate-generic", help="evaluate generic retrieval and grounding"
    )
    evaluate_generic_parser.add_argument("--gold", type=Path, required=True)
    research = subparsers.add_parser(
        "investigate", help="answer a scientific question with a traceable report"
    )
    research.add_argument("--question", required=True)
    research.add_argument("--format", choices=("json", "markdown", "html"), default="markdown")
    research.add_argument("--output", type=Path)
    serve = subparsers.add_parser("serve", help="run the researcher web interface")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    serve.add_argument("--additional-corpus", action="append", type=Path, default=[])
    online = subparsers.add_parser(
        "research-online", help="discover, acquire and analyze an online evidence corpus"
    )
    online.add_argument("--question", required=True)
    online.add_argument("--review-mode", choices=("quick", "research", "deep"), default="research")
    online.add_argument("--per-query", type=int)
    online.add_argument("--max-full-texts", type=int)
    online.add_argument("--max-acquisition-attempts", type=int)
    online.add_argument("--output", type=Path)
    discovery_eval = subparsers.add_parser(
        "evaluate-discovery", help="measure discovery recall against a curated bibliography"
    )
    discovery_eval.add_argument("--discovery", type=Path, required=True)
    discovery_eval.add_argument("--gold", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "evaluate-discovery":
        report = evaluate_discovery(args.discovery, args.gold)
        payload = dataclass_to_dict(report)
        payload["passed"] = report.passed
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if report.passed else 1

    if args.command == "evaluate-generic":
        report = evaluate_generic(GenericResearchEngine(load_corpus(args.corpus)), args.gold)
        payload = dataclass_to_dict(report)
        payload["passed"] = report.passed
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if report.passed else 1

    if args.command == "research-online":
        load_legacy_mistral_key(Path("."))
        memory = ScientificMemory(Path("data/scientific_memory"))
        memory.bootstrap_runs(Path("data/research_runs"))
        manager = ResearchRunManager(Path("data/research_runs"), memory=memory)
        profile = REVIEW_PROFILES[args.review_mode]
        maximum = args.max_full_texts or profile["maximum"]
        limits = ResearchLimits(
            per_query=args.per_query or profile["per_query"],
            max_full_texts=maximum,
            max_acquisition_attempts=args.max_acquisition_attempts
            or max(maximum, profile["attempts"]),
            review_mode=args.review_mode,
            initial_full_texts=profile["initial"],
            acquisition_batch_size=profile["batch"],
        )
        state = manager.run_sync(args.question, limits=limits)
        rendered = json.dumps(state, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0 if state["status"] == "complete" else 1

    store, warnings = build_evidence_store(args.corpus)
    if args.command == "compare":
        payload = comparison_report(store.query_results(args.metric))
        payload["pipeline_warnings"] = list(warnings)
        payload["corpus_notice"] = _corpus_notice(store)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "export":
        payload = (
            store.to_graph_artifact() if args.format == "graph" else store.to_evidence_artifact()
        )
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return 0
    if args.command == "evaluate":
        report = evaluate_results(
            store.query_results("round_trip_efficiency"), args.gold, args.corpus
        )
        payload = dataclass_to_dict(report)
        payload["passed"] = report.passed
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if report.passed else 1
    if args.command == "investigate":
        normalized = " ".join(args.question.lower().replace("-", " ").split())
        specialist = ("round trip efficien" in normalized or "rte" in normalized.split()) and bool(
            store.query_results("round_trip_efficiency")
        )
        if specialist:
            report = investigate(args.question, store)
            if args.format == "json":
                rendered = render_json(report)
            elif args.format == "html":
                rendered = render_html(
                    report, corpus_directory=args.corpus, output_path=args.output
                )
            else:
                rendered = render_markdown(report, corpus_directory=args.corpus)
        else:
            generic = GenericResearchEngine(load_corpus(args.corpus)).investigate(args.question)
            if args.format == "json":
                rendered = render_generic_json(generic)
            elif args.format == "html":
                rendered = render_generic_html(generic, args.corpus)
            else:
                rendered = render_generic_markdown(generic, args.corpus)
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered)
        return 0
    if args.command == "serve":
        load_legacy_mistral_key(Path("."))
        if os.environ.get("OPENALEX_API_KEY"):
            memory = ScientificMemory(Path("data/scientific_memory"))
            memory.bootstrap_runs(Path("data/research_runs"))
            for corpus in (args.corpus, *args.additional_corpus):
                memory.bootstrap_corpus(corpus, corpus_id=corpus.name)
            run_manager = ResearchRunManager(Path("data/research_runs"), memory=memory)
        else:
            run_manager = None
        service = CorpusCatalogService(
            (args.corpus, *args.additional_corpus), run_manager=run_manager
        )
        run_server(args.host, args.port, service)
        return 0
    return 2


def _corpus_notice(store: object) -> str | None:
    publications = getattr(store, "publications", {}).values()
    if publications and all(
        publication.fixture_status == "synthetic" for publication in publications
    ):
        return (
            "Synthetic fixtures demonstrate software behavior; values are not literature evidence."
        )
    return None


if __name__ == "__main__":
    raise SystemExit(main())
