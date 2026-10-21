"""Restore committed, scoped cases and project facts without granting authority."""
from sqlalchemy import text
from typing import Any


def restore_case_id(db, *, tenant_id, uid, session_epoch, subject_ref):
    if not all((tenant_id, uid, session_epoch, subject_ref)):
        return None
    rows = db.execute(text("""
        SELECT a.case_id, MAX(a.created_at) AS last_turn
        FROM conversation_case_amendment a
        JOIN conversation_case_state s ON s.id=a.case_state_id
          AND s.tenant_id=a.tenant_id AND s.case_id=a.case_id
          AND s.session_epoch=a.session_epoch
        JOIN shopping_cases c ON c.case_id=s.case_id AND c.tenant_id=s.tenant_id
        WHERE s.tenant_id=:tenant_id AND s.session_epoch=:session_epoch
          AND s.subject_ref=:subject_ref AND c.uid=:uid
          AND a.dialogue_act='turn_transition' AND a.status='accepted'
        GROUP BY a.case_id ORDER BY last_turn DESC LIMIT 2
    """), dict(tenant_id=tenant_id, uid=uid, session_epoch=session_epoch,
               subject_ref=subject_ref)).all()
    if len(rows) > 1 and rows[0][1] == rows[1][1]:
        raise ValueError("ambiguous_case_restoration")
    return rows[0][0] if rows else None


def project_retained_facts(out):
    from pydantic import ValidationError, TypeAdapter
    from src.app.services.procurement_case_state import MoneyConstraint, DestinationAllocation, TemporalConstraint
    out.pop('retained_buyer_facts',None)
    state = out.get("procurement_case_state")
    if (not isinstance(state, dict) or not out.get("case_id")
            or state.get("case_id") != out.get("case_id")
            or state.get("revision") != out.get("case_revision")):
        return
    facts = {}
    quantity = state.get("requested_quantity")
    if type(quantity) is int and quantity > 0:
        out["requested_quantity"] = quantity
        out['confirmed_slots']={**(out.get('confirmed_slots') or {}),'order_quantity':quantity}
        facts['requested_quantity'] = quantity
    for key, schema in (('budget',MoneyConstraint),('destinations',list[DestinationAllocation]),('temporal',TemporalConstraint)):
        if state.get(key):
            try:
                validated=TypeAdapter(schema).validate_python(state[key],strict=True)
                if key=='destinations' and (type(quantity) is not int or sum(r.quantity for r in validated)!=quantity):
                    continue
                facts[key]=TypeAdapter(schema).dump_python(validated,mode='json')
            except ValidationError:
                continue
    if facts:
        out['retained_buyer_facts']=facts


def retained_facts_message(facts):
    """Present committed buyer facts, including unresolved fields as unresolved."""
    parts=[]
    if facts.get('requested_quantity'):
        parts.append(f"{facts['requested_quantity']} units")
    budget=facts.get('budget')
    if budget:
        scope={'per_unit':'per unit','total':'total','unknown':'(budget scope unresolved)'}[budget['scope']]
        parts.append(f"budget {budget['currency']} {budget['amount_minor']/100:.2f} {scope}")
    if facts.get('destinations'):
        parts.append('delivery allocations: '+', '.join(f"{r['quantity']} to {r['location_ref']}" for r in facts['destinations']))
    temporal=facts.get('temporal')
    if temporal and temporal.get('original_expression'):
        parts.append(f"requested deadline: {temporal['original_expression']} ({temporal['resolution_status']})")
    return 'Your retained request: '+ '; '.join(parts)+'.' if parts else ''


def project_budget_question(out):
    """Preserve the shared commercial obligation even when model fit is blocked."""
    from src.app.services.recommendation_core.gates import material_pre_retrieval_clarify
    slots = out.get("confirmed_slots") or {}
    quantity = out.get("requested_quantity")
    question = material_pre_retrieval_clarify(
        quantity=quantity if type(quantity) is int else None,
        budget_known=slots.get("budget_max") is not None,
        budget_scope=slots.get("budget_scope") or "unknown",
    )
    if question:
        out["next_questions"] = [question] + [
            item for item in out.get("next_questions") or []
            if item.get("id") != question["id"]
        ]


def turn_shared_constraints(fresh_turn_confirmed_slots,response_confirmed_slots,out):
    shared_constraints: dict[str, Any] = {}
    if fresh_turn_confirmed_slots.get('destination'):
        shared_constraints['destination']=fresh_turn_confirmed_slots['destination']
    if fresh_turn_confirmed_slots.get('deadline'):
        shared_constraints['deadline']=fresh_turn_confirmed_slots['deadline']
    if out.get("requested_quantity") is not None:
        shared_constraints["requested_quantity"] = out.get("requested_quantity")
    budget_minor = response_confirmed_slots.get("total_budget_cents")
    if budget_minor is None and response_confirmed_slots.get("budget_max") is not None:
        budget_minor = int(response_confirmed_slots["budget_max"]) * 100
    if budget_minor is not None:
        shared_constraints["budget"] = {
            "amount_minor": int(budget_minor),
            "currency": str(
                response_confirmed_slots.get("currency")
                or out.get("currency") or "AUD"
            )[:3].upper(),
            "scope": str(
                response_confirmed_slots.get("budget_scope") or "unknown"
            ),
        }
    return shared_constraints


def partition_requirement_claims(buyer_requirement_claims,semantic_catalog_blocked,additive_workload_receipt):
    accepted_requirements: list[dict[str, Any]] = []
    rejected_requirements: list[dict[str, Any]] = []
    unresolved_requirements: list[dict[str, Any]] = []
    for claim in buyer_requirement_claims:
        if not isinstance(claim, dict):
            continue
        status = str(
            claim.get("status") or claim.get("authority_status")
            or claim.get("authority") or ""
        ).lower()
        if status in {
            "accepted", "verified", "approved", "verified_official",
            "case_origin_critic_accepted",
        }:
            accepted_requirements.append(dict(claim))
        elif status in {"rejected", "blocked", "invalid"}:
            rejected_requirements.append(dict(claim))
        else:
            unresolved_requirements.append(dict(claim))
    no_requirements = not (
        accepted_requirements or rejected_requirements or unresolved_requirements
    )
    if no_requirements and (semantic_catalog_blocked or additive_workload_receipt):
        unresolved_requirements.append({"reason": "material_requirements_unresolved"})
    return accepted_requirements,rejected_requirements,unresolved_requirements
