"""Magento → canonical catalog adapter (platform edge) — proves the integration seam is platform-blind.

Same canonical destination as the Shopify adapter (commerce_catalog + catalog_entities), different source
shape: Magento products carry `sku` + numeric `price` and stock under
`extension_attributes.stock_item.qty` (no inventory_item_id indirection — the sku IS the key). Pure
mappers + an idempotent ingest; no network. A third platform needs only another small module like this —
core never changes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.services import catalog_entities as ce
from src.app.services import commerce_catalog as cc

PLATFORM = "magento"


def price_to_cents(price: Any) -> Optional[int]:
    """Magento prices are numbers/numeric strings (1199 / '1199.00'). → integer cents."""
    if price is None:
        return None
    try:
        return int(round(float(str(price).replace(",", "").strip()) * 100))
    except Exception:
        return None


def stock_qty(product: Dict[str, Any]) -> Optional[int]:
    """on-hand from extension_attributes.stock_item.qty (Magento's stock shape)."""
    si = ((product or {}).get("extension_attributes") or {}).get("stock_item") or {}
    try:
        return int(si.get("qty")) if si.get("qty") is not None else None
    except Exception:
        return None


def ingest_catalog(db, *, products: List[Dict[str, Any]], tenant_id: str = cc.DEFAULT_TENANT,
                   channel: str = "magento", currency: str = "AUD", commit: bool = True) -> Dict[str, int]:
    """Upsert canonical prices + stock from Magento products. Idempotent. Best-effort; never raises."""
    if db is None:
        return {"prices": 0, "inventory": 0}
    n_p = n_i = 0
    try:
        for p in products or []:
            sku = str((p or {}).get("sku") or "").strip()
            if not sku:
                continue
            ce.upsert_variant(db, sku=sku, tenant_id=tenant_id)
            ce.upsert_external_ref(db, platform=PLATFORM, entity_type="product", external_id=sku,
                                   entity_id=sku, tenant_id=tenant_id)
            cents = price_to_cents((p or {}).get("price"))
            if cents is not None and cc.upsert_price(db, sku=sku, list_cents=cents, channel=channel,
                                                     currency=currency, source="magento", tenant_id=tenant_id):
                n_p += 1
            qty = stock_qty(p)
            if qty is not None and cc.upsert_inventory(db, sku=sku, on_hand=qty, source="magento",
                                                       tenant_id=tenant_id):
                n_i += 1
        if commit:
            db.commit()
    except Exception:
        return {"prices": n_p, "inventory": n_i}
    return {"prices": n_p, "inventory": n_i}
