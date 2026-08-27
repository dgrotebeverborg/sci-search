"""Reproducible, source-grounded cross-domain quality benchmark."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine
from sci_search.question_interpretation import _deterministic_brief
from sci_search.question_planning import plan_question


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    split: str
    domain: str
    passed: bool
    checks_passed: int
    checks_total: int
    failures: tuple[str, ...]
    profile: str
    intent: str
    concepts: tuple[str, ...]
    evidence_publications: int
    relevant_passages: int
    adequacy: str


def evaluate_quality_benchmark(path: Path) -> dict[str, Any]:
    specification = json.loads(path.read_text(encoding="utf-8"))
    cases = specification.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("quality benchmark cases must be a non-empty list")
    engines: dict[Path, GenericResearchEngine] = {}
    results: list[CaseResult] = []
    for case in cases:
        corpus = (path.parent / str(case["corpus"])).resolve()
        engine = engines.get(corpus)
        if engine is None:
            engine = GenericResearchEngine(load_corpus(corpus))
            engines[corpus] = engine
        results.append(_evaluate_case(engine, case))
    passed = sum(item.passed for item in results)
    by_domain = _group(results, "domain")
    by_split = _group(results, "split")
    return {
        "schema_version": "sci_search_quality_benchmark_v1",
        "benchmark": specification.get("name"),
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4),
        "by_domain": by_domain,
        "by_split": by_split,
        "cases": [asdict(item) for item in results],
    }


def _evaluate_case(engine: GenericResearchEngine, case: dict[str, Any]) -> CaseResult:
    question = str(case["question"])
    plan = plan_question(question)
    brief = _deterministic_brief(question, plan).to_dict()
    report = engine.investigate(question)
    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    if expected := case.get("expected_profile"):
        check(plan.profile_id == expected, f"profile {plan.profile_id!r} != {expected!r}")
    if expected := case.get("expected_intent"):
        check(plan.intent == expected, f"intent {plan.intent!r} != {expected!r}")
    for concept in case.get("required_concepts", []):
        check(str(concept) in plan.concepts, f"missing planned concept: {concept}")
    if expected := case.get("expected_ambiguity"):
        allowed = {expected} if isinstance(expected, str) else set(expected)
        check(
            brief.get("ambiguity") in allowed,
            f"ambiguity {brief.get('ambiguity')!r} not in {sorted(allowed)!r}",
        )

    evidence = list(report.evidence)
    publications = {item.publication_id for item in evidence}
    check(
        len(publications) >= int(case.get("minimum_evidence_publications", 0)),
        f"evidence publications {len(publications)} below minimum {case.get('minimum_evidence_publications', 0)}",
    )
    check(
        len(evidence) >= int(case.get("minimum_relevant_passages", 0)),
        f"relevant passages {len(evidence)} below minimum {case.get('minimum_relevant_passages', 0)}",
    )
    if case.get("expect_no_evidence"):
        check(not evidence, f"expected no evidence, found {len(evidence)} passages")
    if expected := case.get("expected_adequacy"):
        allowed = {expected} if isinstance(expected, str) else set(expected)
        check(
            report.answer_adequacy.get("status") in allowed,
            f"adequacy {report.answer_adequacy.get('status')!r} not in {sorted(allowed)!r}",
        )

    searchable = "\n".join(f"{item.statement}\n{item.passage}" for item in evidence).casefold()
    for alternatives in case.get("required_evidence_terms", []):
        values = [alternatives] if isinstance(alternatives, str) else list(alternatives)
        check(
            any(str(value).casefold() in searchable for value in values),
            f"none of the required evidence terms were found: {values}",
        )
    for publication_id in case.get("required_publications", []):
        check(str(publication_id) in publications, f"required publication absent: {publication_id}")

    evidence_ids = {item.id for item in evidence}
    canonical = {item.publication.source_document: item.text for item in engine.documents}
    check(
        all(
            item.source_document in canonical
            and canonical[item.source_document][item.passage_start : item.passage_end]
            == item.passage
            and item.statement in item.passage
            for item in evidence
        ),
        "one or more evidence records failed exact provenance validation",
    )
    check(
        set(report.summary_evidence_ids) <= evidence_ids, "summary cites an unknown evidence record"
    )
    if not report.answer_adequacy.get("can_answer_overall_question"):
        check(not report.summary_evidence_ids, "coverage-limited answer retained summary citations")
        check(
            "withheld" in report.answer_summary.casefold() or not evidence,
            "coverage-limited answer did not clearly withhold the overall conclusion",
        )

    return CaseResult(
        id=str(case["id"]),
        split=str(case.get("split") or "development"),
        domain=str(case.get("domain") or "unknown"),
        passed=not failures,
        checks_passed=checks - len(failures),
        checks_total=checks,
        failures=tuple(failures),
        profile=plan.profile_id,
        intent=plan.intent,
        concepts=plan.concepts,
        evidence_publications=len(publications),
        relevant_passages=len(evidence),
        adequacy=str(report.answer_adequacy.get("status") or "unknown"),
    )


def _group(results: list[CaseResult], field: str) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[CaseResult]] = {}
    for item in results:
        groups.setdefault(str(getattr(item, field)), []).append(item)
    return {
        key: {
            "cases": len(items),
            "passed": sum(item.passed for item in items),
            "pass_rate": round(sum(item.passed for item in items) / len(items), 4),
        }
        for key, items in sorted(groups.items())
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = evaluate_quality_benchmark(args.benchmark)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
