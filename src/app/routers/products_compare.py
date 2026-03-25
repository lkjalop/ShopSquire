from __future__ import annotations
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException, Depends

from src.app.routers.ui_storefront import _get_products
from src.app.repositories.catalog import CatalogRepository
from src.app.models.db import get_db
from src.app.services.search_events import log_search_event


router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/list")
def list_products() -> List[Dict]:
    """Return seeded product list for UI fallbacks and API consumers."""
    return _get_products()


@router.get("/{sku}")
def get_product_detail(sku: str, db=Depends(get_db)) -> Dict:
    repo = CatalogRepository(session=db)
    product = repo.get_product_by_sku(sku)
    if product:
        stock = repo.get_stock_by_product_id(product.id)
        return {
            "sku": product.sku,
            "name": product.name,
            "price_cents": product.price_cents,
            "currency": product.currency,
            "image_url": product.image_url,
            "specs": product.specs,
            "active": product.active,
            "updated_at": product.updated_at,
            "stock": stock,
            "availability": "in_stock" if (stock or 0) > 0 else "out_of_stock",
        }
    # fallback to docs seed
    for p in _get_products():
        if str(p.get("sku")) == str(sku):
            return {
                "sku": p.get("sku"),
                "name": p.get("name"),
                "price_cents": int(p.get("price", 0)) * 100 if p.get("price") else None,
                "currency": "USD",
                "image_url": p.get("image_url"),
                "specs": p.get("features") or p.get("specs"),
                "active": True,
                "updated_at": None,
                "stock": None,
                "availability": "unknown",
            }
    raise HTTPException(status_code=404, detail="product_not_found")


@router.post("/compare")
def compare(payload: Dict) -> Dict:
    """Lightweight comparison matrix for MVP.

    Input: { product_ids: string[], user_query?: string }
    Output: { comparison_matrix, recommendation: { product_id, reasoning, decision_trace_id } }
    """
    ids = payload.get("product_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="product_ids_required")
    products = _get_products()
    by_sku = {p.get("sku"): p for p in products}
    selected = [by_sku.get(s) for s in ids if s in by_sku]
    selected = [p for p in selected if p]
    if not selected:
        raise HTTPException(status_code=404, detail="no_matching_products")

    keys = ["processor", "RAM", "storage", "display", "graphics", "battery"]
    def extract(p):
        feats = p.get("features") or []
        out = {}
        for k in keys:
            out[k] = next((f for f in feats if k.lower() in f.lower()), None)
        return out

    matrix = {p["sku"]: extract(p) for p in selected}
    # Naive recommendation: choose best value (lowest price) as placeholder
    best = min(selected, key=lambda x: x.get("price") or 0)
    reasoning = "Best value among selected based on price; refine with intent in production"
    rec = {"product_id": best.get("sku"), "reasoning": reasoning, "decision_trace_id": None}
    try:
        log_search_event(
            uid=str(payload.get("uid") or "anonymous"),
            query=str(payload.get("user_query") or "compare"),
            filters={"compare": True, "product_ids": ids},
            result_skus=[p.get("sku") for p in selected],
            view_mode="compare",
            trace_id=None,
            session_id=None,
        )
    except Exception:
        pass
    return {"comparison_matrix": matrix, "recommendation": rec}
