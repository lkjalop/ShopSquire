"""Read-only inventory explanation over already-authorized product cards."""
from __future__ import annotations

from typing import Any, Dict, Sequence


def inventory_summary(products: Sequence[Any], *, tenant_id: str) -> Dict[str, Any]:
    if not products:
        return {
            "tenant_id": tenant_id, "source": "catalog_read_model",
            "answered": False, "action_executed": False,
            "message": (
                "I could not match that stock question to an active catalog item. "
                "Name the product or model and I will check it."
            ),
        }
    lines = []
    answered = False
    for product in list(products)[:3]:
        stock = getattr(product, "stock", None)
        label = getattr(product, "title", None) or getattr(product, "sku", None)
        if stock is None:
            lines.append(f"{label}: stock is not currently verified")
        elif stock > 0:
            answered = True
            lines.append(f"{label}: {stock} available")
        else:
            answered = True
            lines.append(f"{label}: currently out of stock")
    return {
        "tenant_id": tenant_id, "source": "catalog_read_model",
        "answered": answered, "action_executed": False,
        "message": "Current catalog availability: " + "; ".join(lines) + ".",
    }
