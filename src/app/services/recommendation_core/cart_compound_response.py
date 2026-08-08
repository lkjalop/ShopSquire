"""Project read-only obligations that accompany a guarded cart mutation.

The cart resolver owns SKU binding and arithmetic.  This module does not reinterpret the
mutation or authorize commerce; it carries already-accepted fit evidence and an explicit
delivery horizon into the response produced by the cart short-circuit.
"""
from __future__ import annotations

from typing import Any, Dict


def _proposed_quantity(plan: Any) -> int | None:
    for op in list(getattr(plan, "ops", ()) or ()):
        if str(getattr(op, "action", "")) != "set_quantity":
            continue
        value = getattr(op, "quantity", None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _selected_sku(envelope: Any, plan: Any) -> str:
    for op in list(getattr(plan, "ops", ()) or ()):
        targets = tuple(getattr(op, "target_skus", ()) or ())
        if len(targets) == 1:
            return str(targets[0])
    lines = [line for line in list(getattr(envelope, "cart", ()) or ()) if isinstance(line, dict)]
    return str(lines[0].get("sku") or "") if len(lines) == 1 else ""


def _fit_narration(explanation: Dict[str, Any]) -> str:
    workload = str(explanation.get("workload_summary") or "the retained workload").strip()
    name = str(explanation.get("name") or explanation.get("sku") or "The selected product").strip()
    checks = []
    for row in list(explanation.get("fit_ledger") or [])[:12]:
        if not isinstance(row, dict):
            continue
        label = str(row.get("attribute_label") or row.get("attribute") or "capability").strip()
        observed = str(row.get("observed_text") or "not recorded").strip()
        required = str(row.get("required_text") or "not recorded").strip()
        verdict = str(row.get("verdict") or "unknown").strip()
        checks.append(f"{label} {observed} {verdict} the accepted {required} target")
    if checks:
        message = f"Why {name} is a bounded candidate for {workload}: " + "; ".join(checks) + "."
    else:
        message = (
            f"I retained {name}, but no accepted capability ledger is available, so I cannot "
            f"claim it is qualified for {workload}."
        )
    unknowns = [str(value).strip() for value in explanation.get("material_unknowns") or []
                if str(value).strip()][:6]
    if unknowns:
        message += " Still unresolved: " + ", ".join(unknowns) + "."
    return message


def project_cart_compound_context(envelope: Any, plan: Any) -> Dict[str, Any]:
    """Return compound read-only projections and cart proposals, never actions."""
    quantity = _proposed_quantity(plan)
    selected_sku = _selected_sku(envelope, plan)
    session = getattr(envelope, "session", {}) or {}
    explanation = session.get("last_product_explanation")
    if not isinstance(explanation, dict) or str(explanation.get("sku") or "") != selected_sku:
        explanations = session.get("product_explanations")
        explanation = (
            explanations.get(selected_sku)
            if isinstance(explanations, dict) and isinstance(explanations.get(selected_sku), dict)
            else None
        )
    from src.app.services.query_classifier import is_followup_explain_query

    query = str(getattr(envelope, "query", "") or "")
    wants_explanation = (
        str(getattr(envelope, "intent_hint", "") or "").upper() == "EXPLAIN"
        or is_followup_explain_query(query)
    )

    try:
        from src.app.services.query_decomposer import decompose

        horizon = decompose(query).availability_horizon_days
    except Exception:
        horizon = None

    additions: Dict[str, Any] = {}
    message_parts = []
    if quantity is not None:
        additions["requested_quantity"] = quantity
    if wants_explanation and explanation is not None:
        additions["explanation"] = dict(explanation)
        message_parts.append(_fit_narration(explanation))
    elif wants_explanation:
        additions["explanation"] = {
            "sku": selected_sku or None,
            "status": "accepted_fit_evidence_unavailable",
            "fit_ledger": [],
            "commercial_authority_granted": False,
        }
        message_parts.append(
            "I can propose the quantity change, but the accepted workload-fit ledger for this "
            "exact SKU is unavailable, so I will not invent a capability explanation."
        )

    from src.app.services.conversation_case_state import decompose_case_obligations

    obligations = decompose_case_obligations(
        query,
        current_state={
            **session,
            "sku": selected_sku or session.get("selected_sku"),
            "quantity": quantity,
        },
        allow_unselected_quantity=True,
    )
    obligation_kinds = {str(row.get("kind") or "") for row in obligations}
    tenant_id = str(getattr(envelope, "tenant_id", None) or session.get("tenant_id") or "default")
    if "policy_question" in obligation_kinds:
        from src.app.services.policy_answer_service import policy_answer

        additions["policy_answer"] = policy_answer(query, tenant_id=tenant_id)
        message_parts.append(additions["policy_answer"]["message"])
    if "support_question" in obligation_kinds:
        from src.app.services.support_handoff_advice import prepare_support_handoff

        additions["support_handoff"] = prepare_support_handoff(query, tenant_id=tenant_id)
        message_parts.append(additions["support_handoff"]["message"])
    if "supplier_status" in obligation_kinds:
        from src.app.services.procurement_advice import supplier_status_projection

        additions["supplier_status"] = supplier_status_projection(
            session.get("last_sourcing_intent"),
            tenant_id=tenant_id,
            case_id=session.get("case_id") or session.get("fulfillment_case_id"),
            rfq_ref=session.get("rfq_ref"),
        )
        message_parts.append(additions["supplier_status"]["message"])

    if horizon is not None and quantity is not None:
        local = 0
        for line in list(getattr(envelope, "cart", ()) or ()):
            if isinstance(line, dict) and str(line.get("sku") or "") == selected_sku:
                try:
                    local = max(0, int(line.get("available_now") or 0))
                except (TypeError, ValueError):
                    local = 0
                break
        additions["delivery_feasibility"] = {
            "requested_quantity": quantity,
            "delivery_window_days": int(horizon),
            "quantity_confirmed_by_deadline": 0,
            "local_atp_without_arrival_proof": min(local, quantity),
            "unknown_quantity": quantity,
            "feasibility": "unknown",
            "reasons": [
                "date_qualified_local_arrival_missing",
                "date_qualified_transfer_eta_missing",
                "supplier_arrival_unconfirmed",
            ],
            "commercial_authority_granted": False,
        }
        message_parts.append(
            f"I cannot confirm {quantity} units within {int(horizon)} days from stock counts alone; "
            "dated local arrival, transfer ETA, and any supplier-confirmed arrival still need verification."
        )

    additions["case_obligations"] = [
        *([{"kind": "explanation", "status": "answered" if explanation else "degraded",
            "authorization_granted": False}] if wants_explanation else []),
        *([{"kind": "quantity_amendment", "status": "pending_confirmation",
            "proposed_value": quantity, "authorization_granted": False}] if quantity is not None else []),
        *([{"kind": "deadline", "status": "unknown", "proposed_value": int(horizon),
            "authorization_granted": False}] if horizon is not None else []),
    ]
    additions["case_obligations"].extend(
        {"kind": kind, "status": "answered", "authorization_granted": False}
        for kind in ("policy_question", "support_question", "supplier_status")
        if kind in obligation_kinds
    )
    additions["message_suffix"] = " ".join(message_parts).strip()
    return additions
