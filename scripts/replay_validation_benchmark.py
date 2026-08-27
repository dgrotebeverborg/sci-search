#!/usr/bin/env python3
"""Replay the ten validation cases with current deterministic pipeline code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sci_search.research_runs import ResearchRunManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1", help="Immutable replay version directory")
    parser.add_argument(
        "--force", action="store_true", help="Replace an incomplete existing replay"
    )
    args = parser.parse_args()
    destination_root = ROOT / "data" / "validation_replays" / args.version
    specification = json.loads(
        (ROOT / "benchmarks" / "researcher_validation_v1.json").read_text(encoding="utf-8")
    )
    code_fingerprint = _code_fingerprint()
    manifest = {
        "schema_version": "sci_search_validation_replay_manifest_v1",
        "version": args.version,
        "created_at": datetime.now(UTC).isoformat(),
        "code_fingerprint": code_fingerprint,
        "model_policy": "deterministic replay; external generative analysis disabled",
        "source_runs_immutable": True,
        "cases": [],
    }
    destination_root.mkdir(parents=True, exist_ok=True)
    previous_key = os.environ.pop("MISTRAL_API_KEY", None)
    try:
        for case in specification["cases"]:
            run_id = str(case["baseline_run_id"])
            source = ROOT / "data" / "benchmark_runs" / run_id
            destination = destination_root / run_id
            if not source.is_dir():
                raise FileNotFoundError(source)
            if destination.exists() and args.force:
                shutil.rmtree(destination)
            if not destination.exists():
                _copy_run_snapshot(source, destination)
                manager = ResearchRunManager(
                    destination_root, providers=(), openalex_api_key="offline-replay"
                )
                manager._rebuild_evidence(run_id)
            state_path = destination / "run.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            manifest["cases"].append(
                {
                    "case_id": case["id"],
                    "run_id": run_id,
                    "source_run_sha256": _sha256(source / "run.json"),
                    "replay_run_sha256": _sha256(state_path),
                    "full_texts_acquired": len(
                        [
                            item
                            for item in state.get("acquisitions", [])
                            if item.get("status") == "acquired"
                        ]
                    ),
                    "full_texts_included": (state.get("progress") or {}).get("full_texts_included"),
                    "evidence_passages": len((state.get("result") or {}).get("evidence", [])),
                    "answer_status": ((state.get("result") or {}).get("answer_adequacy") or {}).get(
                        "status"
                    ),
                }
            )
            print(f"replayed {case['id']} ({run_id})")
    finally:
        if previous_key is not None:
            os.environ["MISTRAL_API_KEY"] = previous_key
    temporary = destination_root / "replay-manifest.json.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(destination_root / "replay-manifest.json")
    print(f"manifest: {destination_root / 'replay-manifest.json'}")
    return 0


def _copy_run_snapshot(source: Path, destination: Path) -> None:
    """Hard-link immutable documents, but copy every mutable metadata artifact."""

    def copy(source_name: str, destination_name: str) -> str:
        source_path = Path(source_name)
        destination_path = Path(destination_name)
        if (
            source_path.suffix.lower() in {".pdf", ".xml", ".nxml", ".txt", ".md"}
            and "papers" in source_path.parts
        ):
            os.link(source_path, destination_path)
            return str(destination_path)
        return shutil.copy2(source_path, destination_path)

    shutil.copytree(source, destination, copy_function=copy)


def _code_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "sci_search").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
