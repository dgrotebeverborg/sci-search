# sci_search/data_research/connectors/stage.py
"""Connector stage: search terms, dataset choice, code selection, analysis and recovery."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sci_search.data_research import semantics
from sci_search.data_research.artifacts import execute_analysis
from sci_search.data_research.connectors import CONNECTORS, base
from sci_search.data_research.packages import attach_provenance, prepare_table
from sci_search.data_research.tabular import analyse_csv, read_csv

TERMS_SCHEMA = {
    "title": "connector_terms",
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["measurement", "terms"],
                "properties": {
                    "measurement": {"type": "string"},
                    "terms": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                },
            },
        }
    },
}
CHOICE_SCHEMA = {
    "title": "connector_choice",
    "type": "object",
    "additionalProperties": False,
    "required": ["choices"],
    "properties": {
        "choices": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["candidate", "measurement", "reason"],
                "properties": {
                    "candidate": {"type": "string"},
                    "measurement": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def selection_schema(description):
    dims = [d.id for d in description.dimensions]
    return {
        "title": "connector_selection",
        "type": "object",
        "additionalProperties": False,
        "required": ["filters", "series_dimensions", "reason"],
        "properties": {
            "filters": {
                "type": "object",
                "additionalProperties": False,
                "required": dims,
                "properties": {
                    d.id: {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": sorted(d.codes)},
                    }
                    for d in description.dimensions
                },
            },
            "series_dimensions": {"type": "array", "items": {"type": "string", "enum": dims}},
            "reason": {"type": "string"},
        },
    }


def _terms(question, strategy, complete):
    try:
        reply = complete(
            "For each requested measurement give 2 to 4 short search terms for official statistics "
            "catalogues, in English and also in Dutch for Dutch statistics. Do not name datasets.\n"
            + json.dumps(
                {
                    "question": question,
                    "measurements": strategy["measurements"],
                    "geography": strategy["geography"],
                }
            ),
            TERMS_SCHEMA,
        )
        terms = {t["measurement"]: [x for x in t["terms"] if x.strip()][:4] for t in reply["terms"]}
    except (ValueError, KeyError, TypeError):
        terms = {}
    return {m: terms.get(m) or [m] for m in strategy["measurements"]}


def analyse_dataset(
    question,
    strategy,
    directory,
    connector,
    candidate,
    measurement,
    *,
    complete,
    fetch,
    post,
    check_cancelled,
    progress,
    catalogue_sha256="",
):
    folder = (
        Path(directory)
        / f"connector-{connector.NAME}-{candidate.dataset.replace('/', '_').replace(':', '_')}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    assessment = {
        "title": candidate.title,
        "url": candidate.landing_url,
        "publisher": getattr(connector, "PUBLISHER", connector.NAME),
        "connector": connector.NAME,
        "dataset": candidate.dataset,
        "measurement": measurement,
        "decision": "blocked",
    }
    stage_name = "connector:describe"
    try:
        check_cancelled()
        description = connector.describe(candidate, strategy, fetch=fetch)
        stage_name = "connector:selection"
        proposal = complete(
            "Choose the codes that answer the requested measurement. Use only listed codes. Fix every "
            "non-series dimension to one code; series dimensions may have several (e.g. countries, sexes). "
            "Keep totals and their components apart.\n"
            + json.dumps(
                {
                    "question": question,
                    "measurement": measurement,
                    "scope": strategy,
                    "dataset": candidate.title,
                    "dimensions": [
                        {"id": d.id, "label": d.label, "codes": d.codes}
                        for d in description.dimensions
                    ],
                },
                ensure_ascii=False,
            ),
            selection_schema(description),
        )
        selection = base.validate_selection(description, proposal)
        assessment["selection"] = selection
        stage_name = "connector:fetch"
        progress(f"Requesting {candidate.title[:100]} from the {connector.NAME} API.")
        fetched = connector.fetch(description, selection, strategy, fetch=fetch, post=post)
        stage_name = "connector:normalize"
        try:
            table, preparation = prepare_table(fetched.raw, fetched.selection)
        except (ValueError, KeyError, TypeError) as exc:
            raise base.ReaderError(str(exc)) from exc
        mapping = connector.mapping(table, preparation, selection, measurement)
        analysis = analyse_csv(table, mapping, strategy)
        attach_provenance(analysis, preparation)
        analysis["limitations"] += list(fetched.notes) + preparation.get("limitations", [])
        source = {
            "title": candidate.title,
            "url": fetched.request["url"],
            "landing_url": candidate.landing_url,
            "publisher": description.publisher,
            "definition": description.definitions[:500],
            "license_url": description.licence_url,
            "license_note": "Licence from the dataset metadata: " + description.licence_url,
            "sha256": hashlib.sha256(fetched.raw).hexdigest(),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "artifact": fetched.artifact,
            "connector": {
                "name": connector.NAME,
                "dataset": candidate.dataset,
                "request": fetched.request,
                "catalogue_sha256": catalogue_sha256,
                "selection": selection,
            },
        }
        (folder / fetched.artifact).write_bytes(fetched.raw)
        (folder / "source.csv").write_bytes(table)
        analysis = {
            **analysis,
            "components": [copy.deepcopy(analysis)],
            "kind": "tabular",
            "source": source,
            "preparation": {**preparation, "selection": fetched.selection}
            if fetched.selection
            else preparation,
        }
        stage_name = "connector:meaning"
        _, rows = read_csv(table)
        documents = {
            "metadata": description.definitions,
            "table_sample": json.dumps(rows[:12], ensure_ascii=False),
        }
        review = semantics.assess(
            question=question,
            scope=strategy,
            analysis=analysis,
            documents=documents,
            complete=complete,
        )
        assessment.setdefault("semantic_reviews", []).append(review)
        save(folder / "semantic-review.json", {"review": review, "evidence_documents": documents})
        if not review["accepted"]:
            raise base.DatasetRejected("Measurement meaning not confirmed: " + review["reason"])
        analysis["semantic_review"] = review
        stage_name = "execution"
        analysis = execute_analysis(analysis, folder, check_cancelled=check_cancelled)
        save(folder / "analysis.json", analysis)
        assessment.update(
            decision="analysed",
            reason=selection["reason"] or "Selected from dataset metadata",
            source=source,
        )
        return analysis, assessment
    except (ValueError, KeyError, TypeError, OSError) as exc:
        assessment.update(
            reason=str(exc)[:700], failure_stage=stage_name, error_class=type(exc).__name__
        )
        if isinstance(exc, base.SelectionError):
            assessment["facts"] = exc.facts
        return None, assessment


def run(
    question,
    strategy,
    directory,
    *,
    complete,
    fetch,
    post,
    check_cancelled,
    progress,
    connectors=None,
    cache_dir=None,
):
    connectors = CONNECTORS if connectors is None else connectors
    directory = Path(directory)
    cache_dir = Path(cache_dir) if cache_dir else directory / "catalogues"
    result = {
        "analyses": [],
        "assessments": [],
        "covered": [],
        "search": {"terms": {}, "candidates": [], "catalogues": {}},
    }
    terms = _terms(question, strategy, complete)
    result["search"]["terms"] = terms
    found = {}
    for name, connector in connectors.items():
        check_cancelled()
        try:
            candidates, digest = connector.search(
                sorted({t for ts in terms.values() for t in ts}),
                strategy,
                fetch=fetch,
                cache_dir=cache_dir,
            )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result["assessments"].append(
                {
                    "title": f"{name} catalogue",
                    "connector": name,
                    "decision": "blocked",
                    "reason": str(exc)[:500],
                    "failure_stage": "connector:search",
                }
            )
            continue
        result["search"]["catalogues"][name] = digest
        for c in candidates:
            found[f"{name}:{c.dataset}"] = (connector, c)
    result["search"]["candidates"] = [
        {"key": k, "title": c.title, "frequency": c.frequency} for k, (_, c) in found.items()
    ]
    if not found:
        return result
    choice = complete(
        "Choose at most 4 datasets that measure the requested measurements. Prefer annual series that "
        "cover the requested years; do not choose monthly or quarterly datasets.\n"
        + json.dumps(
            {"question": question, "scope": strategy, "candidates": result["search"]["candidates"]},
            ensure_ascii=False,
        ),
        CHOICE_SCHEMA,
    )
    for item in choice["choices"][:4]:
        if item["candidate"] not in found or item["measurement"] not in strategy["measurements"]:
            continue
        if item["measurement"] in result["covered"]:
            continue
        connector, candidate = found[item["candidate"]]
        analysis, assessment = analyse_dataset(
            question,
            strategy,
            directory,
            connector,
            candidate,
            item["measurement"],
            complete=complete,
            fetch=fetch,
            post=post,
            check_cancelled=check_cancelled,
            progress=progress,
            catalogue_sha256=result["search"]["catalogues"].get(connector.NAME, ""),
        )
        assessment["choice_reason"] = item["reason"]
        result["assessments"].append(assessment)
        if analysis:
            result["analyses"].append(analysis)
            result["covered"].append(item["measurement"])
    return result
