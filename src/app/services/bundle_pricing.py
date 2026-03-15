from __future__ import annotations

from typing import Any, Dict, Iterable

from src.app.policy.gate import evaluate_policy_gate
from src.app.services.product_taxonomy import count_items, infer_product_family, is_accessory_family


def evaluate_bundle_savings(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [dict(item) for item in (items or []) if isinstance(item, dict)]
    if not rows:
        return {
            "status": "empty",
            "eligible": False,
            "item_count": 0,
            "subtotal_cents": 0,
            "laptop_subtotal_cents": 0,
            "accessories_subtotal_cents": 0,
            "applied_discount_percent": 0,
            "discount_cents": 0,
            "final_total_cents": 0,
            "estimated_final_total_cents": 0,
            "message": "Add a laptop and an accessory to unlock bundle pricing.",
        }

    subtotal_cents = 0
    laptop_subtotal_cents = 0
    accessories_subtotal_cents = 0
    item_count = count_items(rows)
    distinct_count = len(rows)

    for item in rows:
        qty = max(1, int(item.get("quantity") or 1))
        price_cents = max(0, int(item.get("price_cents") or 0))
        line_total = qty * price_cents
        family = infer_product_family(
            sku=item.get("sku"),
            name=item.get("name"),
            specs=item.get("specs") if isinstance(item.get("specs"), dict) else {},
        )
        subtotal_cents += line_total
        if family == "LAP":
            laptop_subtotal_cents += line_total
        elif is_accessory_family(family):
            accessories_subtotal_cents += line_total

    has_bundle_mix = laptop_subtotal_cents > 0 and accessories_subtotal_cents > 0
    tier_15_threshold = 150_000
    tier_20_threshold = 200_000
    next_threshold_cents = tier_15_threshold
    requested_discount_pct = 0.0
    status = "progress"
    badge = None

    if has_bundle_mix and distinct_count >= 2 and subtotal_cents >= tier_20_threshold:
        requested_discount_pct = 0.20
        next_threshold_cents = tier_20_threshold
        status = "pending_review"
        badge = "Pending approval"
    elif has_bundle_mix and distinct_count >= 2 and subtotal_cents >= tier_15_threshold:
        requested_discount_pct = 0.15
        next_threshold_cents = tier_20_threshold
        status = "applied"
        badge = "Bundle applied"
    else:
        next_threshold_cents = tier_15_threshold if subtotal_cents < tier_15_threshold else tier_20_threshold

    discount_cents = int(round(laptop_subtotal_cents * requested_discount_pct))
    estimated_final_total_cents = max(0, subtotal_cents - discount_cents)

    gate = evaluate_policy_gate(
        {
            "tool": "bundle.offer",
            "request_type": "bundle_discount",
            "params": {
                "discount_percent": requested_discount_pct,
                "subtotal_cents": subtotal_cents,
                "laptop_subtotal_cents": laptop_subtotal_cents,
            },
        }
    )
    approval_required = bool(gate.approval_required)
    if requested_discount_pct <= 0.0:
        approval_required = False
    if approval_required and requested_discount_pct > 0.0:
        status = "pending_review"
        badge = "Pending approval"

    applied_discount_cents = 0 if approval_required else discount_cents
    final_total_cents = max(0, subtotal_cents - applied_discount_cents)
    amount_to_next_cents = max(0, next_threshold_cents - subtotal_cents)

    if requested_discount_pct <= 0.0:
        if not has_bundle_mix:
            message = "Add a laptop and a compatible accessory to unlock bundle pricing."
        else:
            message = f"Spend ${amount_to_next_cents / 100:,.0f} more to unlock 15% off your laptop."
    elif approval_required:
        message = "20% laptop bundle discount is available, but it requires review before checkout."
    elif requested_discount_pct >= 0.15 and subtotal_cents < tier_20_threshold:
        message = f"15% off your laptop is active. Spend ${amount_to_next_cents / 100:,.0f} more to unlock the 20% review tier."
    else:
        message = "Bundle savings are active on the laptop line item."

    return {
        "status": status,
        "eligible": has_bundle_mix and distinct_count >= 2,
        "item_count": item_count,
        "distinct_item_count": distinct_count,
        "subtotal_cents": subtotal_cents,
        "laptop_subtotal_cents": laptop_subtotal_cents,
        "accessories_subtotal_cents": accessories_subtotal_cents,
        "applied_discount_percent": 0.0 if approval_required else requested_discount_pct,
        "requested_discount_percent": requested_discount_pct,
        "discount_cents": discount_cents,
        "applied_discount_cents": applied_discount_cents,
        "final_total_cents": final_total_cents,
        "estimated_final_total_cents": estimated_final_total_cents,
        "next_threshold_cents": next_threshold_cents,
        "amount_to_next_cents": amount_to_next_cents,
        "approval_required": approval_required,
        "approval_badge": badge,
        "policy_decision": gate.decision,
        "policy_reasons": list(gate.reasons or []),
        "message": message,
    }
