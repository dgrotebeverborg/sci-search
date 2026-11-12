"""Review, execute and seal derived outputs without modifying retained raw series."""

import json
import re
from pathlib import Path

from sci_search.data_research import derived_outputs, semantics
from sci_search.data_research.artifact_validation import validate_artifacts
from sci_search.data_research.calculations import calculate
from sci_search.data_research.coverage import evaluate
from sci_search.data_research.execution import digest, run_python
from sci_search.data_research.failures import record_failure
from sci_search.data_research.replay_manifest import engine_modules
from sci_search.data_research.run_control import BudgetExhausted

SCRIPT = """import json
import re
from pathlib import Path
from derived_outputs import compute
payload=json.loads(Path('/input/payload.json').read_text())
Path('/output/result.json').write_text(json.dumps(compute(payload), allow_nan=False))
"""


def _retained(directory, analyses):
    folders = list(directory.glob("source-*")) + list(directory.glob("connectors/connector-*"))
    retained = {}
    for folder in folders:
        saved = folder / "analysis.json"
        if not saved.is_file():
            continue
        value = json.loads(saved.read_text())
        for index, analysis in enumerate(analyses):
            if analysis != value:
                continue
            files = analysis.get("execution", {}).get("artifacts", {})
            if not files:
                raise ValueError("Input has no sealed source artifacts")
            validate_artifacts(folder, files)
            executed = json.loads((folder / "calculation/output/result.json").read_text())
            if analysis.get("execution", {}).get("status") != "verified" or executed != {
                k: v for k, v in analysis.items() if k != "execution"
            }:
                raise ValueError("Input analysis differs from its sealed executed result")
            retained[index] = folder
    if len(retained) != len(analyses):
        raise ValueError("Input analysis is missing from the retained verified sources")
    return retained


def _documents(folders, indexes):
    documents = {}
    for index in indexes:
        saved = json.loads((folders[index] / "analysis.json").read_text())
        names = saved["execution"]["artifacts"]
        for name in sorted(names):
            path = folders[index] / name
            if path.parent != folders[index] or not path.match("semantic-review*.json"):
                continue
            value = json.loads(path.read_text())
            if value.get("review", {}).get("accepted"):
                for key, text in value.get("evidence_documents", {}).items():
                    document_key = f"source_{index}:{path.stem}:{key}"
                    if len(text) <= 30000:
                        documents[document_key] = text
                        continue
                    # Large catalogues contain unrelated series. Keep only original
                    # cited passages with context, explicitly labelled as excerpts.
                    quotes = {
                        e.get("quote", "")
                        for measurement in value["review"].get("measurements", [])
                        for check in measurement.get("checks", [])
                        for e in check.get("evidence", [])
                        if e.get("document") == key and isinstance(e.get("quote"), str)
                    }
                    for number, quote in enumerate(sorted(quotes)):
                        if not quote:
                            continue
                        pattern = r"\s+".join(re.escape(word) for word in quote.split())
                        if not pattern:
                            continue
                        for occurrence, match in enumerate(re.finditer(pattern, text)):
                            excerpt = text[max(0, match.start() - 1000) : match.end() + 1000]
                            documents[f"{document_key}:original_excerpt_{number}_{occurrence}"] = (
                                excerpt
                            )
                            if sum(len(t) for t in documents.values()) > 250000:
                                raise ValueError(
                                    "Combined source documentation exceeds the calculation review limit"
                                )
    if len(json.dumps(documents)) > 250000:
        raise ValueError("Combined source documentation exceeds the calculation review limit")
    return documents


