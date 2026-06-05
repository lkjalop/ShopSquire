from __future__ import annotations

"""Candidate retrieval service (Sprint R3 extraction).

Responsible for fetching and merging product candidates from all sources:
- DB keyword/filter search
- Vector/semantic search (pgvector / FAISS)
- Inventory filter (stock gate)
- RRF (Reciprocal Rank Fusion) merge

This module is designed to be called via asyncio.gather() in the scatter-gather
architecture (Sprint R5). All public functions are async-ready.

Usage (Sprint R5 scatter-gather pattern):
    db_hits, vec_hits, inv_stock = await asyncio.gather(
        CandidateRetriever.from_db(query, filters),
        CandidateRetriever.from_vector(query),
        CandidateRetriever.batch_stock(candidate_skus),
    )
    candidates = CandidateRetriever.merge_rrf(db_hits, vec_hits)
    candidates = CandidateRetriever.apply_inventory_filter(candidates, inv_stock)
"""

import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.candidate_retriever")


# ── RRF (Reciprocal Rank Fusion) ──────────────────────────────────────────────

def merge_rrf(
    *ranked_lists: List[Dict[str, Any]],
    k: int = 60,
    top_n: int = 20,
) -> List[Dict[str, Any]]:
    """Merge multiple ranked candidate lists using Reciprocal Rank Fusion.

    RRF score = Σ 1/(k + rank_i) across all lists where the item appears.
    Items present in multiple lists get boosted; items only in one list are
    included but with lower combined scores.

    Args:
        *ranked_lists: Any number of lists of product dicts. Each dict must have
                       a "sku" key. Lists are treated as ranked (index 0 = rank 1).
        k: RRF k parameter (default 60, from original RRF paper).
        top_n: Maximum results to return.

    Returns:
        De-duplicated, RRF-fused candidate list sorted by descending RRF score.
        Each dict gains a "_rrf_score" key.
    """
    scores: Dict[str, float] = {}
    all_items: Dict[str, Dict[str, Any]] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked or [], start=1):
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            scores[sku] = scores.get(sku, 0.0) + 1.0 / (k + rank)
            if sku not in all_items:
                all_items[sku] = dict(item)

    for sku, score in scores.items():
        if sku in all_items:
            all_items[sku]["_rrf_score"] = round(score, 6)

    return sorted(all_items.values(), key=lambda x: x.get("_rrf_score", 0.0), reverse=True)[:top_n]


# ── DB Keyword/Filter Retrieval ───────────────────────────────────────────────

