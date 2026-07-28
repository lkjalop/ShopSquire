from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException, Depends

from src.app.routers.ui_storefront import _get_products
from src.app.repositories.catalog import CatalogRepository
from src.app.models.db import get_db
from src.app.services.search_events import log_search_event
from src.app.platform.tenant_context import current_tenant_id
from src.app.services.product_lifecycle import (
    LifecyclePermissionDenied,
    filter_sellable_skus,
    require_lifecycle_permission,
)


router = APIRouter(prefix="/api/v1/products", tags=["products"])


def _sellable(db, products: List[Dict]) -> List[Dict]:
    tenant = current_tenant_id()
    try:
        allowed = filter_sellable_skus(
            db,
            tenant_id=tenant,
            skus=[str(row.get("sku") or "") for row in products],
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="lifecycle_policy_unavailable",
        ) from exc
    return [row for row in products if str(row.get("sku") or "") in allowed]


@router.get("/list")
def list_products(page: int = 1, per_page: int = 50, db=Depends(get_db)) -> Dict:
    """Return seeded product list with pagination metadata."""
    all_products = _sellable(db, _get_products())
    total = len(all_products)
    offset = (page - 1) * per_page
    page_products = all_products[offset : offset + per_page]
    return {
        "products": page_products,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/{sku}")
def get_product_detail(sku: str, db=Depends(get_db)) -> Dict:
    try:
        require_lifecycle_permission(
            db,
            tenant_id=current_tenant_id(),
            sku=sku,
            permission="selling",
        )
    except LifecyclePermissionDenied as exc:
        raise HTTPException(
            status_code=404,
            detail=f"product_not_sellable:{exc.state}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="lifecycle_policy_unavailable",
        ) from exc
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
def compare(payload: Dict, db=Depends(get_db)) -> Dict:
    """Lightweight comparison matrix for MVP.

    Input: { product_ids: string[], user_query?: string }
    Output: { comparison_matrix, recommendation: { product_id, reasoning, decision_trace_id } }
    """
    ids = payload.get("product_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="product_ids_required")
    products = _get_products()
    by_sku = {p.get("sku"): p for p in products}
    allowed = {
        row["sku"] for row in _sellable(
            db,
            [by_sku[s] for s in ids if s in by_sku],
        )
    }
    selected = [by_sku.get(s) for s in ids if s in allowed]
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
