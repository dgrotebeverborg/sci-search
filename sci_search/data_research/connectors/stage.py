# sci_search/data_research/connectors/stage.py
"""Connector stage: search terms, dataset choice, code selection, analysis and recovery."""

import copy
import csv
import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sci_search.data_research import semantics
from sci_search.data_research.artifacts import execute_analysis
from sci_search.data_research.connectors import CONNECTORS, base
from sci_search.data_research.packages import attach_provenance, prepare_table
from sci_search.data_research.python_recovery import recover as recover_python
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


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:60] or "x"


def _attempt_folder(directory, name, dataset, measurement):
    """A new folder per attempt: sealed artifacts of an earlier analysis are never overwritten."""
    stem = f"connector-{_slug(name)}-{_slug(dataset)}-{_slug(measurement)}"
    Path(directory).mkdir(parents=True, exist_ok=True)
    for number in range(1, 1000):
        folder = Path(directory) / (stem if number == 1 else f"{stem}-{number}")
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return folder
    raise OSError("Too many attempts for " + stem)


def _download(request):
    """Whether DOWNLOAD's plain GET of source["url"] can reproduce the retained bytes."""
    if request.get("method", "GET") != "GET":
        return {
            "reproducible": False,
            "reason": f"The retained source came from a {request.get('method')} request; "
            "its URL and body are in connector.request",
        }
    if any(key.endswith("_sha256") for key in request):
        return {
            "reproducible": False,
            "reason": "The retained source combines several API responses; "
            "their hashes are in connector.request",
        }
    return {"reproducible": True}


SELECT_PROMPT = (
    "Choose the codes that answer the requested measurement. Use only listed codes. Fix every "
    "non-series dimension to one code; series dimensions may have several (e.g. countries, sexes). "
    "Keep totals and their components apart. If previous_error is present, your last selection "
    "was rejected; repair it using the listed facts.\n"
)
CHOOSE_PROMPT = (
    "Choose at most 4 datasets that measure the requested measurements. Prefer annual "
    "series that cover the requested years; do not choose monthly or quarterly datasets.\n"
)
REFORMULATE_PROMPT = (
    "The previous searches did not yield a usable dataset. Using the reasons below, give 2 to 4 "
    "different short search terms for this measurement. Do not name datasets.\n"
)
MAX_REPAIRS = 2
# Reader failures that mean the bytes could not be parsed or have an unexpected shape. Only
# these go to Python extraction. Every other reader failure (frequency, unit, status flag,
# size or entity limit, duplicate or unobserved code) is a content rejection, because Python
# extraction would bypass those checks; an unknown message therefore fails closed.
PARSE_FAILURES = (
    "Invalid GZIP dataset",
    "Not a statistical TSV table",
    "Invalid statistical dimension names",
    "Response is not a JSON-stat dataset",
    "Inconsistent JSON-stat dimensions",
    "JSON-stat category counts do not match sizes",
    "JSON-stat value count does not match its dimensions",
    "OWID CSV lacks entity, year or the selected indicator column",
    "Unsupported CBS observation schema",
    "CBS package is missing a required code table",
    "CBS code table lacks identifiers or labels",
)
PARSE_ERRORS = (
    json.JSONDecodeError,
    UnicodeDecodeError,
    zipfile.BadZipFile,
    csv.Error,
    KeyError,
    TypeError,
)


def _reader_failure(exc):
    """Classify a reader exception: only a parse or shape failure may reach Python recovery."""
    if isinstance(exc, base.SelectionError | base.DatasetRejected):
        return base.DatasetRejected(str(exc))
    if isinstance(exc, PARSE_ERRORS) or any(str(exc).startswith(m) for m in PARSE_FAILURES):
        return base.ReaderError(str(exc))
    return base.DatasetRejected(str(exc))


def _transient(exc):
    if isinstance(exc, base.SelectionError | base.DatasetRejected | base.ReaderError):
        return False
    return isinstance(exc, OSError) or (isinstance(exc, ValueError) and "HTTP 5" in str(exc))


def _with_retry(step, recovery):
    """Run step; after a timeout or HTTP 5xx run it exactly once more."""
    try:
        return step()
    except (OSError, ValueError) as exc:
        if not _transient(exc):
            raise
        recovery.append({"class": "transient", "action": "retry", "outcome": str(exc)[:200]})
    return step()


