"""Truthful execution ontology for recommendation traces.

An execution step is not automatically an agent. The contract distinguishes model proposals,
deterministic authorization, deterministic stages, connectors, workflows, and human approvals.
It is additive while legacy ``agent_chain`` consumers migrate.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _stage_kind(name: str) -> str:
    value = str(name or "").lower()
    if value == "route+intent":
        return "model"
    if "evidence" in value or "inventory" in value or "market" in value:
        return "connector"
    return "stage"


def build_execution_steps(core: Any) -> List[Dict[str, Any]]:
    """Project a finalized core response into auditable authority boundaries."""
    decision = dict((getattr(core, "extras", {}) or {}).get("decision") or {})
    proposal = dict(decision.get("model_proposal") or {})
    changes = list(decision.get("authorization_changes") or [])
    clamped = [item for item in changes if str(item).endswith(":clamped")]
    stages = list((getattr(core, "extras", {}) or {}).get("stage_results") or [])
    route_stage = next((s for s in stages if s.get("stage") == "route+intent"), {})

    steps: List[Dict[str, Any]] = [{
        "id": "model-proposal",
        "kind": "model",
        "authority": "proposes",
        "label": "Interpret shopper request",
        "status": "completed" if proposal else "degraded",
        "source": decision.get("source") or "unknown",
        "latency_ms": route_stage.get("latency_ms"),
        "output": proposal,
    }, {
        "id": "platform-authorization",
        "kind": "gate",
        "authority": "authorizes",
        "label": "Clamp proposal to catalog and policy",
        "status": "corrected" if clamped else ("defaulted" if changes else "accepted"),
        "source": "recommendation_core",
        "changes": changes,
        "output": {
            "lane": decision.get("lane"),
            "node_handle": decision.get("node_handle"),
            "requirements": decision.get("requirements") or {},
            "use_cases": decision.get("use_cases") or [],
            "brand_filter": decision.get("brand_filter"),
            "exclude_brand": decision.get("exclude_brand"),
            "quantity": decision.get("quantity"),
            "budget_scope": decision.get("budget_scope"),
        },
    }]

    for index, stage in enumerate(stages):
        name = str(stage.get("stage") or f"stage-{index}")
        if name == "route+intent":
            continue
        steps.append({
            "id": f"stage-{index}",
            "kind": _stage_kind(name),
            "authority": "executes" if str(stage.get("status") or "ok") == "ok" else "observes",
            "label": name.replace("_", " ").replace(":", ": "),
            "status": stage.get("status") or "ok",
            "source": "recommendation_core",
            "latency_ms": stage.get("latency_ms"),
            "retrieval_count": stage.get("retrieval_count") or 0,
            "won_message": bool(stage.get("won_message")),
        })

    gates = dict((getattr(core, "extras", {}) or {}).get("gates") or {})
    if gates:
        steps.append({
            "id": "commerce-policy-gate",
            "kind": "gate",
            "authority": "authorizes",
            "label": "Commerce policy gate",
            "status": "accepted" if gates.get("policy_route") == "allow" else "blocked",
            "source": gates.get("source") or "recommendation_core",
            "output": gates,
        })
    steps.append({
        "id": "buyer-response",
        "kind": "stage",
        "authority": "presents",
        "label": "Present authorized recommendation",
        "status": "degraded" if getattr(core, "degraded", False) else "completed",
        "source": "recommendation_core",
        "output": {"lane": getattr(core, "lane", None),
                   "product_count": len(getattr(core, "products", []) or []),
                   "clarification_count": len(getattr(core, "clarify", []) or [])},
    })
    return steps
