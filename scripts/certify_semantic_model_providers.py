#!/usr/bin/env python
"""Certify BYO models against ShopSquire's constrained semantic-proposal boundary.

This is intentionally narrower than a prose benchmark: each model must return schema-valid,
query-anchored proposals.  The deterministic validator—not the model—decides whether the output
may enter semantic reduction.  Results are printed as JSON; callers may redirect them to an
external evidence directory without adding generated reports to the repository.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.app.services.llm_providers import OllamaProvider, invocation_version_trace
from src.app.services.semantic_resolution import validate_semantic_proposal


CASES = (
    "Please recommend a laptop for simulating a digital twin for maintenance of mechanical machines.",
    "Find 20 chairs made from iron birch for a hotel refurbishment.",
)


def _prompt(query: str) -> str:
    return f"""Return JSON only. Interpret the buyer request without inventing facts.
Schema:
{{
  "desired_outcome": "string",
  "concepts": [{{"text":"exact span from buyer request","status":"unresolved|ambiguous|resolved","material":true,"interpretations":[]}}],
  "evidence_questions": [{{"question_id":"stable_id","question":"question","purpose":"resolve_concept|resolve_compatibility|resolve_performance_target|resolve_product_identity|resolve_safety_or_policy","material":true}}],
  "proposed_action":"research_then_clarify|research|clarify|search_catalog|answer|align_off_catalog",
  "confidence":0.0
}}
Do not include hardware requirements, product claims, prices, inventory or citations. Those come from tools.
Buyer request: {query}"""


def _json_object(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def main() -> int:
    models = [
        item.strip() for item in os.getenv(
            "SEMANTIC_CERT_MODELS", "qwen3:14b,qwen3.6:27b"
        ).split(",") if item.strip()
    ]
    provider = OllamaProvider()
    results: list[dict[str, Any]] = []
    for model in models:
        for query in CASES:
            started = time.monotonic()
            response = provider.generate(
                _prompt(query),
                model=model,
                max_tokens=500,
                temperature=0,
                prompt_version="semantic-proposal-cert-v1",
                policy_version="semantic-authority-v1",
                format="json",
                think=False,
                timeout_s=float(os.getenv("SEMANTIC_CERT_TIMEOUT_SEC", "60")),
            )
            raw = _json_object(str(response.get("text") or ""))
            validation = validate_semantic_proposal(raw, query=query) if raw else None
            results.append({
                **invocation_version_trace(model=model, provider="ollama", values={
                    "prompt_version": "semantic-proposal-cert-v1",
                    "policy_version": "semantic-authority-v1",
                }),
                "query": query,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "transport_ok": not str(response.get("text") or "").startswith("[ollama error:"),
                "json_object": raw is not None,
                "validation": validation.as_dict() if validation else {
                    "outcome": "rejected", "reasons": ["provider_output_not_json"]
                },
            })
    print(json.dumps({"contract": "semantic-model-provider-cert-v1", "results": results}, indent=2))
    return 0 if all(item["validation"]["outcome"] == "valid" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
