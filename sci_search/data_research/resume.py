"""Resume only a matching, intact research snapshot into a fresh directory."""

import json
import shutil
from pathlib import Path

from sci_search.data_research.artifact_validation import validate_artifacts
from sci_search.data_research.strategy import validate_strategy


def prepare(source, destination, question, strategy):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if (
        destination == source
        or destination.is_relative_to(source)
        or (destination.exists() and any(destination.iterdir()))
    ):
        raise ValueError("Resume requires a fresh destination outside the original run")
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Resume source contains a symlink")
    saved = source / "checkpoint.json"
    if not saved.exists():
        saved = source / "analysis.json"
    state = json.loads(saved.read_text())
    if state.get("question") != question or state.get("strategy") != validate_strategy(strategy):
        raise ValueError("Resume question or scope differs from the retained investigation")
    for key in ("analyses", "assessments"):
        for item in state.get("connector_checkpoint", {}).get(key, []):
            if item not in state[key]:
                state[key].append(item)
    folders = list(source.glob("source-*")) + list(source.glob("connectors/connector-*"))
    retained = []
    for folder in folders:
        if not (folder / "analysis.json").exists():
            continue
        analysis = json.loads((folder / "analysis.json").read_text())
        if analysis.get("execution", {}).get("status") != "verified":
            continue
        artifacts = analysis["execution"].get("artifacts")
        if not artifacts:
            raise ValueError("Resume source has no sealed artifacts")
        validate_artifacts(folder, artifacts)
        executed = json.loads((folder / "calculation/output/result.json").read_text())
        if executed != {k: v for k, v in analysis.items() if k != "execution"}:
            raise ValueError("Resume analysis differs from executed artifact")
        retained.append(analysis)
    if any(a not in retained for a in state["analyses"]):
        raise ValueError("Resume source is missing a checked analysis artifact")
    for analysis in retained:
        if analysis not in state["analyses"]:
            state["analyses"].append(analysis)
    derived = state.get("derived_outputs", {}).get("execution", {})
    if derived.get("status") == "verified":
        validate_artifacts(
            source,
            {
                derived["directory"] + "/" + name: expected
                for name, expected in derived.get("artifacts", {}).items()
            },
        )
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return state


def main():
    import argparse

    from sci_search.configuration import load_env_file
    from sci_search.data_research.workflow import execute

    parser = argparse.ArgumentParser(
        description="Resume a retained data investigation into a fresh directory"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    load_env_file(Path(".env.local"))
    saved = args.source / "checkpoint.json"
    if not saved.exists():
        saved = args.source / "analysis.json"
    state = json.loads(saved.read_text())
    result = execute(
        state["question"], state["strategy"], args.destination, resume_from=args.source
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "analyses": len(result["analyses"]),
                "remaining_combinations": len(result["coverage"]["gaps"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
