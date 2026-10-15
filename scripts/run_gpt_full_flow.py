#!/usr/bin/env python3
"""Bounded live finalist comparison, isolated from the user's saved reviews."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sci_search.configuration import load_env_file
from sci_search.mistral_analysis import ModelAnalyzer
from sci_search.model_provider import PROFILES, _provider_key
from sci_search.question_interpretation import interpret_question
from sci_search.research_runs import ResearchLimits, ResearchRunManager
from sci_search.scholarly_providers import CrossrefProvider, EuropePmcProvider
from scripts.run_gpt_comparison import DEFAULT_OUTPUT, MeasuredTransport, dump, summarize


class ExhaustedOpenAlex:
    name = "openalex"

    def search(self, query, *, limit):
        # The free rate-limit endpoint confirmed zero allowance before the benchmark.
        # Record unavailability through normal provider diagnostics without spending retries.
        raise HTTPError(
            "https://api.openalex.org/works",
            429,
            "Daily budget exhausted; confirmed by rate-limit preflight",
            {},
            None,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--case", required=True, choices=["language", "health", "biochar"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    load_env_file(ROOT / ".env.local")
    load_env_file(ROOT.parent / "sci-graph/.env.local", allowed_keys=frozenset({"OPENAI_API_KEY"}))
    frozen = json.loads((args.output / "frozen_inputs.json").read_text())
    case = next(c for c in frozen["inputs"].values() if c.get("id") == args.case)
    job = f"full--{args.case}--{args.model}--0"
    result_path = args.output / "results" / (job + ".json")
    if result_path.exists():
        raise SystemExit("Full-flow job already exists; refusing to rerun it silently")
    transport = MeasuredTransport(args.output, _provider_key(PROFILES["openai"]), 15.0)
    analyzer = ModelAnalyzer(
        transport.key,
        provider=PROFILES["openai"],
        model=args.model,
        complete_json=transport.for_job(job),
    )
    start = time.monotonic()
    brief = interpret_question(case["question"], analyzer)
    result = {
        "job": job,
        "model": args.model,
        "stage": "full",
        "case_id": args.case,
        "repeat": 0,
        "brief": brief,
        "provider_limitation": "OpenAlex daily budget exhausted before testing; live Europe PMC and Crossref only.",
    }
    if (
        not str(brief.get("method", "")).startswith("openai_")
        or brief.get("ambiguity") == "material"
    ):
        result.update(status="blocked_interpretation", result=None)
    else:
        limits = ResearchLimits(
            per_query=10,
            max_selected=30,
            max_full_texts=6,
            max_acquisition_attempts=12,
            citation_seed_count=0,
            citation_depth=0,
            review_mode="custom",
            initial_full_texts=6,
        )
        result["limits"] = asdict(limits)
        manager = ResearchRunManager(
            args.output / "full_runs" / job,
            providers=(
                ExhaustedOpenAlex(),
                EuropePmcProvider(),
                CrossrefProvider(email=os.environ.get("CROSSREF_EMAIL")),
            ),
            analyzer=analyzer,
        )
        state = manager.run_sync(case["question"], limits=limits, question_brief=brief)
        result.update(
            status=state["status"],
            run_id=state["run_id"],
            result=state.get("result"),
            error=state.get("error"),
            pipeline_diagnostics=state.get("pipeline_diagnostics"),
        )
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    dump(result_path, result)
    summarize(args.output)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("result", "brief", "pipeline_diagnostics")
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
