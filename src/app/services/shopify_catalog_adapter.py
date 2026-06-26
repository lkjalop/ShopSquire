"""Shopify → canonical catalog adapter (platform edge) — maps Shopify product/inventory payloads into
ShopSquire's vertical-blind price_book_entry + inventory_level.

The adapter is the ONLY place that knows Shopify's shape (variants[].price as a decimal string, a shop
currency, inventory_level.available keyed by inventory_item_id). It translates to the canonical model
and upserts idempotently, so a re-sync of the same feed converges. Pure mappers + a thin ingest; the
HTTP fetch is a caller's concern (a webhook handler or the httpx research adapter), so this stays
deterministic + testable with a sample payload and no network.

Speaks Shopify field names (a platform, not a product vertical) — no product flavour, so it stays
agnostic of WHAT is sold.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.services import commerce_catalog as cc


def price_to_cents(price: Any) -> Optional[int]:
    """Shopify prices are decimal strings ('1199.00'). → integer cents. None when unparseable."""
    if price is None:
        return None
    try:
        return int(round(float(str(price).replace(",", "").strip()) * 100))
    except Exception:
        return None


def variants_to_prices(product: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A Shopify product → [{sku, list_cents}] for each variant carrying a sku + price."""
    out: List[Dict[str, Any]] = []
    for v in (product or {}).get("variants") or []:
        sku = str((v or {}).get("sku") or "").strip()
        cents = price_to_cents((v or {}).get("price"))
        if sku and cents is not None:
            out.append({"sku": sku, "list_cents": cents})
    return out


def inventory_item_to_sku(products: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build inventory_item_id → sku from the products' variants (so stock levels map to a sku)."""
    m: Dict[str, str] = {}
    for p in products or []:
        for v in (p or {}).get("variants") or []:
            iid = str((v or {}).get("inventory_item_id") or "").strip()
            sku = str((v or {}).get("sku") or "").strip()
            if iid and sku:
                m[iid] = sku
    return m


def ingest_shop_catalog(db, *, products: List[Dict[str, Any]],
                        inventory_levels: Optional[List[Dict[str, Any]]] = None,
                        tenant_id: str = cc.DEFAULT_TENANT, channel: str = "shopify",
                        currency: str = "AUD", commit: bool = True) -> Dict[str, int]:
    """Upsert canonical prices (from product variants) + stock (from inventory_levels, keyed back to sku
    via inventory_item_id). Idempotent. Returns {prices, inventory} counts. Best-effort; never raises."""
    if db is None:
        return {"prices": 0, "inventory": 0}
    n_p = n_i = 0
    try:
        for product in products or []:
            for row in variants_to_prices(product):
                if cc.upsert_price(db, sku=row["sku"], list_cents=row["list_cents"], channel=channel,
                                   currency=currency, source="shopify", tenant_id=tenant_id):
                    n_p += 1
        if inventory_levels:
            item_sku = inventory_item_to_sku(products or [])
            for lvl in inventory_levels:
                iid = str((lvl or {}).get("inventory_item_id") or "").strip()
                sku = item_sku.get(iid)
                if not sku:
                    continue
                loc = str((lvl or {}).get("location_id") or "default")
                if cc.upsert_inventory(db, sku=sku, on_hand=(lvl or {}).get("available"),
                                       location_id=loc, source="shopify", tenant_id=tenant_id):
                    n_i += 1
        if commit:
            db.commit()
    except Exception:
        return {"prices": n_p, "inventory": n_i}
    return {"prices": n_p, "inventory": n_i}