def _facts(value):
    """Observed codes for a repair prompt; strings that look like URLs are dropped."""

    def url(item):
        return isinstance(item, str) and "://" in item

    if isinstance(value, dict):
        return {k: _facts(v) for k, v in value.items() if not url(k) and not url(v)}
    if isinstance(value, list | tuple | set | frozenset):
        items = sorted(value, key=str) if isinstance(value, set | frozenset) else value
        return [_facts(v) for v in items if not url(v)]
    return value


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
    folder = _attempt_folder(directory, connector.NAME, candidate.dataset, measurement)
    recovery = []
    assessment = {
        "title": candidate.title,
        "url": candidate.landing_url,
        "publisher": getattr(connector, "PUBLISHER", connector.NAME),
        "connector": connector.NAME,
        "dataset": candidate.dataset,
        "measurement": measurement,
        "decision": "blocked",
        "recovery": recovery,
    }
    stage_name = "connector:describe"
    try:
        check_cancelled()
        description = _with_retry(
            lambda: connector.describe(candidate, strategy, fetch=fetch), recovery
        )
        payload = {
            "question": question,
            "measurement": measurement,
            "scope": strategy,
            "dataset": candidate.title,
            "dimensions": [
                {"id": d.id, "label": d.label, "codes": d.codes} for d in description.dimensions
            ],
        }
        selection = fetched = repaired = None
        # A SelectionError gets up to MAX_REPAIRS repairs; every repair is validated again.
        for attempt in range(MAX_REPAIRS + 1):
            check_cancelled()
            stage_name = "connector:selection"
            proposal = complete(
                SELECT_PROMPT + json.dumps(payload, ensure_ascii=False),
                selection_schema(description),
            )
            try:
                selection = base.validate_selection(description, proposal)
                stage_name = "connector:fetch"
                progress(f"Requesting {candidate.title[:100]} from the {connector.NAME} API.")
                fetched = _with_retry(
                    lambda selection=selection: connector.fetch(
                        description, selection, strategy, fetch=fetch, post=post
                    ),
                    recovery,
                )
                break
            except base.SelectionError as exc:
                if attempt == MAX_REPAIRS:
                    raise
                payload["previous_error"] = {"error": str(exc)[:500], "facts": _facts(exc.facts)}
                repaired = {"class": "selection", "action": "repair", "outcome": str(exc)[:200]}
                recovery.append(repaired)
        assert selection is not None and fetched is not None
        if repaired:
            repaired["outcome"] = "repaired"
        assessment["selection"] = selection
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
            "download": _download(fetched.request),
            "connector": {
                "name": connector.NAME,
                "dataset": candidate.dataset,
                "request": fetched.request,
                "catalogue_sha256": catalogue_sha256,
                "selection": selection,
            },
        }
        stage_name = "connector:normalize"
        try:
            table, preparation = prepare_table(fetched.raw, fetched.selection)
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, csv.Error) as exc:
            failure = _reader_failure(exc)
            if isinstance(failure, base.DatasetRejected):
                raise failure from exc
            recovery.append(
                {"class": "reader", "action": "python_recovery", "outcome": str(exc)[:200]}
            )
            stage_name = "connector:python"
            progress("The connector reader could not read this response. Trying Python extraction.")
            (folder / fetched.artifact).write_bytes(fetched.raw)
            # recover_python runs its own semantic review and raises unless it is accepted.
            analysis = recover_python(
                question,
                {**strategy, "measurements": [measurement]},
                fetched.raw,
                source,
                folder,
                complete=complete,
                reason="Connector reader could not read the response: " + str(exc)[:300],
                metadata=description.definitions,
                check_cancelled=check_cancelled,
                progress=progress,
            )
            if measurement in analysis.get("uncovered_measurements", []):
                raise base.DatasetRejected(
                    "Python extraction did not represent the measurement"
                ) from exc
            stage_name = "execution"
            analysis = execute_analysis(analysis, folder, check_cancelled=check_cancelled)
            save(folder / "analysis.json", analysis)
            recovery[-1]["outcome"] = "recovered"
            assessment.setdefault("semantic_reviews", []).append(analysis["semantic_review"])
            assessment.update(
                decision="analysed",
                reason="Recovered with executed Python extraction",
                source=analysis["source"],
            )
            return analysis, assessment
        try:
            mapping = connector.mapping(table, preparation, selection, measurement)
        except base.SelectionError as exc:
            raise base.DatasetRejected(str(exc)) from exc
        analysis = analyse_csv(table, mapping, strategy)
        attach_provenance(analysis, preparation)
        analysis["limitations"] += list(fetched.notes) + preparation.get("limitations", [])
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


def _search_all(connectors, terms, strategy, fetch, cache_dir, result, *, check_cancelled):
    """Search every connector catalogue for terms; failures become blocked assessments."""
    found = {}
    for name, connector in connectors.items():
        check_cancelled()
        try:
            candidates, digest = connector.search(
                sorted(set(terms)), strategy, fetch=fetch, cache_dir=cache_dir
            )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            if any(
                a.get("title") == f"{name} catalogue"
                and a.get("failure_stage") == "connector:search"
                for a in result["assessments"]
            ):
                continue  # already recorded in an earlier round
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
    return found


