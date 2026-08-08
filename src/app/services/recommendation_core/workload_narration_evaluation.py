"""Deterministic shadow-narration corpus and fidelity evaluation harness."""
from __future__ import annotations

from statistics import median
from typing import Any, Callable, Mapping

from src.app.services.recommendation_core.workload_narration_rollout import (
    NarrationRolloutPolicy,
    decide_shadow_rollout,
)
from src.app.services.recommendation_core.workload_narration_shadow import (
    run_shadow_narration,
)
from src.app.services.six_prompt_research_certification import (
    SCENARIOS,
    certify_six_prompt_fixture,
)


def _preserve(requirement_id: str, *terms: str) -> dict[str, Any]:
    return {"requirement_id": requirement_id, "required_terms": list(terms)}


def _research_case(prompt: str) -> dict[str, Any]:
    result = certify_six_prompt_fixture(prompt)
    top = result.products[0]
    safe_unknowns = [
        "CPU, RAM and GPU values remain unresolved until a named local application and scale are supplied"
        if "floor require a named local application" in value
        else value
        for value in top.unknowns
    ]
    rows: list[dict[str, Any]] = []
    for key in top.meets:
        rows.append({
            "attribute_key": key, "attribute_label": key.replace("_", " "),
            "verdict": "meets_minimum", "requirement_claim_ids": [f"req-{key}"],
            "capability_claim_ids": [f"cap-{key}"],
        })
    for key in top.misses:
        rows.append({
            "attribute_key": key, "attribute_label": key.replace("_", " "),
            "verdict": "fails_minimum", "requirement_claim_ids": [f"req-{key}"],
            "capability_claim_ids": [f"cap-{key}"],
        })
    for index, gap in enumerate(safe_unknowns):
        rows.append({
            "attribute_key": f"gap_{index}", "attribute_label": gap,
            "verdict": "unknown", "requirement_claim_ids": [],
            "capability_claim_ids": [],
        })
    blocks = [
        f"The current result for {result.scenario_id.replace('_', ' ')} is {top.status}.",
    ]
    if top.meets:
        blocks.append("Verified meets: " + ", ".join(key.replace("_", " ") for key in top.meets) + ".")
    if top.misses:
        blocks.append("It does not meet: " + ", ".join(key.replace("_", " ") for key in top.misses) + ".")
    if safe_unknowns:
        blocks.append("Still unresolved or not verified: " + "; ".join(safe_unknowns) + ".")
    preservation = [
        _preserve(f"gap-{index}", gap)
        for index, gap in enumerate(safe_unknowns)
    ] + [
        _preserve(f"miss-{key}", key.replace("_", " "))
        for key in top.misses
    ]
    return {
        "case_id": f"research-{result.scenario_id}",
        "category": "research_prompt",
        "decision": {
            "schema_version": "workload-decision-shadow-eval-v1",
            "workload": {
                "desired_outcome": prompt,
                "material_unknowns": safe_unknowns,
            },
            "product": {"sku": top.sku, "title": top.title},
            "overall_decision": {
                "qualified": "qualified_for_stated_scope",
                "conditional": "conditional",
                "failed": "not_qualified",
            }[top.status],
            "performance_status": "not_verified",
            "budget_status": "unknown",
            "fit_ledger": rows,
            "critic": {"status": "pass"},
            "authorized_narration_blocks": blocks,
            "material_preservation": preservation,
        },
    }


