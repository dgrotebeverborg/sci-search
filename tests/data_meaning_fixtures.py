"""Positive model transport double for extraction/replay tests.

These tests exercise readers, arithmetic, retention and replay, not the model's
scientific judgment. The fake reviewer explicitly supports each published
measure and returns source-present citations. Rejection/grounding cases live in
test_data_semantics; this helper is never installed globally.
"""

import json


def positive_review(prompt):
    context = json.loads(prompt.split("\n", 1)[1])
    documents = context["evidence_documents"]
    key, text = next((k, v) for k, v in documents.items() if len(v.strip()) >= 3)
    return {
        "measurements": [
            {
                "measurement": name,
                "transformation": "direct",
                "followup_question": "",
                "checks": [
                    {
                        "aspect": aspect,
                        "status": "supported",
                        "reason": "Positive transport fixture",
                        "evidence": [{"document": key, "quote": text[:200]}],
                    }
                    for aspect in ("definition", "unit", "geography", "time", "calculation")
                ],
            }
            for name in context["measurements"]
        ]
    }


def with_positive_meaning_review(complete):
    def wrapped(prompt, schema):
        if set(schema["properties"]) == {"measurements"}:
            return positive_review(prompt)
        reply = complete(prompt, schema)
        if "accepted" in schema["properties"] and reply.get("accepted") is True:
            return {**reply, **positive_review(prompt)}
        return reply

    return wrapped