def _choose_and_analyse(
    question,
    strategy,
    directory,
    found,
    measurements,
    result,
    *,
    complete,
    fetch,
    post,
    check_cancelled,
    progress,
    skipped,
    recovery=(),
):
    """Let the model choose among found candidates, analyse each choice; return how many were tried."""
    candidates = [
        {"key": k, "title": c.title, "frequency": c.frequency} for k, (_, c) in found.items()
    ]
    try:
        choice = complete(
            CHOOSE_PROMPT
            + json.dumps(
                {
                    "question": question,
                    "scope": {**strategy, "measurements": measurements},
                    "candidates": candidates,
                },
                ensure_ascii=False,
            ),
            CHOICE_SCHEMA,
        )
        items = [
            {"candidate": i["candidate"], "measurement": i["measurement"], "reason": i["reason"]}
            for i in choice["choices"][:4]
        ]
        if not all(isinstance(i["candidate"], str) for i in items):
            raise TypeError("Dataset choice candidate must be a string")
    except (ValueError, KeyError, TypeError) as exc:
        result["assessments"].append(
            {
                "title": "connector dataset choice",
                "decision": "blocked",
                "failure_stage": "connector:choice",
                "reason": str(exc)[:500],
            }
        )
        return 0
    attempted = 0
    for item in items:
        problem = ""
        if item["candidate"] not in found:
            problem = "unknown candidate"
        elif item["measurement"] not in measurements:
            problem = "measurement not requested"
        if problem:
            skipped.append(
                {
                    "candidate": item["candidate"],
                    "measurement": item["measurement"],
                    "reason": problem,
                }
            )
            continue
        if item["measurement"] in result["covered"]:
            continue
        connector, candidate = found[item["candidate"]]
        attempted += 1
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
        assessment["recovery"] = [*recovery, *assessment["recovery"]]
        result["assessments"].append(assessment)
        if analysis:
            result["analyses"].append(analysis)
            result["covered"].append(item["measurement"])
    return attempted


def _reformulate(question, measurement, previous, reasons, complete):
    try:
        reply = complete(
            REFORMULATE_PROMPT
            + json.dumps(
                {
                    "question": question,
                    "measurement": measurement,
                    "previous_terms": previous,
                    "reasons": reasons,
                },
                ensure_ascii=False,
            ),
            TERMS_SCHEMA,
        )
        terms = next(t["terms"] for t in reply["terms"] if t["measurement"] == measurement)
        return [t for t in terms if isinstance(t, str) and t.strip()][:4]
    except (ValueError, KeyError, TypeError, StopIteration):
        return []


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
    search_fetch=None,
):
    connectors = CONNECTORS if connectors is None else connectors
    # Catalogue lists can be larger than one data response; the caller may bound them separately.
    search_fetch = search_fetch or fetch
    directory = Path(directory)
    cache_dir = Path(cache_dir) if cache_dir else directory / "catalogues"
    result = {
        "analyses": [],
        "assessments": [],
        "covered": [],
        "search": {
            "terms": {},
            "candidates": [],
            "catalogues": {},
            "skipped_choices": [],
            "reformulated_terms": {},
            "reformulated_skipped_choices": [],
        },
    }
    steps = {
        "complete": complete,
        "fetch": fetch,
        "post": post,
        "check_cancelled": check_cancelled,
        "progress": progress,
    }
    terms = _terms(question, strategy, complete)
    result["search"]["terms"] = terms
    found = _search_all(
        connectors,
        [t for ts in terms.values() for t in ts],
        strategy,
        search_fetch,
        cache_dir,
        result,
        check_cancelled=check_cancelled,
    )
    result["search"]["candidates"] = [
        {"key": k, "title": c.title, "frequency": c.frequency} for k, (_, c) in found.items()
    ]
    if found:
        _choose_and_analyse(
            question,
            strategy,
            directory,
            found,
            strategy["measurements"],
            result,
            skipped=result["search"]["skipped_choices"],
            **steps,
        )
    # One reformulated search per measurement that is still uncovered.
    for measurement in [m for m in strategy["measurements"] if m not in result["covered"]]:
        check_cancelled()
        reasons = [
            a["reason"]
            for a in result["assessments"]
            if a.get("measurement") == measurement and a.get("reason")
        ]
        retry_terms = _reformulate(question, measurement, terms[measurement], reasons, complete)
        result["search"]["reformulated_terms"][measurement] = retry_terms
        entry = {
            "class": "search",
            "action": "reformulate",
            "outcome": ", ".join(retry_terms)[:200],
        }
        tried = {
            f"{a.get('connector')}:{a.get('dataset')}"
            for a in result["assessments"]
            if a.get("measurement") == measurement
        }
        found_again = (
            _search_all(
                connectors,
                retry_terms,
                strategy,
                search_fetch,
                cache_dir,
                result,
                check_cancelled=check_cancelled,
            )
            if retry_terms
            else {}
        )
        fresh = {k: v for k, v in found_again.items() if k not in tried}
        reason = "No connector dataset found after reformulated search"
        if fresh:
            attempted = _choose_and_analyse(
                question,
                strategy,
                directory,
                fresh,
                [measurement],
                result,
                skipped=result["search"]["reformulated_skipped_choices"],
                recovery=[entry],
                **steps,
            )
            if attempted:
                continue  # the analysed datasets carry their own assessments
            reason += ": reformulated choice was invalid"
        elif found_again:
            reason += ": all reformulated datasets were already tried"
        result["assessments"].append(
            {
                "title": "Connector search",
                "measurement": measurement,
                "decision": "blocked",
                "failure_stage": "connector:search",
                "reason": reason,
                "recovery": [entry],
            }
        )
    return result
