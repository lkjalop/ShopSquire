"""Typed, deterministic Hippograph evidence emitted by commerce state transitions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from src.app.services.hippograph_journey_edges import TypedJourneyEdge


def _stamp(value: Any = None) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if value:
        return str(value)
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str, *parts: Any) -> str:
    material = "|".join(json.dumps(part, sort_keys=True, default=str) for part in parts)
    return f"{prefix}-" + hashlib.sha256(material.encode()).hexdigest()[:24]


def accepted_requirement_edges(
    *, tenant_id: str, case_id: str, proposal_id: str,
    claims: Iterable[dict[str, Any]], observed_at: Any = None,
) -> list[TypedJourneyEdge]:
    when = _stamp(observed_at)
    rows: list[TypedJourneyEdge] = []
    for claim in claims:
        claim_id = str(claim.get("claim_id") or "").strip()
        attribute = str(claim.get("attribute") or "").strip()
        if not claim_id or not attribute:
            continue
        requirement_id = f"requirement:{case_id}:{claim_id}"
        capability_id = "capability:" + _id(
            "predicate", attribute, claim.get("operator"), claim.get("value"),
            claim.get("unit"), claim.get("condition"),
        )
        authority = str(claim.get("authority_status") or "buyer_accepted")
        rows.append(TypedJourneyEdge(
            edge_id=_id("hje", tenant_id, proposal_id, claim_id), tenant_id=tenant_id,
            source_id=requirement_id, source_kind="requirement",
            target_id=capability_id, target_kind="capability",
            relation="requires_capability", signal_class="accepted",
            evidence_id=claim_id, observed_at=when, effective_at=when,
            source_authority=authority,
            attributes={
                "case_id": case_id, "proposal_id": proposal_id,
                "attribute": attribute, "operator": claim.get("operator"),
                "value": claim.get("value"), "unit": claim.get("unit"),
                "condition": claim.get("condition"),
            },
        ))
    return rows


def fulfillment_selection_edges(
    *, tenant_id: str, case_id: str, selection: Any, observed_at: Any = None,
) -> list[TypedJourneyEdge]:
    when = _stamp(observed_at)
    decision_id = f"buyer_decision:{selection.selection_id}"
    option_id = f"fulfillment_option:{selection.selection_id}:{selection.choice}"
    rows: list[TypedJourneyEdge] = []
    for offer in selection.offers:
        supplier_ref = str(offer.provenance.get("supplier_reference") or "unknown")
        offer_id = f"supplier_offer:{offer.offer_id}"
        configuration_id = f"configuration:{offer.offered_sku}"
        rows.extend([
            TypedJourneyEdge(
                edge_id=_id("hje", tenant_id, selection.selection_id, offer.offer_id, "configuration"),
                tenant_id=tenant_id, source_id=configuration_id, source_kind="configuration",
                target_id=offer_id, target_kind="supplier_offer", relation="has_supplier_offer",
                signal_class="attested", evidence_id=offer.offer_id,
                observed_at=when, effective_at=when, source_authority=supplier_ref,
                attributes={
                    "case_id": case_id, "quantity_available": offer.quantity_available,
                    "lead_time_days": offer.lead_time_days, "trust_status": offer.trust_status,
                    "response_status": offer.response_status,
                },
            ),
            TypedJourneyEdge(
                edge_id=_id("hje", tenant_id, selection.selection_id, offer.offer_id, "option"),
                tenant_id=tenant_id, source_id=offer_id, source_kind="supplier_offer",
                target_id=option_id, target_kind="fulfillment_option",
                relation="offers_fulfillment_option", signal_class="derived",
                evidence_id=f"commercial:{offer.offer_id}", observed_at=when, effective_at=when,
                source_authority="deterministic_commercial_reducer",
                attributes={"case_id": case_id, "choice": selection.choice},
            ),
        ])
    rows.append(TypedJourneyEdge(
        edge_id=_id("hje", tenant_id, selection.selection_id, "decision"), tenant_id=tenant_id,
        source_id=option_id, source_kind="fulfillment_option",
        target_id=decision_id, target_kind="buyer_decision", relation="selected_by_buyer",
        signal_class="accepted", evidence_id=selection.selection_id,
        observed_at=when, effective_at=when, source_authority="buyer_explicit_selection",
        attributes={
            "case_id": case_id, "choice": selection.choice,
            "requested_quantity": selection.requested_quantity,
        },
    ))
    return rows


def cart_outcome_edge(
    *, tenant_id: str, case_id: str, selection: Any, cart_result: dict[str, Any],
    observed_at: Any = None,
) -> TypedJourneyEdge:
    when = _stamp(observed_at)
    return TypedJourneyEdge(
        edge_id=_id("hje", tenant_id, selection.selection_id, "cart_outcome"),
        tenant_id=tenant_id,
        source_id=f"buyer_decision:{selection.selection_id}", source_kind="buyer_decision",
        target_id=f"order_outcome:{selection.cart_plan_id or selection.selection_id}",
        target_kind="order_outcome", relation="produced_order_outcome",
        signal_class="outcome", evidence_id=selection.cart_plan_id or selection.selection_id,
        observed_at=when, effective_at=when, source_authority="cart_mutation_service",
        attributes={"case_id": case_id, "cart_result": dict(cart_result)},
    )


__all__ = ["accepted_requirement_edges", "cart_outcome_edge", "fulfillment_selection_edges"]
