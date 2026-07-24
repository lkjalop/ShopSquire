"""Evidence-bounded newsletter/catalogue drafts.

This module selects products and renders editable copy. It never publishes,
sends, schedules, or changes a product price.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable


def build_newsletter_draft(
    projections: Iterable[Dict[str, Any]], *, max_products: int = 3
) -> Dict[str, Any]:
    qualified = []
    for item in projections or []:
        sku = str(item.get("sku") or "").strip()
        discount = (item.get("action_proposals") or {}).get("discount") or {}
        if not sku or not discount.get("eligible"):
            continue
        qualified.append(item)
    qualified.sort(key=lambda item: (
        -float(((item.get("projection") or {}).get("dsi_days") or 0.0)),
        str(item.get("sku") or ""),
    ))
    selected = qualified[:max(0, min(10, int(max_products)))]
    blurbs: Dict[str, str] = {}
    deals = []
    for item in selected:
        sku = str(item["sku"])
        name = str(item.get("name") or sku).strip()
        discount = (item.get("action_proposals") or {}).get("discount") or {}
        pct = round(float(discount.get("recommended_discount_pct") or 0.0), 4)
        blurbs[sku] = (
            f"{name} is included in this operator-selected catalogue draft. "
            "Review product claims, availability, and offer terms before publishing."
        )
        if pct > 0:
            deals.append({"sku": sku, "discount_pct": pct})
    return {
        "draft_id": str(uuid.uuid4()),
        "featured_skus": [str(item["sku"]) for item in selected],
        "blurbs": blurbs,
        "deals": deals,
        "status": "draft" if selected else "insufficient_evidence",
        "send_gate": "human",
        "sent": False,
        "copy_mode": "grounded_template",
        "selection_basis": "validated_surplus_discount_proposal",
    }