def build_shadow_evaluation_corpus() -> tuple[dict[str, Any], ...]:
    cases = [_research_case(scenario.prompt) for scenario in SCENARIOS]
    cases.extend([
        {
            "case_id": "uploaded-requirements-provisional",
            "category": "uploaded_requirements",
            "decision": {
                "schema_version": "workload-decision-shadow-eval-v1",
                "workload": {"desired_outcome": "Use buyer-uploaded requirements", "material_unknowns": ["exact product RAM ceiling", "GPU power limit"]},
                "product": {"sku": "UPLOAD-CANDIDATE"},
                "overall_decision": "conditional", "performance_status": "not_verified",
                "budget_status": "unknown",
                "fit_ledger": [
                    {"attribute_key": "ram_ceiling", "attribute_label": "exact product RAM ceiling", "verdict": "unknown"},
                    {"attribute_key": "gpu_tgp_w", "attribute_label": "GPU power limit", "verdict": "unknown"},
                ],
                "critic": {"status": "pass"},
                "authorized_narration_blocks": [
                    "The buyer-uploaded 64 GB RAM and 2 TB NVMe requirements are accepted provisionally, not independently verified.",
                    "The exact product RAM ceiling and GPU power limit remain unresolved.",
                ],
                "material_preservation": [
                    _preserve("upload-authority", "provisionally", "not independently verified"),
                    _preserve("upload-gaps", "exact product RAM ceiling", "GPU power limit"),
                ],
            },
        },
        {
            "case_id": "budget-conflict",
            "category": "budget_conflict",
            "decision": {
                "schema_version": "workload-decision-shadow-eval-v1",
                "workload": {"desired_outcome": "Meet the accepted workload floor", "material_unknowns": []},
                "product": {"sku": "STRETCH-01", "price_cents": 349900},
                "overall_decision": "conditional", "performance_status": "not_verified",
                "budget_status": "over", "budget_ceiling_cents": 250000,
                "fit_ledger": [], "critic": {"status": "pass"},
                "authorized_narration_blocks": [
                    "This option is over the AUD 2,500 budget ceiling by AUD 999.",
                    "Keep the verified floor, relax budget, or choose a lower-cost compromise.",
                ],
                "material_preservation": [
                    _preserve("budget-conflict", "over", "budget ceiling"),
                ],
            },
        },
        {
            "case_id": "exact-product-gaps",
            "category": "exact_product_gaps",
            "decision": {
                "schema_version": "workload-decision-shadow-eval-v1",
                "workload": {"desired_outcome": "Qualify the exact retailer configuration", "material_unknowns": ["GPU power limit", "warranty duration"]},
                "product": {"sku": "RETAILER-SKU-UNKNOWN-MPN"},
                "overall_decision": "conditional", "performance_status": "not_verified",
                "budget_status": "within",
                "fit_ledger": [
                    {"attribute_key": "os_edition", "attribute_label": "OS edition", "verdict": "fails_minimum", "required_text": "Windows 11 Pro", "observed_text": "Windows 11 Home", "requirement_claim_ids": ["req-os-pro"], "capability_claim_ids": ["cap-os-home"]},
                    {"attribute_key": "gpu_tgp_w", "attribute_label": "GPU power limit", "verdict": "contested"},
                    {"attribute_key": "warranty_duration", "attribute_label": "warranty duration", "verdict": "unknown"},
                ],
                "critic": {"status": "pass"},
                "authorized_narration_blocks": [
                    "The OS edition does not meet the accepted Windows 11 Pro requirement.",
                    "The exact configuration remains conditional: GPU power limit and warranty duration are unresolved or contested.",
                ],
                "material_preservation": [
                    _preserve("identity-miss", "OS edition", "does not meet"),
                    _preserve("identity-gaps", "GPU power limit", "warranty duration"),
                ],
            },
        },
        {
            "case_id": "supplier-choice",
            "category": "supplier_choice",
            "decision": {
                "schema_version": "workload-decision-shadow-eval-v1",
                "workload": {"desired_outcome": "Obtain 30 units within 10 days", "material_unknowns": ["supplier confirmation for 18 units"]},
                "product": {"sku": "PREFERRED-01"},
                "overall_decision": "conditional", "performance_status": "not_verified",
                "budget_status": "within", "availability_status": "partial",
                "fit_ledger": [
                    {"attribute_key": "supplier_balance", "attribute_label": "supplier confirmation for 18 units", "verdict": "unknown"},
                ],
                "supplier_choices": [
                    "split 12 now and 18 later", "wait for preferred fit",
                    "take the next-best verified option now", "ask suppliers for all 30",
                ],
                "critic": {"status": "pass"},
                "authorized_narration_blocks": [
                    "Only 12 units are confirmed now; supplier confirmation for 18 units remains unresolved.",
                    "Choices: split 12 now and 18 later; wait for preferred fit; take the next-best verified option now; or ask suppliers for all 30.",
                    "Supplier enquiry and cart change are not authorized yet.",
                ],
                "material_preservation": [
                    _preserve("supplier-balance", "supplier confirmation for 18 units"),
                    _preserve("supplier-choices", "split 12 now and 18 later", "wait for preferred fit", "take the next-best verified option now", "ask suppliers for all 30"),
                    _preserve("supplier-authority", "not authorized"),
                ],
            },
        },
    ])
    return tuple(cases)


def evaluate_shadow_corpus(
    *,
    generate: Callable[[str], str],
    model_id: str,
    corpus: tuple[Mapping[str, Any], ...] | None = None,
) -> dict[str, Any]:
    selected = tuple(corpus or build_shadow_evaluation_corpus())
    results: list[dict[str, Any]] = []
    unsupported = 0
    preservation_failures = 0
    elapsed: list[int] = []
    policy = NarrationRolloutPolicy(mode="shadow", canary_percent=100)
    for item in selected:
        decision = dict(item["decision"])
        shadow = run_shadow_narration(decision, generate=generate, model_id=model_id)
        violations = list(shadow.get("violations") or [])
        preservation = [
            value for value in violations
            if "_omitted" in value or value.startswith("material_fact_omitted:")
        ]
        unsupported_rows = [value for value in violations if value not in preservation]
        rollout = decide_shadow_rollout(
            decision, shadow, tenant_id="shadow-certification",
            identity_id=str(item["case_id"]), policy=policy,
        )
        elapsed.append(int(shadow.get("elapsed_ms") or 0))
        unsupported += len(unsupported_rows)
        preservation_failures += len(preservation)
        results.append({
            "case_id": item["case_id"], "category": item["category"],
            "shadow": shadow, "unsupported_claim_violations": unsupported_rows,
            "preservation_failures": preservation,
            "rollout": rollout.model_dump(mode="json"),
        })
    passed = all(row["shadow"]["status"] == "accepted_shadow" for row in results)
    return {
        "schema_version": "workload-narration-shadow-evaluation-v1",
        "model_id": model_id, "case_count": len(results), "results": results,
        "unsupported_claim_count": unsupported,
        "preservation_failure_count": preservation_failures,
        "fidelity_passed": passed and unsupported == 0 and preservation_failures == 0,
        "buyer_visible": False, "commercial_authority_granted": False,
        "latency_observation": {
            "samples_ms": elapsed,
            "median_ms": int(median(elapsed)) if elapsed else None,
            "max_ms": max(elapsed) if elapsed else None,
            "certification_status": "observed_separately_not_a_fidelity_gate",
        },
    }


__all__ = ["build_shadow_evaluation_corpus", "evaluate_shadow_corpus"]
