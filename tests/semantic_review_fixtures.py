"""Explicit positive review transport fixtures for grounding/provider tests.

Semantic rejection behavior is exercised separately in test_claim_support.
"""

import json


def reviewed_response(body, generation_response):
    if body["response_format"]["json_schema"]["name"] != "scientific_claim_support":
        return generation_response
    request = json.loads(body["messages"][1]["content"])
    judgments = [
        {
            "id": item["id"],
            "entailed": True,
            "causal_direction_valid": True,
            "geographic_scope_valid": True,
            "relevant": True,
            "reason": "Supported in this positive transport fixture.",
        }
        for item in request["assertions"]
    ]
    return {
        "choices": [{"message": {"content": json.dumps({"judgments": judgments})}}],
        "usage": {},
    }
