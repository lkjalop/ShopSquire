"""Visual similarity search API router.

Exposes ``POST /api/v1/visual-search`` for nearest-neighbour product
lookup using CLIP embeddings + FAISS.  All ML deps are lazy-loaded
so this router registers safely even when they're absent.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import Any, Dict, List, Optional

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services import visual_search as vs

router = APIRouter(prefix="/api/v1/visual-search", tags=["visual-search"])


@router.get("/status")
async def visual_search_status() -> Dict[str, Any]:
    """Health-check: reports whether the CLIP+FAISS stack is loaded."""
    return {
        "available": vs.is_available(),
        "index_size": len(vs._product_map),
    }


@router.post("/query")
async def visual_search_query(
    image: Optional[UploadFile] = File(None),
    query_text: Optional[str] = Query(None),
    budget_min: Optional[float] = Query(None, ge=0),
    budget_max: Optional[float] = Query(None, ge=0),
    brand: Optional[str] = Query(None),
    k: int = Query(20, ge=1, le=100),
    _role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Search for visually similar products by image upload or text query."""
    if not vs.is_available():
        raise HTTPException(status_code=503, detail="Visual search is not available (CLIP/FAISS not loaded)")

    image_bytes: bytes | None = None
    if image is not None:
        image_bytes = await image.read()
        if len(image_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit")

    if not image_bytes and not query_text:
        raise HTTPException(status_code=422, detail="Provide either an image or query_text")

    results = vs.search(
        image_bytes=image_bytes,
        query_text=query_text,
        k=k,
        budget_max=budget_max,
        budget_min=budget_min,
        brand=brand,
    )
    return {"results": results, "count": len(results)}


@router.post("/reindex", dependencies=[Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))])
async def visual_search_reindex() -> Dict[str, Any]:
    """Re-build the FAISS index from the current product catalog (admin-only)."""
    import asyncio
    import json as _json
    from src.app.models.db import db_session
    from sqlalchemy import text as sql_text

    def _fetch_products():
        with db_session() as session:
            rows = session.execute(sql_text(
                "SELECT sku, name, brand, price_cents, specs FROM products LIMIT 50000"
            )).fetchall()
            items = []
            for r in rows:
                specs = {}
                if r[4]:
                    try:
                        specs = _json.loads(r[4]) if isinstance(r[4], str) else r[4]
                    except Exception:
                        pass
                items.append({
                    "sku": r[0],
                    "name": r[1],
                    "brand": r[2],
                    "price_cents": r[3],
                    "specs": specs,
                })
            return items

    try:
        products = await asyncio.to_thread(_fetch_products)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Catalog query failed: {exc}")

    n = vs.build_index(products)
    return {"indexed": n, "available": vs.is_available()}