def _review(result, jobs, folders, complete):
    records = []
    for plan in result["strategy"].get("calculations", []):
        group = [j for j in jobs if j["plan"]["id"] == plan["id"] and not j["reason"]]
        if not plan["reference"] or not group:
            continue
        eligible = []
        for job in group:
            inputs = [
                result["analyses"][pair[0]]["series"][pair[1]]
                for pair in (job["source"], job["reference"])
            ]
            candidate = calculate(plan, *inputs, years=job["years"])
            if candidate["status"] == "blocked":
                job["reason"] = candidate["reason"]
            else:
                eligible.append(job)
        group = eligible
        if not group:
            continue
        fingerprint = digest(
            json.dumps(
                {"plan": plan, "analyses": result["analyses"], "group": group}, sort_keys=True
            ).encode()
        )
        result.setdefault("calculation_reviews", {})
        if complete is None:
            review = {
                "accepted": False,
                "reason": "No remaining model budget for input compatibility review",
            }
        else:
            indexes = sorted({pair[0] for j in group for pair in (j["source"], j["reference"])})
            try:
                documents = _documents(folders, indexes)
                if any(
                    not any(key.startswith(f"source_{i}:") for key in documents) for i in indexes
                ):
                    raise ValueError("Original definition evidence missing for a calculation input")
                proposal = {"plan": plan, "series": []}
                for job in group:
                    inputs = [
                        result["analyses"][pair[0]]["series"][pair[1]]
                        for pair in (job["source"], job["reference"])
                    ]
                    proposal["series"].append(
                        {
                            "entity": job["entity"],
                            "dimensions": job["dimensions"],
                            "inputs": [semantics._ends(s) for s in inputs],
                            "calculation": semantics._ends(
                                calculate(plan, *inputs, years=job["years"])
                            ),
                        }
                    )
                prompt = (
                    semantics.INSTRUCTIONS
                    + "\nAssess this REQUESTED derived calculation, not merely whether the raw inputs can be copied. For shares verify a matching numerator and total denominator (gross/net, population, category, observation type, and time basis); for inflation use a compatible price index. Cite definition evidence from each input source. A rebased average transaction-price series is not a constant-quality house-price index.\n"
                    + json.dumps(
                        {
                            "measurements": [plan["label"]],
                            "proposal": proposal,
                            "evidence_documents": documents,
                        }
                    )
                )
                review = semantics.validate(
                    complete(prompt, semantics.review_schema([plan["label"]])),
                    [plan["label"]],
                    documents,
                )
                cited = {
                    e.get("document", "").split(":")[0]
                    for item in review.get("measurements", [])
                    for check in item.get("checks", [])
                    for e in check.get("evidence", [])
                }
                if any(f"source_{i}" not in cited for i in indexes):
                    review = {
                        **review,
                        "accepted": False,
                        "reason": "Compatibility review did not cite every input source",
                    }
                records.append(
                    {"fingerprint": fingerprint, "review": review, "evidence_documents": documents}
                )
            except BudgetExhausted:
                complete = None
                review = {
                    "accepted": False,
                    "reason": "No remaining model budget for input compatibility review",
                }
            except (OSError, ValueError, KeyError, TypeError) as exc:
                review = {"accepted": False, "reason": str(exc)}
            result["calculation_reviews"][plan["id"]] = {
                "fingerprint": fingerprint,
                "review": review,
            }
        for job in group:
            job["review"] = review
    return records


def finalize(result, directory, *, complete=None, check_cancelled=lambda: None):
    """Called on ordinary finish and after a discovery budget is exhausted."""
    directory = Path(directory)
    coverage = evaluate(result["strategy"], result["analyses"])
    result["coverage"] = coverage
    if not result["strategy"].get("calculations"):
        derived = derived_outputs.compute(
            {"scope": result["strategy"], "analyses": result["analyses"], "jobs": []}
        )
    else:
        try:
            folders = _retained(directory, result["analyses"])
            jobs = derived_outputs.prepare_jobs(result["strategy"], result["analyses"])
            reviews = _review(result, jobs, folders, complete)
            payload = {"scope": result["strategy"], "analyses": result["analyses"], "jobs": jobs}
            inputs = {
                "payload.json": json.dumps(payload, allow_nan=False).encode(),
                "reviews.json": json.dumps(reviews, allow_nan=False).encode(),
                **{
                    name: Path(__file__).with_name(name).read_bytes()
                    for name in engine_modules("derived_outputs.py")
                },
            }
            number = 1
            while (directory / f"derived-{number}").exists():
                number += 1
            folder = directory / f"derived-{number}"
            record = run_python(SCRIPT, inputs, folder, check_cancelled=check_cancelled)
            if record["status"] != "succeeded":
                raise ValueError(record.get("error", "Derived calculation failed"))
            derived = json.loads((folder / "output/result.json").read_text())
            if derived != derived_outputs.compute(payload):
                raise ValueError("Executed derived calculations differ from proposed outputs")
            derived["execution"] = {
                "status": "verified",
                "directory": folder.name,
                "script_sha256": record["script_sha256"],
                "runtime": record["runtime"],
                "checks": [
                    "Retained input artifact hashes",
                    "Executed derived values equal published outputs",
                ],
                "artifacts": {
                    str(p.relative_to(folder)): digest(p.read_bytes())
                    for p in folder.rglob("*")
                    if p.is_file()
                },
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            derived = {"version": 1, "status": "blocked", "outputs": []}
            record_failure(derived, exc, stage="derived_calculation")
    result["derived_outputs"] = derived
    result["output_completion"] = derived_outputs.completion(result["strategy"], coverage, derived)
