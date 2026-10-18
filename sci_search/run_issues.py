"""Local observational issue ledger; never changes scientific decisions or learns rules."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

SCHEMA = "sci_search_run_issues_v1"


@lru_cache(maxsize=1)
def code_fingerprint():
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _items(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Expected a list of diagnostic objects")
    return value


def _validate_ledger(ledger):
    if not isinstance(ledger, dict) or ledger.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported issue ledger schema")
    if not isinstance(ledger.get("run_status", "unknown"), str):
        raise ValueError("Invalid run status")
    for item in _items(ledger.get("issues")):
        for field in ("id", "stream", "category", "evidence_ref", "first_seen", "last_seen"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise ValueError("Invalid issue field")
        if item["stream"] not in {"data", "literature", "run"} or not re.fullmatch(
            r"[a-z_]+", item["category"]
        ):
            raise ValueError("Invalid issue category")
        for field in ("first_seen", "last_seen"):
            if datetime.fromisoformat(item[field]).tzinfo is None:
                raise ValueError("Issue timestamp requires timezone")
        if not isinstance(item.get("code_fingerprints"), list) or not all(
            isinstance(v, str) for v in item["code_fingerprints"]
        ):
            raise ValueError("Invalid code fingerprints")
    return ledger


def observations(state, data):
    """Yield categories and pointers, without copying questions, URLs or source text."""
    for index, item in enumerate(_items(state.get("search_log"))):
        if item.get("status") not in {None, "ok", "skipped"}:
            yield (
                "literature",
                "provider_failure",
                str(item.get("provider")) + str(item.get("query")),
                f"run.json#/search_log/{index}",
            )
    for index, item in enumerate(_items(state.get("acquisitions"))):
        status = item.get("status")
        if status and status != "acquired":
            category = "unreadable_source" if status == "unreadable" else "acquisition_failure"
            yield (
                "literature",
                category,
                str(item.get("publication_id")),
                f"run.json#/acquisitions/{index}",
            )
    for index, item in enumerate(_items(state.get("full_text_screening"))):
        if item.get("decision") == "uncertain":
            yield (
                "literature",
                "screening_uncertain",
                str(item.get("publication_id")),
                f"run.json#/full_text_screening/{index}",
            )
    result = state.get("result") or {}
    adequacy = result.get("answer_adequacy") or {}
    # Data-only investigation also has report fields; do not label it as literature.
    if adequacy and (not data or result.get("evidence") or result.get("pipeline_diagnostics")):
        if adequacy.get("can_answer_overall_question") is False:
            yield "literature", "answer_withheld", "answer", "run.json#/result/answer_adequacy"
    ai = result.get("ai_analysis") or {}
    if ai.get("status") in {"failed", "rejected", "invalid", "error"}:
        yield "literature", "synthesis_rejected", "synthesis", "run.json#/result/ai_analysis"
    if ai.get("status") == "unavailable":
        yield "literature", "synthesis_unavailable", "synthesis", "run.json#/result/ai_analysis"
    if data:
        for index, item in enumerate(_items(data.get("assessments"))):
            if item.get("decision") in {"analysed", "accepted", "duplicate"}:
                continue
            if not (item.get("reason") or item.get("failure_stage")):
                continue
            stage = str(item.get("failure_stage") or "")
            reason = str(item.get("reason") or "").casefold()
            if re.search(r"\bunits?\b", reason) or stage.endswith(":selection"):
                category = "unit_or_selection"
            elif any(word in stage for word in ("meaning", "semantic")):
                category = "meaning_unconfirmed"
            elif any(word in stage for word in ("fetch", "download", "retrieve")):
                category = "retrieval_failure"
            elif any(word in stage for word in ("parse", "normalize", "python")):
                category = "extraction_failure"
            else:
                category = "source_not_accepted"
            identity = str(item.get("url") or item.get("dataset") or item.get("title")) + stage
            yield "data", category, identity, f"data_analysis/analysis.json#/assessments/{index}"
        completion = data.get("output_completion") or {}
        if completion.get("data_status") in {"partial", "blocked", "insufficient"}:
            yield (
                "data",
                "incomplete_data",
                "coverage",
                "data_analysis/analysis.json#/output_completion",
            )
        if completion.get("calculation_status") in {"partial", "blocked", "unsupported"}:
            yield (
                "data",
                "blocked_calculation",
                "calculation",
                "data_analysis/analysis.json#/output_completion",
            )
        if (data.get("run_control") or {}).get("stop_reason"):
            yield "data", "budget_exhausted", "budget", "data_analysis/analysis.json#/run_control"
    if state.get("status") == "failed":
        yield "run", "run_failed", "run", "run.json#/error"
    elif state.get("status") == "cancelled":
        yield "run", "cancelled", "run", "run.json#/status"


def record(directory, state, *, now=None, historical=False):
    """Merge observations idempotently; disappearance is not proof of resolution."""
    directory = Path(directory)
    path = directory / "issues.json"
    now = (
        now
        or (state.get("finished_at") or state.get("created_at") if historical else None)
        or datetime.now(UTC).isoformat()
    )
    ledger = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "schema_version": SCHEMA,
            "run_id": state.get("run_id"),
            "issues": [],
        }
    )
    _validate_ledger(ledger)
    data = (state.get("result") or {}).get("data_analysis")
    data_path = directory / "data_analysis/analysis.json"
    if not data and data_path.is_file():
        data = json.loads(data_path.read_text())
    version = "unknown_historical" if historical else code_fingerprint()
    entries = {item["id"]: item for item in ledger["issues"]}
    for stream, category, identity, pointer in observations(state, data):
        key = hashlib.sha256(json.dumps([stream, category, identity]).encode()).hexdigest()
        item = entries.setdefault(
            key,
            {
                "id": key,
                "stream": stream,
                "category": category,
                "first_seen": now,
                "code_fingerprints": [],
                "resolution": "not_assessed",
                "observation_mode": "historical_backfill" if historical else "live",
            },
        )
        item.update(last_seen=now, evidence_ref=pointer)
        if version not in item["code_fingerprints"]:
            item["code_fingerprints"].append(version)
    ledger.update(issues=list(entries.values()), run_status=state.get("status"), updated_at=now)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def summarize(root, *, since=None):
    """Group observations by stream/category; frequencies count distinct run folders."""
    root = Path(root).resolve()
    groups = {}
    unreadable = []
    scanned = 0
    for path in sorted(root.rglob("issues.json")):
        try:
            ledger = _validate_ledger(json.loads(path.read_text()))
            run = str(path.parent.relative_to(root))
            scanned += 1
            for item in ledger["issues"]:
                if since and datetime.fromisoformat(item["last_seen"]) < since:
                    continue
                key = (item["stream"], item["category"])
                group = groups.setdefault(
                    key,
                    {
                        "stream": key[0],
                        "category": key[1],
                        "runs": {},
                        "observation_count": 0,
                        "examples": [],
                    },
                )
                group["runs"][run] = ledger.get("run_status") or "unknown"
                group["observation_count"] += 1
                if len(group["examples"]) < 5:
                    group["examples"].append(
                        {"run": run, "evidence_ref": item["evidence_ref"], "issue_id": item["id"]}
                    )
        except (OSError, ValueError, KeyError, TypeError):
            unreadable.append(str(path.relative_to(root)))
    results = []
    for group in groups.values():
        runs = group.pop("runs")
        group.update(run_count=len(runs), run_status_counts=dict(Counter(runs.values())))
        results.append(group)
    return {
        "schema_version": "sci_search_issue_report_v1",
        "scanned_runs": scanned,
        "qualification": "Observations are not confirmed bugs. Withholding and cancellation can be correct. Frequency does not establish scientific severity or resolution.",
        "groups": sorted(
            results,
            key=lambda g: (-g["run_count"], -g["observation_count"], g["stream"], g["category"]),
        ),
        "unreadable_ledgers": unreadable,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--since", help="UTC date YYYY-MM-DD; filter by last observation")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Register retained run.json snapshots as historical observations",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error("--root must be an existing directory")
    try:
        since = (
            datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC) if args.since else None
        )
    except ValueError:
        parser.error("--since must be YYYY-MM-DD")
    errors = []
    if args.backfill:
        for path in sorted(args.root.rglob("run.json")):
            if (path.parent / "issues.json").exists():
                continue
            try:
                state = json.loads(path.read_text())
                if not isinstance(state, dict) or not state.get("run_id"):
                    continue
                if state.get("status") in {"pending", "queued", "running", "cancel_requested"}:
                    continue
                record(path.parent, state, historical=True)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                errors.append(str(path.relative_to(args.root)))
    report = summarize(args.root, since=since)
    report["backfill_errors"] = errors
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 1 if errors or report["unreadable_ledgers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
