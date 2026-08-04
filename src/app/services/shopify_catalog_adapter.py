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

from src.app.services import catalog_entities as ce
from src.app.services import commerce_catalog as cc

PLATFORM = "shopify"


def price_to_cents(price: Any) -> Optional[int]:
    """Shopify prices are decimal strings ('1199.00'). → integer cents. None when unparseable."""
    if price is None:
        return None
    try:
        return int(round(float(str(price).replace(",", "").strip()) * 100))
    except Exception:
        return None


def variants_to_prices(product: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A Shopify product → [{sku, list_cents, sale_cents}] per variant carrying a sku + price.
    Shopify semantics: `price` is what the buyer pays NOW; `compare_at_price` is the original.
    So compare_at present-and-higher → list=compare_at, sale=price; else list=price, no sale."""
    out: List[Dict[str, Any]] = []
    for v in (product or {}).get("variants") or []:
        sku = str((v or {}).get("sku") or "").strip()
        cents = price_to_cents((v or {}).get("price"))
        if not sku or cents is None:
            continue
        compare_at = price_to_cents((v or {}).get("compare_at_price"))
        if compare_at is not None and compare_at > cents:
            out.append({"sku": sku, "list_cents": compare_at, "sale_cents": cents})
        else:
            out.append({"sku": sku, "list_cents": cents, "sale_cents": None})
    return out


def product_attributes(product: Dict[str, Any]) -> Dict[str, Any]:
    """The T2 widening (2026-07-11): everything classification + retrieval need that the old
    adapter dropped — product_type, vendor, tags, options (the VARIANT AXES), handle, image,
    a description snippet, status. All into attributes_json per the flavour-in-data rule."""
    p = product or {}
    tags = p.get("tags")
    if isinstance(tags, str):  # REST API returns a comma-joined string; GraphQL a list
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    body = str(p.get("body_html") or "")
    images = p.get("images") or []
    image_url = str((images[0] or {}).get("src") or "") if images else ""
    return {
        "product_type": str(p.get("product_type") or ""),
        "vendor": str(p.get("vendor") or ""),
        "tags": [str(t) for t in (tags or [])][:50],
        "options": [str((o or {}).get("name") or "") for o in (p.get("options") or []) if (o or {}).get("name")],
        "handle": str(p.get("handle") or ""),
        "image_url": image_url,
        "description_snippet": body[:500],
        "shopify_status": str(p.get("status") or ""),
    }


def variant_attributes(variant: Dict[str, Any], product: Dict[str, Any]) -> Dict[str, Any]:
    """Variant-level truth: the option VALUES matched to the product's option NAMES (the
    category × variant axes — 'Color: Black', 'Size: 16in'), barcode/GTIN, weight."""
    v, p = variant or {}, product or {}
    names = [str((o or {}).get("name") or "") for o in (p.get("options") or [])]
    values = [v.get("option1"), v.get("option2"), v.get("option3")]
    options = {n: str(val) for n, val in zip(names, values) if n and val not in (None, "")}
    out: Dict[str, Any] = {"options": options,
                           "product_type": str(p.get("product_type") or "")}
    if v.get("barcode"):
        out["barcode"] = str(v.get("barcode"))
    grams = v.get("grams")
    if isinstance(grams, (int, float)):  # Shopify sends an integer; anything else isn't weight
        out["grams"] = int(grams)
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
            # record the product + variants in the canonical catalog + the platform mapping (the seam)
            pid = str((product or {}).get("id") or "")
            if pid:
                ce.upsert_product(db, product_id=f"shopify:{pid}", title=str((product or {}).get("title") or ""),
                                  brand=str((product or {}).get("vendor") or ""),
                                  category=str((product or {}).get("product_type") or ""),
                                  attributes=product_attributes(product), tenant_id=tenant_id)
                ce.upsert_external_ref(db, platform=PLATFORM, entity_type="product", external_id=pid,
                                       entity_id=f"shopify:{pid}", tenant_id=tenant_id)
            for v in (product or {}).get("variants") or []:
                sku = str((v or {}).get("sku") or "").strip()
                iid = str((v or {}).get("inventory_item_id") or "").strip()
                if sku:
                    ce.upsert_variant(db, sku=sku, product_id=f"shopify:{pid}" if pid else "",
                                      gtin=str((v or {}).get("barcode") or ""),
                                      attributes=variant_attributes(v, product), tenant_id=tenant_id)
                    if iid:  # so inventory_levels (keyed by inventory_item_id) resolve to a sku later
                        ce.upsert_external_ref(db, platform=PLATFORM, entity_type="inventory_item",
                                               external_id=iid, entity_id=sku, tenant_id=tenant_id)
            for row in variants_to_prices(product):
                if cc.upsert_price(db, sku=row["sku"], list_cents=row["list_cents"],
                                   sale_cents=row.get("sale_cents"), channel=channel,
                                   currency=currency, source="shopify", tenant_id=tenant_id):
                    n_p += 1
        if inventory_levels:
            item_sku = inventory_item_to_sku(products or [])   # in-memory fallback if not persisted
            for lvl in inventory_levels:
                iid = str((lvl or {}).get("inventory_item_id") or "").strip()
                sku = ce.resolve_external(db, platform=PLATFORM, entity_type="inventory_item",
                                          external_id=iid, tenant_id=tenant_id) or item_sku.get(iid)
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
