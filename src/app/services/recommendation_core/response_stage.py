"""Buyer-response executors extracted from the legacy core coordinator."""
from __future__ import annotations

from typing import Any

from src.app.services.recommendation_core.envelope import CoreResponse, MsgPriority, TurnEnvelope
from src.app.services.recommendation_core.turn_router import TurnDecision


def execute_off_catalog(_db: Any, _envelope: TurnEnvelope, decision: TurnDecision,
                        response: CoreResponse, _limit: int) -> None:
    label = decision.requested_category_label or decision.node_path or "that category"
    response.off_catalog = {
        "class": decision.node_handle, "label": label, "supplier_rfq_offer": True,
    }


def execute_clarify(_db: Any, _envelope: TurnEnvelope, _decision: TurnDecision,
                    response: CoreResponse, _limit: int) -> None:
    response.clarify.append({
        "question": "Could you tell me a bit more about what you need "
        "(budget, brand, or intended use)?",
        "reason": "low_routing_confidence",
    })


def execute_policy_answer(_db: Any, envelope: TurnEnvelope, _decision: TurnDecision,
                          response: CoreResponse, _limit: int) -> None:
    from src.app.services.policy_answer_service import policy_answer

    answer = policy_answer(envelope.query, tenant_id=envelope.tenant_id)
    response.extras.update({
        "policy_topic": answer["topic"], "policy_source": answer["source"],
        "policy_answered": answer["answered"], "action_executed": answer["action_executed"],
    })
    response.set_message(answer["message"], MsgPriority.LANE_BASE)


def execute_support_handoff(_db: Any, envelope: TurnEnvelope, _decision: TurnDecision,
                            response: CoreResponse, _limit: int) -> None:
    from src.app.services.support_handoff_advice import prepare_support_handoff

    advice = prepare_support_handoff(envelope.query, tenant_id=envelope.tenant_id)
    response.extras.update({key: value for key, value in advice.items() if key != "message"})
    response.set_message(advice["message"], MsgPriority.LANE_BASE)


def execute_procurement_handoff(_db: Any, envelope: TurnEnvelope, decision: TurnDecision,
                                response: CoreResponse, _limit: int) -> None:
    if decision.case_operation in ("status", "summary", "amendment"):
        session = envelope.session or {}
        accepted = session.get("accepted_constraints") if isinstance(
            session.get("accepted_constraints"), dict
        ) else {}
        sku, quantity = decision.exact_product_sku, decision.quantity
        case_id = (session.get("fulfillment_case_id") or session.get("procurement_case_id")
                   or session.get("sourcing_request_id"))
        anchor = " · ".join(value for value in (
            sku, f"{quantity} units" if quantity else None,
            f"case {case_id}" if case_id else None,
        ) if value)
        message = (
            "I kept the selected product and cart unchanged and recorded the "
            "delivery/payment requirements for the next confirmation check"
            if decision.case_operation == "amendment" else "Your procurement case is still active"
        )
        if anchor:
            message += f" for {anchor}"
        message += (
            ". No new product search or commercial execution was started."
            if decision.case_operation == "amendment"
            else ". I kept the existing product and case context; no new search or commercial "
            "action was started."
        )
        response.extras.update({
            "case_operation": decision.case_operation, "preserve_current_view": True,
            "state_changed": False,
            "case_anchor": {
                "sku": sku, "quantity": quantity, "case_id": case_id,
                "destination_token": accepted.get("destination_token"),
                "deadline": accepted.get("deadline"),
            },
        })
        response.set_message(message, MsgPriority.LANE_BASE)
        return
    from .procurement import build_procurement_advice

    advice = build_procurement_advice(envelope)
    response.extras.update({key: value for key, value in advice.items() if key != "message"})
    response.set_message(advice["message"], MsgPriority.LANE_BASE)


def execute_inventory_summary(_db: Any, envelope: TurnEnvelope, _decision: TurnDecision,
                              response: CoreResponse, _limit: int) -> None:
    from src.app.services.inventory_read_advice import inventory_summary

    advice = inventory_summary(response.products, tenant_id=envelope.tenant_id)
    response.extras.update({
        "inventory_source": advice["source"], "inventory_answered": advice["answered"],
        "action_executed": advice["action_executed"],
    })
    response.set_message(advice["message"], MsgPriority.LANE_BASE)


__all__ = [
    "execute_clarify", "execute_inventory_summary", "execute_off_catalog",
    "execute_policy_answer", "execute_procurement_handoff", "execute_support_handoff",
]
