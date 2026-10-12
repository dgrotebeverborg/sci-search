#!/usr/bin/env python3
"""Auditable, resumable GPT comparison using the application's actual prompts.

This benchmark supplies a measured transport; it does not change app defaults.
All inputs are frozen before the first call. Provider failures are kept as results.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sci_search.configuration import load_env_file
from sci_search.mistral_analysis import ModelAnalyzer
from sci_search.model_provider import PROFILES, _provider_key
from sci_search.question_interpretation import interpret_question

MODELS = ("gpt-4.1-mini", "gpt-6-luna", "gpt-6-sol", "gpt-6-astra")
# Standard, short-context USD / million tokens; verified 2026-09-28.
RATES = {
    "gpt-4.1-mini": (0.4, 0.1, 1.6),
    "gpt-6-luna": (0.1, 0.01, 0.5),
    "gpt-6-sol": (2.0, 0.2, 10.0),
    "gpt-6-astra": (10.0, 1.0, 50.0),
}
DEFAULT_OUTPUT = ROOT / "data/benchmark_results/gpt_comparison_20260928"


def request_body(body: dict) -> dict:
    result = copy.deepcopy(body)
    if result["model"].startswith("gpt-6-"):
        result.pop("temperature", None)
        result.pop("max_tokens", None)
        result["max_completion_tokens"] = 8000
        result["reasoning_effort"] = "medium"
    result["store"] = False
    return result


def token_cost(model: str, usage: dict) -> float:
    inp, cached, out = RATES[model]
    n = usage.get("prompt_tokens", 0)
    c = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    w = (usage.get("prompt_tokens_details") or {}).get("cache_write_tokens", 0)
    return (
        (n - c - w) * inp + c * cached + w * inp * 1.25 + usage.get("completion_tokens", 0) * out
    ) / 1e6


def normalized(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def interpretation_checks(case: dict, brief: dict) -> dict[str, bool]:
    checks = {"model_response_used": str(brief.get("method", "")).startswith("openai_")}
    structure = brief.get("research_plan") or {}
    for field, wanted in case["expected"].items():
        if field == "ambiguity":
            checks[field] = brief.get(field) in wanted
        elif field in ("intent", "relationship_type"):
            checks[field] = structure.get(field) in wanted
        elif not wanted:
            checks[field] = structure.get(field) == []
        else:
            actual = normalized(" ".join(structure.get(field) or []))
            checks[field] = all(
                any(normalized(term) in actual for term in alternatives) for alternatives in wanted
            )
    if case["expected"].get("ambiguity") == ["material"]:
        checks["clarification_present"] = bool(brief.get("clarification_question"))
    return checks


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class MeasuredTransport:
    def __init__(self, output: Path, key: str, ceiling: float):
        self.output, self.key, self.ceiling = output, key, ceiling
        self.lock = threading.Lock()
        self.reserved = 0.0
        self.spent = 0.0
        self.unknown = 0
        for path in (output / "calls").glob("*.json"):
            record = json.loads(path.read_text())
            self.spent += record.get("cost_usd") or 0.0
            self.unknown += bool(record.get("billing_unknown"))

    def for_job(self, job: str):
        def complete(body, headers):
            return self.call(job, body)

        return complete

    def call(self, job: str, body: dict) -> dict:
        prepared = request_body(body)
        model = prepared["model"]
        # One token per UTF-8 byte is a conservative input bound; prompts are small.
        input_bound = len(json.dumps(prepared).encode())
        output_bound = prepared.get("max_completion_tokens", prepared.get("max_tokens", 8000))
        reserve = (input_bound * RATES[model][0] * 1.25 + output_bound * RATES[model][2]) / 1e6
        with self.lock:
            if self.unknown or self.spent + self.reserved + reserve > self.ceiling:
                raise RuntimeError("Benchmark cost ceiling or unknown billing requires stopping")
            self.reserved += reserve
        call_id = uuid.uuid4().hex
        record = {
            "id": call_id,
            "job": job,
            "request": prepared,
            "started_at": datetime.now(UTC).isoformat(),
            "billing_unknown": True,
        }
        start = time.monotonic()
        try:
            response = httpx.post(
                PROFILES["openai"].endpoint,
                json=prepared,
                headers={"Authorization": "Bearer " + self.key},
                timeout=180,
            )
            record["http_status"] = response.status_code
            payload = response.json()
            if response.is_success:
                record["response"] = payload
                record["usage"] = payload.get("usage", {})
                if not isinstance(record["usage"], dict) or not all(
                    isinstance(record["usage"].get(k), int) and record["usage"][k] >= 0
                    for k in ("prompt_tokens", "completion_tokens")
                ):
                    raise ValueError("Successful response omitted verified token usage")
                record["cost_usd"] = token_cost(model, record["usage"])
                record["billing_unknown"] = False
            else:
                error = payload.get("error") or {}
                record["error"] = {k: error.get(k) for k in ("code", "type", "param", "message")}
                record["cost_usd"] = 0.0
                record["billing_unknown"] = False
                raise ValueError(f"Provider HTTP {response.status_code}: {error.get('code')}")
            return payload
        except (httpx.TransportError, json.JSONDecodeError) as exc:
            record["error"] = type(exc).__name__
            record["billing_unknown"] = True
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - start, 3)
            with self.lock:
                self.reserved -= reserve
                self.spent += record.get("cost_usd") or 0.0
                self.unknown += bool(record.get("billing_unknown"))
                dump(self.output / "calls" / (call_id + ".json"), record)


def freeze(output: Path) -> dict:
    paths = [ROOT / "benchmarks/gpt_interpretation_v1.json"]
    paths += sorted((ROOT / "benchmarks").glob("gpt_*_reference_v1.json"))
    inputs = {p.name: json.loads(p.read_text()) for p in paths}
    checksum = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    path = output / "frozen_inputs.json"
    if path.exists():
        existing = json.loads(path.read_text())
        if existing["sha256"] != checksum:
            raise SystemExit("Reference inputs changed after freeze; use a new output directory")
        return existing
    code_files = [
        "sci_search/question_interpretation.py",
        "sci_search/mistral_analysis.py",
        "sci_search/claim_support.py",
        "scripts/run_gpt_comparison.py",
    ]
    result = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "sha256": checksum,
        "inputs": inputs,
        "model_rates": RATES,
        "code_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in code_files},
        "limitations": [
            "AI-authored silver reference; no independent human scientific validation.",
            "Small exploratory benchmark, not a population-level ranking.",
            "Reasoning models use medium effort and 8000 completion-token cap; baseline uses its app defaults.",
            "Fixed-paper synthesis uses identical packets; full search uses independently retrieved evidence.",
        ],
    }
    dump(path, result)
    return result


def run_job(job, transport, output):
    job_id, model, stage, case, repeat = job
    path = output / "results" / (job_id + ".json")
    if path.exists():
        return json.loads(path.read_text())
    analyzer = ModelAnalyzer(
        transport.key,
        provider=PROFILES["openai"],
        model=model,
        complete_json=transport.for_job(job_id),
    )
    record = {
        "job": job_id,
        "model": model,
        "stage": stage,
        "case_id": case["id"],
        "repeat": repeat,
    }
    start = time.monotonic()
    try:
        if stage == "interpretation":
            record["result"] = interpret_question(case["question"], analyzer)
            record["checks"] = interpretation_checks(case, record["result"])
        else:
            # Same records, in the same order, for every model and repeat.
            record["result"] = analyzer.analyze(case["question"], case["evidence"])
        record["status"] = "returned"
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__)
    record["elapsed_seconds"] = round(time.monotonic() - start, 3)
    dump(path, record)
    return record


def summarize(output: Path):
    records = [json.loads(p.read_text()) for p in sorted((output / "results").glob("*.json"))]
    calls = [json.loads(p.read_text()) for p in (output / "calls").glob("*.json")]
    summary = []
    for stage in sorted({r["stage"] for r in records}):
        for model in MODELS:
            subset = [r for r in records if r["stage"] == stage and r["model"] == model]
            if not subset:
                continue
            jobs = {r["job"] for r in subset}
            usage = [c for c in calls if c["job"] in jobs]
            checks = [v for r in subset for v in r.get("checks", {}).values()]
            row = {
                "stage": stage,
                "model": model,
                "jobs": len(subset),
                "failures": sum(r["status"] == "failed" for r in subset),
                "cost_usd": round(sum(c.get("cost_usd", 0) for c in usage), 6),
                "call_seconds": round(sum(c["elapsed_seconds"] for c in usage), 2),
                "input_tokens": sum(c.get("usage", {}).get("prompt_tokens", 0) for c in usage),
                "output_tokens": sum(c.get("usage", {}).get("completion_tokens", 0) for c in usage),
            }
            if checks:
                row.update(
                    checks_passed=sum(checks),
                    checks_total=len(checks),
                    cases_all_checks_passed=sum(
                        bool(r.get("checks")) and all(r["checks"].values()) for r in subset
                    ),
                )
            if stage == "full":
                analyses = [(r.get("result") or {}).get("ai_analysis") or {} for r in subset]
                row.update(
                    completed_runs=sum(r["status"] == "complete" for r in subset),
                    synthesis_unavailable=sum(a.get("status") == "unavailable" for a in analyses),
                    runs_with_evidence=sum(
                        bool((r.get("result") or {}).get("evidence")) for r in subset
                    ),
                    synthesis_generation_calls=sum(
                        c["request"].get("response_format", {}).get("json_schema", {}).get("name")
                        == "scientific_analysis"
                        for c in usage
                    ),
                )
            summary.append(row)
    dump(output / "summary.json", summary)
    return summary


def blind(output: Path, frozen: dict):
    records = [json.loads(p.read_text()) for p in sorted((output / "results").glob("*.json"))]
    random.SystemRandom().shuffle(records)
    mapping, packets = {}, []
    cases = {}
    for name, value in frozen["inputs"].items():
        if name == "gpt_interpretation_v1.json":
            cases.update({c["id"]: c for c in value["cases"]})
        else:
            cases[value["id"]] = value
    for i, r in enumerate(records):
        alias = f"sample-{i + 1:03d}"
        mapping[alias] = r["job"]
        result = copy.deepcopy(r.get("result"))
        if isinstance(result, dict):
            for key in ("model", "provider", "usage", "elapsed_seconds", "method"):
                result.pop(key, None)
        packets.append(
            {
                "sample": alias,
                "stage": r["stage"],
                "case_id": r["case_id"],
                "status": r["status"],
                "result": result,
            }
        )
    dump(output / "blind_key.json", mapping)
    dump(output / "blind_review.json", {"references": cases, "samples": packets})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stage", choices=["interpretation", "fixed", "all"], default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--ceiling", type=float, default=15.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    frozen = freeze(args.output)
    if args.freeze_only:
        print("Inputs frozen:", frozen["sha256"])
        return
    load_env_file(ROOT / ".env.local")
    load_env_file(ROOT.parent / "sci-graph/.env.local", allowed_keys=frozenset({"OPENAI_API_KEY"}))
    key = _provider_key(PROFILES["openai"])
    if not key:
        raise SystemExit("OpenAI key unavailable")
    transport = MeasuredTransport(args.output, key, args.ceiling)
    jobs = []
    for name, value in frozen["inputs"].items():
        stage = "interpretation" if name == "gpt_interpretation_v1.json" else "fixed"
        if args.stage not in (stage, "all"):
            continue
        cases = value["cases"] if stage == "interpretation" else [value]
        for case in cases:
            for model in MODELS:
                for repeat in range(args.repeats):
                    job = f"{stage}--{case['id']}--{model}--{repeat}"
                    jobs.append((job, model, stage, case, repeat))
    random.Random(20260928).shuffle(jobs)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_job, job, transport, args.output) for job in jobs]
        for n, future in enumerate(as_completed(futures), 1):
            result = future.result()
            print(
                f"{n}/{len(jobs)} {result['job']} {result['status']} cost=${transport.spent:.4f}",
                flush=True,
            )
    summarize(args.output)
    blind(args.output, frozen)


if __name__ == "__main__":
    main()