def from_db(
    query: str,
    *,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    brands: Optional[List[str]] = None,
    category: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Fetch products from the catalog DB matching query text + filters.

    Parameterised SQL only — no string interpolation of user input.
    Returns a list of product dicts ranked by text relevance score.
    """
    try:
        conditions = ["COALESCE(p.active, 1) = 1"]
        params: Dict[str, Any] = {"lim": int(limit)}

        if budget_min is not None:
            conditions.append("p.price_cents >= :budget_min")
            params["budget_min"] = int(budget_min)
        if budget_max is not None:
            conditions.append("p.price_cents <= :budget_max")
            params["budget_max"] = int(budget_max)
        if brands:
            brand_placeholders = ", ".join(f":brand_{i}" for i in range(len(brands)))
            conditions.append(f"LOWER(p.brand) IN ({brand_placeholders})")
            for i, b in enumerate(brands):
                params[f"brand_{i}"] = str(b).lower()
        if category:
            conditions.append("(LOWER(p.category) LIKE :cat OR LOWER(p.name) LIKE :cat)")
            params["cat"] = f"%{str(category).lower()[:40]}%"

        # Keyword relevance: simple LIKE matching (pgvector handles semantic)
        if query:
            q_safe = str(query or "")[:100]
            conditions.append(
                "(LOWER(p.name) LIKE :qt OR LOWER(p.brand) LIKE :qt "
                "OR LOWER(COALESCE(p.specs::text, p.specs, '')) LIKE :qt)"
            )
            params["qt"] = f"%{q_safe.lower()}%"

        where_clause = " AND ".join(conditions)
        sql = (
            f"SELECT p.sku, p.name, p.brand, p.price_cents, p.image_url, p.specs "
            f"FROM products p WHERE {where_clause} LIMIT :lim"
        )
        with db_session() as db:
            rows = db.execute(_text(sql), params).fetchall()

        return [
            {
                "sku": str(r[0]),
                "name": str(r[1] or ""),
                "brand": str(r[2] or ""),
                "price_cents": int(r[3] or 0),
                "image_url": str(r[4] or ""),
                "specs": r[5] if isinstance(r[5], dict) else {},
                "_source": "db",
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("from_db failed: %s", exc)
        return []


# ── Vector/Semantic Retrieval ─────────────────────────────────────────────────

def from_vector(
    query: str,
    *,
    top_k: int = 20,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch semantically similar products using the visual search / embedding index.

    Falls back to an empty list if the vector index is unavailable.
    """
    try:
        from src.app.services.visual_search import search_by_text
        results = search_by_text(query, top_k=top_k)
        if not results:
            return []
        return [
            {
                "sku": str(r.get("sku") or ""),
                "name": str(r.get("name") or ""),
                "brand": str(r.get("brand") or ""),
                "price_cents": int(r.get("price_cents") or 0),
                "score": float(r.get("score") or 0.0),
                "_source": "vector",
            }
            for r in results
            if r.get("sku")
        ]
    except Exception as exc:
        logger.debug("from_vector failed: %s", exc)
        return []


# ── Inventory filter ──────────────────────────────────────────────────────────

def apply_inventory_filter(
    candidates: List[Dict[str, Any]],
    stock_map: Optional[Dict[str, int]] = None,
    *,
    hide_oos: bool = False,
) -> List[Dict[str, Any]]:
    """Annotate candidates with stock levels and optionally hide OOS items.

    When hide_oos=False (default): OOS items get a rank penalty of 0.5 and are
    moved to the end, but remain visible.
    When hide_oos=True: OOS items are excluded entirely.

    If stock_map is not provided, a batch DB lookup is performed.
    """
    if not candidates:
        return candidates

    if stock_map is None:
        try:
            from src.app.services.inventory_query_service import batch_stock_levels
            skus = [str(c.get("sku") or "") for c in candidates if c.get("sku")]
            stock_map = batch_stock_levels(skus) if skus else {}
        except Exception:
            stock_map = {}

    out = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        sku = str(c.get("sku") or "")
        stock = int((stock_map or {}).get(sku, 0))
        c = dict(c)
        c["stock_level"] = stock
        if stock == 0:
            if hide_oos:
                continue
            c["stock_status"] = "out_of_stock"
            c["_rank_penalty"] = float(c.get("_rank_penalty") or 0.0) + 0.5
        elif stock <= 3:
            c["stock_status"] = "very_low_stock"
            c["stock_urgency"] = f"Only {stock} left in stock"
        elif stock <= 10:
            c["stock_status"] = "low_stock"
            c["stock_urgency"] = f"{stock} units remaining"
        else:
            c["stock_status"] = "in_stock"
        out.append(c)

    # Sort: OOS items last
    return sorted(out, key=lambda r: float(r.get("_rank_penalty") or 0.0))


# ── Full retrieval pipeline (convenience wrapper for Sprint R5) ───────────────

def retrieve_and_merge(
    query: str,
    *,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    brands: Optional[List[str]] = None,
    category: Optional[str] = None,
    top_n: int = 12,
    hide_oos: bool = False,
) -> List[Dict[str, Any]]:
    """Single-call retrieval: DB + vector → RRF merge → inventory filter.

    This is the synchronous wrapper for the full pipeline. In Sprint R5, this
    will be replaced by the async scatter-gather version using asyncio.gather().
    """
    db_hits = from_db(query, budget_min=budget_min, budget_max=budget_max, brands=brands, category=category)
    vec_hits = from_vector(query, top_k=top_n)
    merged = merge_rrf(db_hits, vec_hits, top_n=top_n * 2)
    return apply_inventory_filter(merged, hide_oos=hide_oos)[:top_n]
