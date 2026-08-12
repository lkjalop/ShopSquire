"""Human-origin substitute proposals routed through the canonical cart plan service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.app.domain.cart_mutation import CartMutationPlan, CartOp
from src.app.models.db import db_session
from src.app.services.cart_mutation_service import propose_plan
from src.app.services.catalog_read_model import get_variant


@dataclass(frozen=True)
class HumanSubstituteRequest:
    buyer_uid: str
    source_sku: str
    replacement_sku: str
    quantity: int
    supplier_provenance: str
    delivery_consequence: str


def propose_human_substitute(
    *,
    tenant_id: str,
    incident_id: str,
    trace_id: str,
    request: HumanSubstituteRequest,
) -> dict[str, Any]:
    if not request.buyer_uid.strip():
        raise ValueError("buyer_uid_required")
    if not request.source_sku.strip() or not request.replacement_sku.strip():
        raise ValueError("source_and_replacement_sku_required")
    if request.source_sku == request.replacement_sku:
        raise ValueError("replacement_must_differ")
    if request.quantity < 1 or request.quantity > 500:
        raise ValueError("quantity_out_of_range")
    if not request.supplier_provenance.strip() or not request.delivery_consequence.strip():
        raise ValueError("provenance_and_delivery_required")

    from src.app.routers.cart import _load_cart_row

    with db_session() as db:
        _, cart_items, _ = _load_cart_row(db, request.buyer_uid, tenant_id=tenant_id)
        source_line = next((item for item in cart_items if str(item.get("sku") or "") == request.source_sku), None)
        if source_line is None:
            raise ValueError("source_sku_not_in_cart")
        replacement = get_variant(db, request.replacement_sku, tenant_id=tenant_id)
        if replacement is None or not replacement.active or replacement.price_cents is None:
            raise ValueError("replacement_not_available")
        replacement_name = str(replacement.name or request.replacement_sku)
        unit_price_cents = int(replacement.price_cents)

    plan = CartMutationPlan(
        ops=(CartOp(
            action="replace_item",
            target_skus=(request.source_sku,),
            quantity=request.quantity,
            replacement_sku=request.replacement_sku,
            replacement_name=replacement_name,
            unit_price_cents=unit_price_cents,
            previous_quantity=int(source_line.get("quantity") or 0),
            allow_sourcing=True,
        ),),
        confidence=1.0,
        source="authenticated_human_proposal",
    )
    proposed = propose_plan(
        tenant_id=tenant_id,
        uid=request.buyer_uid,
        plan=plan,
        cart_items=cart_items,
        query=f"human substitute proposal for incident {incident_id}",
        trace_id=trace_id,
    )
    return {
        **proposed,
        "plan": plan.as_dict(),
        "buyer_uid": request.buyer_uid,
        "buyer_identity_binding": "staff_asserted_compatibility",
        "supplier_provenance": request.supplier_provenance,
        "delivery_consequence": request.delivery_consequence,
        "commercial_authority": "none",
        "buyer_confirmation_required": True,
    }
