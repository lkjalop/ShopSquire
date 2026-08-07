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

    intent = dict((getattr(core, "extras", {}) or {}).get("intent") or {})
    title_requirements = dict(intent.get("title_requirements") or {})
    workload_evidence = dict(
        title_requirements.get("external_workload_evidence") or {}
    )
    workload_items = [
        dict(item) for item in (workload_evidence.get("items") or [])
        if isinstance(item, dict)
    ]
    if workload_items:
        resolved = sum(
            1 for item in workload_items if str(item.get("status") or "") == "resolved"
        )
        steps.append({
            "id": "workload-evidence",
            "kind": "connector",
            "authority": "supplies_evidence",
            "label": "Resolve named workload requirements",
            "status": "resolved" if resolved == len(workload_items) else "incomplete",
            "source": "workload_evidence_registry",
            "output": {
                "resolved": resolved,
                "requested": len(workload_items),
                "live_allowed": bool(workload_evidence.get("live_allowed")),
                "consent_recorded": bool(workload_evidence.get("consent_recorded")),
                "provider_coverage": [
                    {
                        "kind": item.get("kind"),
                        "requested_name": item.get("requested_name"),
                        "coverage": item.get("provider_coverage"),
                        "attempts": item.get("provider_attempts") or [],
                    }
                    for item in workload_items
                ],
                "items": workload_items,
            },
        })
        compiled = [
            dict(requirement)
            for item in workload_items
            for requirement in list(item.get("compiled_requirements") or [])
            if isinstance(requirement, dict)
        ]
        rejections = [
            dict(rejection)
            for item in workload_items
            for rejection in list(item.get("claim_rejections") or [])
            if isinstance(rejection, dict)
        ]
        steps.append({
            "id": "requirements-compiler",
            "kind": "gate",
            "authority": "compiles_constraints",
            "label": "Compile accepted evidence into capability predicates",
            "status": "accepted" if compiled and not rejections else (
                "partial" if compiled else "blocked"
            ),
            "source": "requirement_compiler",
            "output": {
                "compiled_requirements": compiled,
                "rejected_claims": rejections,
                "catalog_authority_granted": bool(compiled),
                "commercial_authority_granted": False,
            },
        })

    workload_authorization = dict(
        (getattr(core, "extras", {}) or {}).get("workload_authorization") or {}
    )
    if workload_authorization:
        steps.append({
            "id": "workload-authorization",
            "kind": "gate",
            "authority": "authorizes",
            "label": "Authorize workload-to-product fit",
            "status": workload_authorization.get("status") or "unknown",
            "source": "recommendation_core",
            "output": workload_authorization,
        })

    research_plan = dict(
        ((getattr(core, "extras", {}) or {}).get("plan") or {}).get("research_plan") or {}
    )
    if research_plan.get("evidence_needs") or research_plan.get("material_slots"):
        steps.append({
            "id": "buyer-research-consent",
            "kind": "buyer_input",
            "authority": "grants_research_scope",
            "label": "Record buyer research consent",
            "status": (
                "recorded"
                if research_plan.get("external_research_authorized")
                else "not_recorded"
            ),
            "source": "conversation_case_state",
            "output": {
                "external_research_authorized": bool(
                    research_plan.get("external_research_authorized")
                ),
                "commercial_authority_granted": False,
            },
        })
        steps.append({
            "id": "research-plan",
            "kind": "stage",
            "authority": "plans",
            "label": "Plan bounded evidence collection",
            "status": "authorized" if research_plan.get("external_research_authorized") else "consent_required",
            "source": "recommendation_core",
            "output": research_plan,
        })

    semantic_evidence = dict(
        (getattr(core, "extras", {}) or {}).get("semantic_evidence") or {}
    )
    if semantic_evidence:
        steps.append({
            "id": "semantic-evidence",
            "kind": "connector",
            "authority": "supplies_evidence",
            "label": "Gather concept and requirement evidence",
            "status": semantic_evidence.get("source_health") or "unknown",
            "source": "evidence_orchestrator",
            "latency_ms": semantic_evidence.get("ms"),
            "output": semantic_evidence,
        })

    semantic_resolution = dict(
        (getattr(core, "extras", {}) or {}).get("semantic_resolution") or {}
    )
    if semantic_resolution:
        steps.append({
            "id": "semantic-authorization",
            "kind": "gate",
            "authority": "authorizes",
            "label": "Authorize concept-to-catalog fit",
            "status": (
                "accepted"
                if semantic_resolution.get("catalog_authority") == "permitted"
                else "blocked"
            ),
            "source": "semantic_resolution",
            "output": semantic_resolution,
        })
        clarification = next(
            (
                dict(item)
                for item in list(getattr(core, "clarify", []) or [])
                if isinstance(item, dict)
                and item.get("selection_policy")
            ),
            None,
        )
        if clarification:
            steps.append({
                "id": "material-clarification",
                "kind": "gate",
                "authority": "requests_buyer_input",
                "label": "Select one material buyer clarification",
                "status": "awaiting_buyer",
                "source": "clarification_policy",
                "output": {
                    "question_id": clarification.get("id"),
                    "question": clarification.get("text"),
                    "missing_slots": list(clarification.get("missing_slots") or []),
                    "selection_policy": clarification.get("selection_policy"),
                    "decision_impacts": list(clarification.get("decision_impacts") or []),
                    "commercial_authority_granted": False,
                },
            })

    case_obligations = [
        dict(item) for item in list(
            (getattr(core, "extras", {}) or {}).get("case_obligations") or []
        ) if isinstance(item, dict)
    ]
    if case_obligations:
        case_context = dict(
            (getattr(core, "extras", {}) or {}).get("conversation_case_context") or {}
        )
        steps.append({
            "id": "commercial-case-reducer",
            "kind": "gate",
            "authority": "validates_commercial_state",
            "label": "Validate commercial amendments against case state",
            "status": (
                "blocked" if any(item.get("status") == "blocked" for item in case_obligations)
                else "pending_confirmation" if any(
                    item.get("status") == "pending_confirmation" for item in case_obligations
                ) else "accepted"
            ),
            "source": "conversation_case_state",
            "output": {
                **case_context,
                "obligations": case_obligations,
                "commercial_authority_granted": False,
            },
        })

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
