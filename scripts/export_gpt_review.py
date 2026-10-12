#!/usr/bin/env python3
"""Export blinded app outputs and raw generations for independent appraisal."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_gpt_comparison import DEFAULT_OUTPUT, dump


def clean(value):
    if isinstance(value, dict):
        return {
            k: clean(v)
            for k, v in value.items()
            if k not in {"model", "provider", "usage", "elapsed_seconds", "method"}
        }
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def main():
    root = DEFAULT_OUTPUT
    references = json.loads((root / "frozen_inputs.json").read_text())["inputs"]
    records = [json.loads(p.read_text()) for p in (root / "results").glob("*.json")]
    calls = [json.loads(p.read_text()) for p in (root / "calls").glob("*.json")]
    random.SystemRandom().shuffle(records)
    groups, key = {}, {}
    for n, record in enumerate(records, 1):
        alias = f"sample-{n:03d}"
        key[alias] = record["job"]
        group = (
            "interpretation"
            if record["stage"] == "interpretation"
            else record["stage"] + "-" + record["case_id"]
        )
        sample = {
            "id": alias,
            "case_id": record["case_id"],
            "status": record["status"],
            "result": clean(record.get("result")),
        }
        raw = []
        for call in sorted(calls, key=lambda c: c["started_at"]):
            if call["job"] != record["job"]:
                continue
            schema = call["request"].get("response_format", {}).get("json_schema", {}).get("name")
            if schema not in ("research_question_brief", "scientific_analysis"):
                continue
            response = call.get("response") or {}
            try:
                content = json.loads(response["choices"][0]["message"]["content"])
                raw.append({"schema": schema, "content": clean(content)})
            except (ValueError, KeyError, IndexError, TypeError):
                raw.append({"schema": schema, "provider_or_format_failure": True})
        sample["raw_generations"] = raw
        groups.setdefault(group, []).append(sample)
    for group, samples in groups.items():
        ref = (
            references["gpt_interpretation_v1.json"]
            if group == "interpretation"
            else next(c for c in references.values() if c.get("id") == group.split("-", 1)[1])
        )
        dump(root / "review" / f"{group}.json", {"reference": ref, "samples": samples})
    dump(root / "review_key.json", key)
    print({group: len(samples) for group, samples in groups.items()})


if __name__ == "__main__":
    main()
