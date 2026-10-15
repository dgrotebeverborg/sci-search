"""Execute a bounded reviewer decision against retained bytes and observed documentation."""

import http.client
import json
from pathlib import Path

from sci_search.data_research.artifacts import execute_analysis
from sci_search.data_research.coverage import evaluate as evaluate_coverage
from sci_search.data_research.coverage import planning_summary
from sci_search.data_research.execution import digest, run_python
from sci_search.data_research.python_recovery import INSPECT_CODE, recover
from sci_search.data_research.retrieval import inspect_page


def inherit_context(candidate, assessments, retained):
    """Only carry evidence along an observed parent-to-download link, never by host."""
    for index, assessment in enumerate(assessments):
        if (
            assessment.get("url") == candidate.get("recovery_from")
            and candidate["url"] in assessment.get("recovery_links", [])
            and index in retained
        ):
            record = retained[index]
            return record["metadata"], [assessment["url"]]
    return "", []


def save_context(folder, record):
    """Persist source evidence independently of extraction success; never persist raw bytes here."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "source-context.json").write_text(
        json.dumps({k: v for k, v in record.items() if k != "body"}, ensure_ascii=False, indent=2)
    )


def execution_summary(folder):
    """Small factual snapshot for the next decision; never executable instructions."""
    root = Path(folder) / "python"
    result = {}
    inspection = root / "inspection/output/inspection.json"
    if inspection.exists():
        result["inspection"] = inspection.read_text()[:20000]
    reviews = sorted(root.glob("attempt-*/semantic-review.json"))
    if reviews:
        result["semantic_review"] = json.loads(reviews[-1].read_text())
    attempts = sorted(root.glob("attempt-*/validation.json"))
    if attempts:
        attempt = attempts[-1].parent
        result["last_validation"] = json.loads(attempts[-1].read_text())
        result["last_code"] = (attempt / "script.py").read_text()[:12000]
        result["decisions"] = [
            json.loads(p.read_text()) for p in sorted(root.glob("attempt-*/reflection.json"))
        ]
    return result


def reassess_source(
    index,
    measurements,
    link_index,
    round_number,
    *,
    retained,
    result,
    question,
    scope,
    directory,
    fetch,
    complete,
    progress,
    check_cancelled,
    knowledge_dir=None,
):
    source_record = retained.get(index)
    if source_record is None:
        raise ValueError("No downloaded source bytes are available for reassessment")
    assessment = result["assessments"][index]
    already_retained = {
        s["label"]
        for a in result["analyses"]
        if a["source"]["sha256"] == digest(source_record["body"])
        for s in a.get("series", [])
    }
    has_explicit_scope = any(
        scope.get(k) for k in ("geography", "countries", "requirements", "start_year", "end_year")
    )
    coverage = evaluate_coverage(scope, result["analyses"])
    completed_measurements = (
        coverage["complete_measurements"] if has_explicit_scope else already_retained
    )
    measurements = [m for m in measurements if m not in completed_measurements]
    if not measurements:
        return {
            "status": "already_retained",
            "reason": "Requested source measurements are already retained; no extraction repeated.",
        }
    # The candidate's own folder; assessment positions can differ from folder numbers.
    source_folder = source_record.get("folder", f"source-{index + 1}")
    folder = Path(directory) / f"{source_folder}-review-{round_number}"
    folder.mkdir()
    record = {
        "measurements": measurements,
        "documentation_link_index": link_index,
        "artifact_directory": folder.name,
        "status": "started",
    }
    assessment.setdefault("reassessments", []).append(record)
    metadata = source_record["metadata"]
    try:
        check_cancelled()
        if link_index >= 0:
            url = assessment["recovery_links"][link_index]
            progress("Reviewing source documentation: " + url[:180])
            body, content_type, final_url = fetch(url)
            (folder / "documentation.bin").write_bytes(body)
            record["documentation"] = {"url": final_url, "sha256": digest(body)}
            if "html" in content_type or body.lstrip().startswith(b"<"):
                text = inspect_page(body, final_url)["text"]
            elif body.startswith(b"%PDF"):
                inspected = run_python(
                    INSPECT_CODE,
                    {"source.bin": body},
                    folder / "documentation-inspection",
                    check_cancelled=check_cancelled,
                )
                if inspected["status"] != "succeeded":
                    raise ValueError("Documentation could not be inspected")
                text = (folder / "documentation-inspection/output/inspection.json").read_text()
            else:
                text = body[:40000].decode("utf-8", errors="replace")
            metadata = metadata + "\nObserved documentation: " + final_url + "\n" + text[:20000]
            source_record["metadata"] = metadata
            assessment["context_digest"] = digest(metadata.encode())
            source_record.setdefault("documentation", []).append(
                {
                    **record["documentation"],
                    "artifact": str(folder.relative_to(directory) / "documentation.bin"),
                }
            )
            save_context(Path(directory) / source_folder, source_record)
        progress("Reassessing downloaded data for: " + ", ".join(measurements))
        analysis = recover(
            question,
            {**scope, "measurements": measurements},
            source_record["body"],
            source_record["source"],
            folder,
            complete=complete,
            reason="Investigation review seeks missing coverage and/or additional documentation. "
            "Extract missing entities or breakdowns; do not repeat retained series. Coverage: "
            + json.dumps(planning_summary(scope, result["analyses"]))
            + ". Previous result: "
            + assessment["reason"],
            metadata=metadata,
            knowledge_dir=knowledge_dir,
            progress=progress,
            check_cancelled=check_cancelled,
        )
        analysis = execute_analysis(analysis, folder, check_cancelled=check_cancelled)
        # Retained analyses are immutable. Do not publish a second copy of the same source/series.
        existing = {
            (a["source"]["sha256"], s["label"], s["entity"])
            for a in result["analyses"]
            for s in a.get("series", [])
        }
        keys = {(analysis["source"]["sha256"], s["label"], s["entity"]) for s in analysis["series"]}
        if keys & existing:
            raise ValueError(
                "Reassessment overlaps already retained series; existing results preserved"
            )
        (folder / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2))
        result["analyses"].append(analysis)
        record.update(
            status="retained",
            reason="Validated requested subset",
            measurements=sorted({s["label"] for s in analysis["series"]}),
        )
        assessment.setdefault(
            "initial_assessment",
            {k: assessment.get(k) for k in ("decision", "reason", "failure_stage", "availability")},
        )
        assessment.update(
            decision="analysed",
            reason="Reassessed and validated: " + ", ".join(record["measurements"]),
            source=analysis["source"],
        )
        assessment.pop("availability", None)
        assessment.pop("failure_stage", None)
        progress(
            "Source review retained validated results for: " + ", ".join(record["measurements"])
        )
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
        record.update(status="blocked", reason=str(error)[:1000])
    finally:
        record["execution_review"] = execution_summary(folder)
        (folder / "review.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        original_folder = Path(directory) / source_folder
        original_folder.mkdir(exist_ok=True)
        (original_folder / "assessment.json").write_text(
            json.dumps(assessment, ensure_ascii=False, indent=2)
        )
    return record
