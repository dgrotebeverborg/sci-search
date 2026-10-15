"""Resolve requested inputs conservatively and keep calculation coverage separate."""

try:
    from sci_search.data_research.calculations import calculate
except ImportError:  # retained offline calculation, without the installed application
    from calculations import calculate


def _key(cell):
    return cell["entity"], tuple(sorted(cell.get("dimensions", {}).items()))


def prepare_jobs(scope, analyses):
    from sci_search.data_research.coverage import evaluate

    cells = evaluate(scope, analyses)["cells"]

    def choose(cell, measurement):
        candidates = []
        for match in cell.get("sources", []) if cell else []:
            if not match["years"]:
                continue
            source_index = match["source_index"]
            for index, series in enumerate(analyses[source_index].get("series", [])):
                if series["label"] == measurement and series["entity"] == match["entity"]:
                    candidate = [source_index, index]
                    if candidate not in candidates:
                        candidates.append(candidate)
        return candidates[0] if len(candidates) == 1 else None, len(candidates)

    jobs = []
    for plan in scope.get("calculations", []):
        references = {_key(c): c for c in cells if c["measurement"] == plan["reference"]}
        for cell in cells:
            if cell["measurement"] != plan["input"]:
                continue
            source, count = choose(cell, plan["input"])
            ref, ref_count = choose(references.get(_key(cell)), plan["reference"])
            reason = ""
            if count != 1:
                reason = (
                    "Input series missing"
                    if not count
                    else "Input series ambiguous; sources are not spliced or chosen automatically"
                )
            elif plan["reference"] is not None and ref_count != 1:
                reason = (
                    "Matching reference series missing"
                    if not ref_count
                    else "Reference series ambiguous"
                )
            if any(
                analyses[i].get("execution", {}).get("status") != "verified"
                for i, _ in [s for s in (source, ref) if s is not None]
            ):
                reason = "Input has not been verified by executed source calculations"
            start, end = scope.get("start_year"), scope.get("end_year")
            if start is None or end is None:
                reason = "An explicit output period is required to certify calculation coverage"
            jobs.append(
                {
                    "plan": plan,
                    "entity": cell["entity"],
                    "dimensions": cell["dimensions"],
                    "source": source,
                    "reference": ref,
                    "reason": reason,
                    "years": list(range(start, end + 1))
                    if start is not None and end is not None
                    else [],
                }
            )
    if len(jobs) > 6000:
        raise ValueError("Requested calculations exceed 6000 output series")
    return jobs


def compute(payload):
    scope, analyses, jobs = (payload[k] for k in ("scope", "analyses", "jobs"))
    outputs = []
    for job in jobs:
        reason = job["reason"]
        plan = job["plan"]
        source = analyses[job["source"][0]]["series"][job["source"][1]] if job["source"] else None
        reference = (
            analyses[job["reference"][0]]["series"][job["reference"][1]]
            if job["reference"]
            else None
        )
        if (
            not reason
            and plan["reference"] is not None
            and not job.get("review", {}).get("accepted")
        ):
            reason = "Input compatibility review unresolved: " + job.get("review", {}).get(
                "reason", "No validated meaning review"
            )
        if reason:
            output = {
                "id": plan["id"],
                "label": plan["label"],
                "operation": plan["operation"],
                "status": "blocked",
                "reason": reason,
                "unit": plan["target_unit"] or "",
                "annual": [
                    {"year": y, "value": None, "reason": reason, "inputs": []} for y in job["years"]
                ],
            }
        else:
            output = calculate(plan, source, reference, years=job["years"])
        dependencies = []
        for role, pair in [("input", job["source"]), ("reference", job["reference"])]:
            if pair is not None:
                dependencies.append(
                    {
                        "role": role,
                        "analysis_index": pair[0],
                        "series_index": pair[1],
                        "sha256": analyses[pair[0]]["source"]["sha256"],
                    }
                )
        output.update(entity=job["entity"], dimensions=job["dimensions"], sources=dependencies)
        if job.get("review"):
            output["semantic_review"] = job["review"]
        outputs.append(output)
    status = (
        "not_assessed"
        if "calculations" not in scope
        else "not_requested"
        if not scope["calculations"]
        else "complete"
        if outputs and all(o["status"] == "complete" for o in outputs)
        else "partial"
        if any(r["value"] is not None for o in outputs for r in o["annual"])
        else "blocked"
    )
    return {
        "version": 1,
        "status": status,
        "outputs": outputs,
        "qualification": "Computed from retained observations. Missing inputs are not filled; scientific interpretation remains a separate assessment.",
    }


def completion(scope, coverage, derived):
    cells = coverage.get("cells", [])
    data_status = (
        "complete"
        if cells and not coverage.get("gaps")
        else "partial"
        if any(c["status"] in {"partial", "complete"} for c in cells)
        else "blocked"
    )
    calculation_status = derived["status"]
    answer = (
        "not_assessed"
        if calculation_status == "not_assessed"
        else "complete"
        if data_status == "complete" and calculation_status in {"complete", "not_requested"}
        else "partial"
        if data_status != "blocked" or calculation_status == "partial"
        else "blocked"
    )
    return {
        "data_status": data_status,
        "calculation_status": calculation_status,
        "numerical_answer_status": answer,
        "qualification": "This checks numerical inputs and explicitly requested calculations, not completeness of methodological or literature explanations.",
    }
