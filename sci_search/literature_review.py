"""Build portable, cited literature-review artifacts from a completed research run."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from typing import Any

from sci_search.domain.contradictions import SEVERITY_RULES_VERSION, assess_severity
from sci_search.pdf_report import markdown_to_pdf
from sci_search.research_landscape import build_research_landscape


def build_literature_review(investigation: dict[str, Any]) -> dict[str, Any]:
    question = str(investigation.get("question") or "Scientific literature review").strip()
    run = (
        investigation.get("research_run")
        if isinstance(investigation.get("research_run"), dict)
        else {}
    )
    evidence = [item for item in investigation.get("evidence", []) if isinstance(item, dict)]
    evidence_by_id = {str(item.get("id")): item for item in evidence if item.get("id")}
    candidates = [item for item in run.get("candidates", []) if isinstance(item, dict)]
    active_ids = {str(item) for item in run.get("active_publication_ids", [])}
    candidate_by_id = {str(item.get("id")): item for item in candidates if item.get("id")}

    cited_publication_ids: list[str] = []
    for item in evidence:
        publication_id = str(item.get("publication_id") or "")
        if publication_id and publication_id not in cited_publication_ids:
            cited_publication_ids.append(publication_id)
    included_ids = list(dict.fromkeys([*cited_publication_ids, *sorted(active_ids)]))
    references = []
    reference_number: dict[str, int] = {}
    for publication_id in included_ids:
        candidate = candidate_by_id.get(publication_id, {})
        matching_evidence = next(
            (item for item in evidence if str(item.get("publication_id")) == publication_id), {}
        )
        reference_number[publication_id] = len(references) + 1
        references.append(
            {
                "number": len(references) + 1,
                "publication_id": publication_id,
                "title": candidate.get("title")
                or matching_evidence.get("publication_title")
                or publication_id,
                "authors": candidate.get("authors") or [],
                "year": candidate.get("year"),
                "doi": candidate.get("doi") or matching_evidence.get("doi"),
                "source_url": candidate.get("source_url") or matching_evidence.get("source_url"),
                "publication_type": candidate.get("publication_type"),
                "cited_in_report": publication_id in cited_publication_ids,
            }
        )

    def assertion(value: Any, *, category: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        text = str(value.get("text") or value.get("statement") or "").strip()
        evidence_ids = [
            str(item) for item in value.get("evidence_ids", []) if str(item) in evidence_by_id
        ]
        if not text or not evidence_ids:
            return None
        citations = sorted(
            {
                reference_number[str(evidence_by_id[item].get("publication_id"))]
                for item in evidence_ids
                if str(evidence_by_id[item].get("publication_id")) in reference_number
            }
        )
        return {
            "text": text,
            "category": category,
            "evidence_ids": evidence_ids,
            "citations": citations,
            "qualification": str(value.get("qualification") or "").strip(),
        }

    ai = (
        investigation.get("ai_analysis")
        if isinstance(investigation.get("ai_analysis"), dict)
        else {}
    )
    ai_complete = ai.get("status") in {"complete", "coverage_limited"}
    overall_answer_supported = bool(
        (investigation.get("answer_adequacy") or {}).get("can_answer_overall_question")
    )
    executive = assertion(ai.get("answer"), category="executive_summary") if ai_complete else None
    if executive is None:
        executive = {
            "text": str(
                investigation.get("answer_summary")
                or "The available evidence did not support a summary conclusion."
            ),
            "category": "executive_summary",
            "evidence_ids": [
                str(item)
                for item in investigation.get("summary_evidence_ids", [])
                if str(item) in evidence_by_id
            ],
            "citations": sorted(
                {
                    reference_number[str(evidence_by_id[str(item)].get("publication_id"))]
                    for item in investigation.get("summary_evidence_ids", [])
                    if str(item) in evidence_by_id
                    and str(evidence_by_id[str(item)].get("publication_id")) in reference_number
                }
            ),
            "qualification": "Deterministic extractive summary.",
        }

    findings: list[dict[str, Any]] = []
    if ai_complete:
        for item in ai.get("claims", []):
            category = (
                str(item.get("category") or "finding") if isinstance(item, dict) else "finding"
            )
            converted = assertion(item, category=category)
            if converted and converted not in findings:
                findings.append(converted)
    if not findings and overall_answer_supported:
        for item in investigation.get("findings", []):
            converted = assertion(item, category="finding")
            if converted:
                findings.append(converted)

    actually_cited_evidence = {
        evidence_id
        for item in (executive, *findings)
        if isinstance(item, dict)
        for evidence_id in item.get("evidence_ids", [])
    }
    actually_cited_publications = {
        str(evidence_by_id[evidence_id].get("publication_id"))
        for evidence_id in actually_cited_evidence
        if evidence_id in evidence_by_id
    }
    for reference in references:
        reference["cited_in_report"] = reference["publication_id"] in actually_cited_publications

    categories = {
        name: [item for item in findings if item["category"] == name]
        for name in (
            "claims",
            "agreements",
            "contradictions",
            "method_differences",
            "limitations",
            "uncertainties",
            "assumptions",
            "knowledge_gaps",
        )
    }
    acquisitions = [item for item in run.get("acquisitions", []) if isinstance(item, dict)]
    unreadable_acquisitions = [item for item in acquisitions if item.get("status") == "unreadable"]
    fulltext_screening = [
        item for item in run.get("full_text_screening", []) if isinstance(item, dict)
    ]
    study_matrix = (
        investigation.get("study_matrix")
        if isinstance(investigation.get("study_matrix"), dict)
        else {}
    )
    screening_counts: dict[str, int] = {}
    for item in fulltext_screening:
        decision = str(item.get("decision") or "unclassified")
        screening_counts[decision] = screening_counts.get(decision, 0) + 1
    selected = [item for item in candidates if item.get("screening_status") == "selected"]
    excluded = [item for item in candidates if item.get("screening_status") == "excluded"]
    queries = [item for item in run.get("queries", []) if isinstance(item, dict)]
    providers = sorted(
        {
            str(entry.get("provider"))
            for entry in run.get("search_log", [])
            if isinstance(entry, dict) and entry.get("provider")
        }
    )
    years = [
        int(candidate["year"])
        for candidate in candidates
        if str(candidate.get("id")) in active_ids and isinstance(candidate.get("year"), int)
    ]
    evidence_types: dict[str, int] = {}
    study_designs: dict[str, int] = {}
    validation_statuses: dict[str, int] = {}
    review_states: dict[str, int] = {}
    for item in evidence:
        evidence_type = str(item.get("evidence_type") or "unclassified")
        study_design = str(item.get("study_design") or "unclassified")
        evidence_types[evidence_type] = evidence_types.get(evidence_type, 0) + 1
        study_designs[study_design] = study_designs.get(study_design, 0) + 1
        validation = str(item.get("validation_status") or "unvalidated")
        review_state = str(item.get("review_state") or "unreviewed")
        validation_statuses[validation] = validation_statuses.get(validation, 0) + 1
        review_states[review_state] = review_states.get(review_state, 0) + 1

    explicit_limitations = list(
        dict.fromkeys(
            [
                *[str(item) for item in investigation.get("limitations", []) if str(item).strip()],
                *(
                    [
                        f"{len(unreadable_acquisitions)} acquired document artifact(s) could not be parsed into usable text; OCR or a replacement full text may be required."
                    ]
                    if unreadable_acquisitions
                    else []
                ),
                "The review is limited to records discoverable through the configured metadata providers and to full texts that were openly available, already cached, or supplied by the researcher.",
                "Automated screening and extraction require researcher verification; this report is not a substitute for dual independent screening or a formal risk-of-bias assessment.",
                "Model synthesis uses a bounded set of retrieved evidence passages, so absence from this report is not proof that a finding is absent from the acquired corpus.",
            ]
        )
    )
    quality_flags = list((investigation.get("synthesis") or {}).get("quality_flags") or [])
    plan = investigation.get("plan") if isinstance(investigation.get("plan"), dict) else {}
    question_brief = (
        investigation.get("question_brief")
        if isinstance(investigation.get("question_brief"), dict)
        else None
    )
    landscape = (
        investigation.get("research_landscape")
        if isinstance(investigation.get("research_landscape"), dict)
        else build_research_landscape(investigation)
    )
    answer_evidence_ids: set[str] = set()
    if ai_complete:
        answer_evidence_ids.update(
            str(item) for item in (ai.get("answer") or {}).get("evidence_ids", [])
        )
        answer_evidence_ids.update(
            str(evidence_id)
            for item in ai.get("claims", [])
            if isinstance(item, dict) and item.get("category") in {"claims", "agreements"}
            for evidence_id in item.get("evidence_ids", [])
        )
    contradiction_groups = _assess_contradictions(
        ai.get("contradiction_groups") if ai_complete else None,
        evidence_by_id,
        study_matrix,
        answer_evidence_ids,
        reference_number,
    )
    return {
        "schema_version": "cited_literature_review_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "review_type": "AI-assisted cited evidence review",
        "systematic_review_status": "not_a_systematic_review",
        "title": f"Cited literature review: {question}",
        "question": question,
        "question_interpretation": question_brief,
        "answer_adequacy": investigation.get("answer_adequacy"),
        "run_id": run.get("run_id"),
        "executive_summary": executive,
        "scope": {
            "profile": plan.get("profile_id"),
            "intent": plan.get("intent"),
            "concepts": plan.get("concepts") or [],
            "expanded_terms": plan.get("expanded_terms") or [],
            "evidence_preferences": plan.get("evidence_preferences") or [],
            "decomposition": investigation.get("research_scope"),
        },
        "methodology": {
            "providers": providers,
            "queries": queries,
            "citation_expansion": {
                "seeds": run.get("citation_seeds", 0),
                "candidates": run.get("citation_candidates", 0),
            },
            "full_text_sources": sorted(
                {str(item.get("source")) for item in acquisitions if item.get("source")}
            ),
            "extraction_methods": sorted(
                {
                    str(item.get("extraction_method"))
                    for item in evidence
                    if item.get("extraction_method")
                }
            ),
            "model": {
                "provider": ai.get("provider"),
                "name": ai.get("model"),
                "method": ai.get("method"),
                "validation": ai.get("validation"),
            },
            "coverage_search": run.get("coverage_search"),
            "adaptive_stopping": run.get("adaptive_stopping"),
            "post_acquisition_screening": {
                "method": next(
                    (item.get("method") for item in fulltext_screening if item.get("method")), None
                ),
                "decision_counts": screening_counts,
                "researcher_overrides": sum(
                    bool(item.get("researcher_override")) for item in fulltext_screening
                ),
            },
        },
        "selection_flow": {
            "records_retrieved": run.get("records_retrieved", len(candidates)),
            "unique_candidates": run.get("unique_candidates", len(candidates)),
            "selected_after_automated_screening": run.get("selected_candidates", len(selected)),
            "excluded_after_automated_screening": len(excluded),
            "full_text_acquisition_attempts": run.get("acquisition_attempts", len(acquisitions)),
            "full_texts_unreadable": len(unreadable_acquisitions),
            "full_texts_acquired": run.get("full_texts_acquired", len(active_ids)),
            "full_texts_included_or_background": run.get("full_texts_included", len(active_ids)),
            "full_texts_excluded_or_uncertain": sum(
                count
                for decision, count in screening_counts.items()
                if decision not in {"included", "background"}
            ),
            "publications_cited_in_report": len(actually_cited_publications),
        },
        "corpus_overview": {
            "included_publications": len(active_ids),
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "evidence_types": evidence_types,
            "study_designs": study_designs,
            "relevant_passages": len(evidence),
            "validation_statuses": validation_statuses,
            "review_states": review_states,
        },
        "study_matrix_summary": study_matrix.get("summary") or {},
        "research_landscape": landscape,
        "findings": findings,
        "thematic_findings": categories,
        "contradiction_groups": contradiction_groups,
        "answer_contest": _answer_contest(contradiction_groups),
        "measurements": ai.get("measurements", []) if ai_complete else [],
        "quality": {
            "quality_flags": quality_flags,
            "limitations": explicit_limitations,
            "formal_risk_of_bias_completed": False,
            "source_grounding_is_not_expert_validation": True,
        },
        "research_implications": [
            str(item.get("label") or item.get("question") or item)
            if isinstance(item, dict)
            else str(item)
            for item in investigation.get("follow_up_questions", [])
        ],
        "conclusion": executive,
        "references": references,
        "appendices": {
            "search_queries": queries,
            "excluded_records": [
                {
                    "publication_id": item.get("id"),
                    "title": item.get("title"),
                    "reason": item.get("screening_reason"),
                    "researcher_decision": (run.get("review_decisions") or {}).get(
                        str(item.get("id"))
                    ),
                }
                for item in excluded
            ],
            "evidence_records": evidence,
            "rejected_model_records": ai.get("rejected_records", []) if ai_complete else [],
            "full_text_screening": fulltext_screening,
            "study_matrix": study_matrix,
        },
    }


def render_review_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_review_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"**Review type:** {report['review_type']}  ",
        "**Status:** This is not yet a systematic review.  ",
        f"**Generated:** {report['generated_at']}",
        "",
    ]
    lines += ["## Executive summary", "", _cited(report["executive_summary"]), ""]
    adequacy = report.get("answer_adequacy") or {}
    if adequacy:
        lines += [
            "## Answer adequacy",
            "",
            f"**Decision:** {_label(str(adequacy.get('status') or 'unknown'))}.  ",
            str(adequacy.get("decision") or "No adequacy decision was recorded."),
            "",
        ]
        if adequacy.get("missing_requirements"):
            lines += [
                "Missing requirements: "
                + ", ".join(str(item) for item in adequacy["missing_requirements"])
                + ".",
                "",
            ]
        lines += ["| Required coverage check | Result | Publications |", "|---|---|---:|"]
        lines += [
            f"| {item.get('label')} | {'passed' if item.get('passed') else 'missing'} | {item.get('publication_count', 0)} |"
            for item in adequacy.get("checks", [])
            if item.get("required")
        ]
    scope = report["scope"]
    lines += [
        "## Research question and scope",
        "",
        report["question"],
        "",
        f"Profile: `{scope.get('profile') or 'generic'}`. Concepts: {', '.join(scope.get('concepts') or []) or 'not specified'}.",
        "",
    ]
    methods = report["methodology"]
    lines += [
        "## Methodology",
        "",
        f"Providers: {', '.join(methods['providers']) or 'not recorded'}.",
        f"Full-text sources: {', '.join(methods['full_text_sources']) or 'not recorded'}.",
        f"Extraction: {', '.join(methods['extraction_methods']) or 'not recorded'}.",
        "",
        "### Search strategies",
        "",
    ]
    lines += [
        f"- **{item.get('purpose', 'query')}:** `{item.get('text', '')}`"
        for item in methods["queries"]
    ] or ["- No query ledger was available."]
    stopping = methods.get("adaptive_stopping") or {}
    if stopping:
        lines += [
            "",
            "### Adaptive full-text stopping",
            "",
            str(stopping.get("explanation") or "No stopping explanation was recorded."),
            "",
            f"Review mode: `{stopping.get('review_mode') or 'unknown'}`. Initial target: {stopping.get('initial_target', 0)}. Hard cap: {stopping.get('hard_cap', 0)}. Coverage checks: {len(stopping.get('evaluations') or [])}.",
        ]
    flow = report["selection_flow"]
    lines += ["", "## Selection flow", "", "| Stage | Count |", "|---|---:|"]
    lines += [f"| {_label(key)} | {value} |" for key, value in flow.items()]
    corpus = report["corpus_overview"]
    years = f"{corpus['year_min']}–{corpus['year_max']}" if corpus["year_min"] else "not recorded"
    lines += [
        "",
        "## Corpus overview",
        "",
        f"The acquired corpus contains {corpus['included_publications']} publications ({years}) and {corpus['relevant_passages']} retrieved evidence passages.",
        "",
    ]
    lines += [
        f"Evidence types: {_distribution(corpus['evidence_types'])}.  ",
        f"Study designs: {_distribution(corpus['study_designs'])}.",
        "",
    ]
    lines += [
        f"Automatic validation: {_distribution(corpus['validation_statuses'])}.  ",
        f"Review states: {_distribution(corpus['review_states'])}.",
        "",
    ]
    screening = methods.get("post_acquisition_screening") or {}
    if screening.get("decision_counts"):
        lines += [
            "## Full-text inclusion quality",
            "",
            "Successfully acquiring a document did not automatically include it. Parsed full texts were screened against the question before analysis and packaging.",
            "",
            f"Decisions: {_distribution(screening['decision_counts'])}.  ",
            f"Method: `{screening.get('method') or 'not recorded'}`. Researcher overrides: {screening.get('researcher_overrides', 0)}.",
            "",
        ]
    matrix = report["appendices"].get("study_matrix") or {}
    cards = matrix.get("studies") or []
    if cards:
        lines += [
            "## Study-by-study evidence matrix",
            "",
            "Each row records the question-specific full-text decision and the source-grounded dimensions found in that study.",
            "",
            "| Study | Design or evidence nature | Decision | Supported question dimensions |",
            "|---|---|---|---|",
        ]
        for card in cards:
            supported = [
                str(item.get("label"))
                for item in card.get("dimension_coverage", [])
                if item.get("status") == "supported"
            ]
            nature = (card.get("inferred_evidence_nature") or {}).get("label") or "unclassified"
            decision = (card.get("screening") or {}).get("decision") or "unclassified"
            title = str(card.get("title") or card.get("publication_id")).replace("|", "\\|")
            lines.append(
                f"| {title} | {nature} | {decision} | {', '.join(supported) or 'none found'} |"
            )
        lines.append("")
    landscape = report.get("research_landscape") or {}
    landscape_coverage = landscape.get("coverage") or {}
    if landscape_coverage:
        lines += [
            "## Research landscape",
            "",
            "Landscape statistics describe the deduplicated discovery results, including metadata-only records; they do not imply that every record was available as full text or used as evidence.",
            "",
            "| Landscape population | Count |",
            "|---|---:|",
            f"| Discovered metadata records | {landscape_coverage.get('records', 0)} |",
            f"| Selected for acquisition | {landscape_coverage.get('selected_for_acquisition', 0)} |",
            f"| Full texts acquired and included in the package | {landscape_coverage.get('full_texts_acquired', 0)} |",
            f"| Publications cited in the review | {landscape_coverage.get('publications_cited_in_review', 0)} |",
            "",
        ]
        timeline = landscape.get("publication_timeline") or []
        if timeline:
            lines += ["### Publications by year", "", "| Year | Discovered records |", "|---|---:|"]
            lines += [
                f"| {item.get('year')} | {item.get('publications', 0)} |" for item in timeline
            ]
            lines.append("")
        for heading, key, name_key in (
            ("Leading organizations in the discovered set", "top_organizations", "name"),
            ("Leading authors in the discovered set", "top_authors", "name"),
        ):
            items = landscape.get(key) or []
            if items:
                lines += [f"### {heading}", "", "| Name | Publications |", "|---|---:|"]
                lines += [
                    f"| {item.get(name_key)} | {item.get('publications', 0)} |"
                    for item in items[:15]
                ]
                lines.append("")
        signals = landscape.get("title_term_signals") or []
        if signals:
            method = landscape.get("trend_method") or {}
            lines += [
                "### Transparent title-term signals",
                "",
                f"Windows: {method.get('baseline_from')}–{method.get('baseline_to')} versus {method.get('recent_from')}–{method.get('recent_to')}.",
                "",
                "| Term | Earlier | Recent | Change | Signal |",
                "|---|---:|---:|---:|---|",
            ]
            lines += [
                f"| {item.get('term')} | {item.get('baseline_publications', 0)} | {item.get('recent_publications', 0)} | {item.get('absolute_change', 0)} | {item.get('classification')} |"
                for item in signals
            ]
            lines.append("")
        lines += ["### Landscape limitations", ""]
        lines += [f"- {item}" for item in landscape.get("limitations", [])] or [
            "- No landscape limitations were recorded."
        ]
        lines.append("")
    lines += ["## Findings by theme", ""]
    if report["findings"]:
        for item in report["findings"]:
            lines += [f"### {_label(item['category'])}", "", _cited(item), ""]
    else:
        lines += ["No grounded cross-paper findings survived validation.", ""]
    lines += ["## Contradictions, methods, and comparability", ""]
    if report.get("contradiction_groups"):
        lines += ["### Where studies disagree", ""]
        for group in report["contradiction_groups"]:
            lines.append(
                f"- **{group['topic']}** — severity: {group['severity']}; "
                f"cause: {_label(str(group['cause']))}."
            )
            for position in group["positions"]:
                lines.append(
                    "  - "
                    + _cited(
                        {"text": position["stance"], "citations": position.get("citations", [])}
                    )
                )
        lines.append("")
    comparison_items = [
        *report["thematic_findings"].get("contradictions", []),
        *report["thematic_findings"].get("method_differences", []),
    ]
    lines += [f"- {_cited(item)}" for item in comparison_items] or [
        "No grounded contradiction or method-difference records survived validation."
    ]
    lines += ["## Contextual numerical evidence", ""]
    if report["measurements"]:
        lines += ["| Metric | Value | Unit | Context | Source |", "|---|---:|---|---|---|"]
        for item in report["measurements"]:
            evidence = next(
                (
                    e
                    for e in report["appendices"]["evidence_records"]
                    if e.get("id") == item.get("evidence_id")
                ),
                {},
            )
            ref = next(
                (
                    r["number"]
                    for r in report["references"]
                    if r["publication_id"] == evidence.get("publication_id")
                ),
                "?",
            )
            context = item.get("context") or {}
            lines.append(
                f"| {item.get('metric')} | {item.get('value')} | {item.get('unit')} | {context.get('evidence_nature', 'unknown')}; {context.get('method', 'unknown')}; {context.get('scale', 'unknown')} | [{ref}] |"
            )
    else:
        lines += ["No contextual numerical records passed model validation for this question."]
    lines += ["", "## Evidence quality and review limitations", ""]
    lines += [f"- {item}" for item in report["quality"]["limitations"]]
    if report["quality"]["quality_flags"]:
        lines += [
            f"- Quality flag: {_label(str(item))}" for item in report["quality"]["quality_flags"]
        ]
    lines += ["", "## Knowledge gaps and research implications", ""]
    gaps = report["thematic_findings"].get("knowledge_gaps") or []
    lines += [f"- {_cited(item)}" for item in gaps]
    lines += [f"- Suggested next question: {item}" for item in report["research_implications"]] or [
        "- No next questions were generated."
    ]
    lines += ["", "## Conclusion", "", _cited(report["conclusion"]), "", "## References", ""]
    for item in report["references"]:
        authors = ", ".join(item.get("authors") or []) or "Authors not recorded"
        doi = f" https://doi.org/{item['doi']}" if item.get("doi") else ""
        lines.append(
            f"{item['number']}. {authors} ({item.get('year') or 'n.d.'}). *{item['title']}*.{doi}"
        )
    lines += ["", "## Appendix A — Excluded records", ""]
    excluded = report["appendices"]["excluded_records"]
    lines += [
        f"- {item['title']}: {item.get('reason') or 'reason not recorded'}" for item in excluded
    ] or ["- None recorded."]
    lines += ["", "## Appendix B — Verifiable evidence passages", ""]
    for item in report["appendices"]["evidence_records"]:
        ref = next(
            (
                r["number"]
                for r in report["references"]
                if r["publication_id"] == item.get("publication_id")
            ),
            "?",
        )
        lines += [
            f"### Evidence `{item.get('id')}` — [{ref}]",
            "",
            f"Section: {item.get('section') or 'unknown'}; page: {item.get('page') or 'not encoded'}; extraction: `{item.get('extraction_method')}`.",
            "",
            f"> {item.get('passage')}",
            "",
        ]
    lines += ["## Appendix C — Post-acquisition full-text screening", ""]
    screened = report["appendices"].get("full_text_screening") or []
    lines += [
        f"- **{_label(str(item.get('decision') or 'unclassified'))}:** {item.get('publication_id')} — {item.get('reason')}"
        for item in screened
    ] or ["- No post-acquisition screening ledger was recorded."]
    lines += ["", "## Appendix D — Question-specific study cards", ""]
    for card in cards:
        lines += [
            f"### {card.get('title') or card.get('publication_id')}",
            "",
            f"Decision: `{(card.get('screening') or {}).get('decision') or 'unclassified'}`. Evidence nature: `{(card.get('inferred_evidence_nature') or {}).get('label') or 'unclassified'}`.",
            "",
        ]
        for passage in card.get("selected_passages", [])[:3]:
            lines += [
                f"Passage `{passage.get('id')}`; section: {passage.get('section') or 'unknown'}; page: {passage.get('page') or 'not encoded'}; characters: {passage.get('start_char')}–{passage.get('end_char')}.",
                "",
                f"> {passage.get('passage')}",
                "",
            ]
    if not cards:
        lines += ["No question-specific study cards were recorded.", ""]
    return "\n".join(lines).strip() + "\n"


def render_review_html(report: dict[str, Any]) -> str:
    markdown = render_review_markdown(report)
    body: list[str] = []
    in_table = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("|---"):
            continue
        if line.startswith("|"):
            cells = [html.escape(cell.strip()) for cell in line.strip("|").split("|")]
            if not in_table:
                body.append("<table>")
                in_table = True
            body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("> "):
            body.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
        elif line.startswith("- "):
            body.append(f"<p class='bullet'>• {html.escape(line[2:])}</p>")
        elif line:
            body.append(f"<p>{_inline_html(line)}</p>")
    if in_table:
        body.append("</table>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + html.escape(report["title"])
        + "</title><style>body{font:16px/1.55 Arial,sans-serif;color:#222;max-width:900px;margin:40px auto;padding:0 24px}h1{border-top:12px solid #FFCD00;padding-top:20px}h2{margin-top:2.5rem;border-bottom:1px solid #ccc}h3{margin-top:1.5rem}table{border-collapse:collapse;width:100%;margin:1rem 0}td{border:1px solid #ccc;padding:.55rem;vertical-align:top}blockquote{border-left:5px solid #FFCD00;margin:1rem 0;padding:.25rem 1rem;color:#444}.bullet{margin:.25rem 0 0 1rem}code{background:#f2f2f2;padding:.1rem .25rem}</style></head><body>"
        + "".join(body)
        + "</body></html>"
    )


def render_review_pdf(report: dict[str, Any]) -> bytes:
    return markdown_to_pdf(
        render_review_markdown(report), title=str(report.get("title") or "Literature review")
    )


_SEVERITY_RANK = {"high": 0, "moderate": 1, "low": 2}


def _assess_contradictions(
    raw: Any,
    evidence_by_id: dict[str, dict[str, Any]],
    study_matrix: dict[str, Any],
    answer_evidence_ids: set[str],
    reference_number: dict[str, int],
) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    natures = {
        str(card.get("publication_id")): str(
            (card.get("inferred_evidence_nature") or {}).get("label") or "unclassified"
        )
        for card in study_matrix.get("studies", [])
        if isinstance(card, dict)
    }
    assessed: list[dict[str, Any]] = []
    for group in raw:
        if not isinstance(group, dict):
            continue
        positions = [item for item in group.get("positions", []) if isinstance(item, dict)]
        evidence_ids = {str(e) for item in positions for e in item.get("evidence_ids", [])}
        if len(positions) < 2 or not evidence_ids <= set(evidence_by_id):
            continue
        touches = bool(evidence_ids & answer_evidence_ids)
        try:
            severity, basis = assess_severity(
                str(group.get("cause")),
                [[str(p) for p in item.get("publication_ids", [])] for item in positions],
                touches_answer=touches,
                evidence_nature_by_publication=natures,
            )
        except (KeyError, ValueError):
            continue
        assessed.append(
            {
                **group,
                "positions": [
                    {
                        **item,
                        "citations": sorted(
                            {
                                reference_number[str(p)]
                                for p in item.get("publication_ids", [])
                                if str(p) in reference_number
                            }
                        ),
                    }
                    for item in positions
                ],
                "severity": severity.value,
                "severity_basis": list(basis),
                "severity_rules_version": SEVERITY_RULES_VERSION,
                "touches_answer": touches,
                "dimension_ids": sorted(
                    {
                        str(dimension)
                        for e in evidence_ids
                        for dimension in evidence_by_id[e].get("scope_dimension_ids") or []
                    }
                ),
            }
        )
    assessed.sort(
        key=lambda g: (
            _SEVERITY_RANK[g["severity"]],
            -sum(len(item.get("publication_ids", [])) for item in g["positions"]),
            str(g.get("id")),
        )
    )
    return assessed


def _answer_contest(groups: list[dict[str, Any]] | None) -> dict[str, Any]:
    contested = [g for g in groups or [] if g["severity"] == "high" and g["touches_answer"]]
    return {
        "contested": bool(contested),
        "group_ids": [str(g.get("id")) for g in contested],
        "qualifications": [
            f"Studies disagree on {g.get('topic')}; see the contradiction group." for g in contested
        ],
    }


def _cited(item: dict[str, Any]) -> str:
    citations = "".join(f"[{number}]" for number in item.get("citations", []))
    return f"{item.get('text', '')} {citations}".strip()


def _distribution(values: dict[str, int]) -> str:
    return (
        ", ".join(f"{_label(key)} ({value})" for key, value in sorted(values.items()))
        or "none classified"
    )


def _label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _inline_html(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped
