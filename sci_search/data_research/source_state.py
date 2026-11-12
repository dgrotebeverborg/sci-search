"""Stable retained-source identity with a positional API compatibility adapter."""

import copy


def state_snapshot(result):
    """Planning reads an isolated observation of the latest published state."""
    return copy.deepcopy({key: result.get(key, []) for key in ("analyses", "assessments")})


def resolve_source(reference, assessments, retained):
    """Resolve a current API index or stable ID to its assessment and retained bytes.

    Historical callers may retain integer-keyed records. New records are keyed
    by source_id, so a later assessment reorder cannot change the source bytes.
    """
    if type(reference) is int:
        if not 0 <= reference < len(assessments):
            raise ValueError("Invalid source assessment position")
        assessment = assessments[reference]
        key = assessment.get("source_id", reference)
    else:
        if not isinstance(reference, str) or not reference:
            raise ValueError("Invalid source identity")
        matches = [a for a in assessments if a.get("source_id") == reference]
        if len(matches) != 1:
            raise ValueError("Unknown or ambiguous source identity")
        assessment = matches[0]
        key = reference
    return assessment, retained.get(key)


def restore_retained(directory, assessments):
    """Restore only context tied to one assessment and exact retained byte digests.

    Older runs without digest-bearing context remain readable, but do not gain
    reassessment inputs. Folder order never supplies identity for legacy runs.
    """
    import hashlib
    import json
    from pathlib import Path

    from sci_search.data_research.artifact_validation import validate_artifacts

    retained = {}
    for folder in Path(directory).glob("source-*"):
        context_path, assessment_path = folder / "source-context.json", folder / "assessment.json"
        # Dossiers are metadata rather than sealed execution artifacts; never
        # follow links while discovering their identity and expected digests.
        if any(p.is_symlink() for p in (context_path, assessment_path, folder, *folder.parents)):
            continue
        try:
            context = json.loads(context_path.read_text())
            saved_assessment = json.loads(assessment_path.read_text())
            if not isinstance(context, dict) or not isinstance(saved_assessment, dict):
                continue
            source_id = context.get("source_id", folder.name)
            if source_id != folder.name or context.get("folder", folder.name) != folder.name:
                continue
            matches = [
                a
                for a in assessments
                if a.get("source_id") == source_id
                or ("source_id" not in a and a == saved_assessment)
            ]
            if len(matches) != 1:
                continue
            assessment = matches[0]
            source_digest, context_digest = (
                assessment.get("source_digest"),
                assessment.get("context_digest"),
            )
            if (
                not source_digest
                or not context_digest
                or not isinstance(context.get("source"), dict)
                or context["source"].get("sha256") != source_digest
                or not isinstance(context.get("metadata"), str)
            ):
                continue
            if hashlib.sha256(context["metadata"].encode()).hexdigest() != context_digest:
                continue
            for name in ("download.bin", "source.bin", "landing.bin"):
                try:
                    validate_artifacts(folder, {name: source_digest})
                except ValueError:
                    continue
                retained[source_id] = {
                    **context,
                    "source_id": source_id,
                    "folder": folder.name,
                    "body": (folder / name).read_bytes(),
                }
                assessment["source_id"] = source_id
                break
        except (OSError, ValueError, KeyError, TypeError):
            # Missing or malformed old dossiers cannot introduce new evidence.
            continue
    return retained
