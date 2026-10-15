"""Describe actual series coverage without claiming that discovery is exhaustive."""


def period_summary(strategy, analyses):
    start, end = strategy.get("start_year"), strategy.get("end_year")
    requested = (
        "Longest comparable historical series"
        if start is None and end is None
        else f"{start or 'Earliest comparable year'}–{end or 'Latest available year'}"
    )
    rows = []
    for analysis in analyses:
        series_list = analysis.get("series") or [
            {
                "label": analysis.get("source", {}).get("title", "Dataset"),
                "annual": analysis.get("annual", []),
            }
        ]
        for series in series_list:
            annual = series.get("annual", [])
            years = [
                r["year"]
                for r in annual
                if r.get("value") is not None
                or ("value" not in r and any(v is not None for k, v in r.items() if k != "year"))
            ]
            rows.append(
                {
                    "source": analysis.get("source", {}).get("title", ""),
                    "series": series.get("label", ""),
                    "entity": series.get("entity", ""),
                    "first_year": min(years) if years else None,
                    "last_year": max(years) if years else None,
                    "missing_years": [
                        r["year"] for r in annual if "value" in r and r["value"] is None
                    ],
                }
            )
    return {
        "requested": requested,
        "analysed": rows,
        "qualification": "These are the years actually analysed. Discovery does not establish that no earlier or broader data exists.",
    }


def candidates_with_followup(
    question, strategy, trace, result, search, analyzer, save_trace, progress, check_cancelled
):
    seen = set()
    for candidate in trace["candidates"][:4]:
        if candidate["url"] not in seen:
            seen.add(candidate["url"])
            yield candidate
    check_cancelled()
    # A bounded second pass also checks coverage of types/definitions: an analysed
    # measurement alone does not establish complete coverage of the question.
    progress("Searching for earlier comparable data and missing types or coverage.")
    context = {
        "period": period_summary(strategy, result["analyses"]),
        "source_decisions": result["assessments"],
        "coverage_limits": [a.get("limitations", []) for a in result["analyses"]],
    }
    import json

    prompt = (
        question + "\nFollow-up coverage search: seek earlier comparable years and any missing "
        "technologies/types or requested measurements. Respect the user's explicit date bounds. "
        "Find primary downloadable sources beyond those already checked. Do not substitute installed "
        "capacity for actual use. Keep incompatible definitions and series separate; do not splice them. "
        "If only short or partial series exist, seek documentation explaining their limits. "
        "Return no candidates if no additional useful source is found. Current findings:\n"
        + json.dumps(context)
    )
    try:
        extra = search(prompt, strategy, analyzer=analyzer)
        result["followup"] = {
            "status": "complete",
            "discovery": extra,
            "purpose": "Earlier comparable years and missing types or measurements",
        }
        save_trace(extra)
        for candidate in extra["candidates"][:4]:
            if candidate["url"] not in seen:
                seen.add(candidate["url"])
                yield candidate
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["followup"] = {"status": "failed", "reason": str(exc)[:300]}
        result["limitations"].append(
            "Additional coverage search failed; earlier or broader data may exist."
        )
