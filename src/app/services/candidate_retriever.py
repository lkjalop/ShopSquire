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
from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _text, bindparam

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.candidate_retriever")


def _budget_cents(value: Optional[int]) -> Optional[int]:
    """from_db callers pass shopper budgets in dollars; products store cents."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    # Preserve already-cent-like values from older internal callers.
    if abs(numeric) >= 100_000:
        return int(round(numeric))
    return int(round(numeric * 100.0))


def _obs(source: str, n: int, *, error: bool = False) -> None:
    """Make retrieval-source outcomes observable (these paths swallow errors and
    return [] — a silently-empty index should show up as a metric, not vanish)."""
    try:
        from src.app.observability.metrics import record_retrieval_source
        outcome = "error" if error else ("empty" if n == 0 else "hit")
        record_retrieval_source(source, outcome)
    except Exception:
        pass


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
        conditions = ["p.active IS NOT FALSE"]
        params: Dict[str, Any] = {"lim": int(limit)}

        if budget_min is not None:
            conditions.append("p.price_cents >= :budget_min")
            params["budget_min"] = _budget_cents(budget_min)
        if budget_max is not None:
            conditions.append("p.price_cents <= :budget_max")
            params["budget_max"] = _budget_cents(budget_max)
        if brands:
            brand_placeholders = ", ".join(f":brand_{i}" for i in range(len(brands)))
            conditions.append(f"LOWER(p.brand) IN ({brand_placeholders})")
            for i, b in enumerate(brands):
                params[f"brand_{i}"] = str(b).lower()
        if category:
            conditions.append("(LOWER(p.category) LIKE :cat OR LOWER(p.name) LIKE :cat)")
            params["cat"] = f"%{str(category).lower()[:40]}%"

        # Keyword relevance: TOKENISED LIKE matching (pgvector handles semantic).
        # Match ANY significant token, NOT the whole raw string. A multi-word query
        # (several terms plus a price range) matched as `LIKE %whole phrase%` hits no
        # product name → 0 results, which is why the scatter-gather DB leg returned empty
        # for realistic queries (V2 parity = 0). Tokenising restores recall.
        # CAST(... AS TEXT) is portable (Postgres + SQLite); `p.specs::text` was
        # Postgres-only and made from_db raise → empty results on SQLite.
        if query:
            import re as _re_tok
            q_low = str(query or "")[:120].lower()
            # conversational filler that should never drive catalog matching
            _STOP = {
                "show", "me", "the", "for", "with", "and", "you", "can", "get", "got",
                "please", "looking", "that", "this", "into", "what", "which", "about",
                "around", "are", "any", "some", "have", "want", "need", "give",
            }
            toks = [
                t for t in _re_tok.split(r"[^a-z0-9]+", q_low)
                if len(t) >= 3 and not t.isdigit() and t not in _STOP
            ][:6]
            if toks:
                ors = []
                for i, t in enumerate(toks):
                    params[f"qt_{i}"] = f"%{t}%"
                    ors.append(
                        f"(LOWER(p.name) LIKE :qt_{i} "
                        f"OR LOWER(COALESCE(p.brand,'')) LIKE :qt_{i} "
                        f"OR LOWER(COALESCE(CAST(p.specs AS TEXT), '')) LIKE :qt_{i})"
                    )
                conditions.append("(" + " OR ".join(ors) + ")")

        where_clause = " AND ".join(conditions)
        sql = (
            f"SELECT p.sku, p.name, p.brand, p.price_cents, p.image_url, p.specs "
            f"FROM products p WHERE {where_clause} LIMIT :lim"
        )
        with db_session() as db:
            rows = db.execute(_text(sql), params).fetchall()

        out = []
        for r in rows:
            raw_specs = r[5]
            if isinstance(raw_specs, dict):
                specs = raw_specs
            elif isinstance(raw_specs, str) and raw_specs.strip():
                try:
                    parsed = json.loads(raw_specs)
                    specs = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    specs = {}
            else:
                specs = {}
            out.append({
                "sku": str(r[0]),
                "name": str(r[1] or ""),
                "brand": str(r[2] or ""),
                "price_cents": int(r[3] or 0),
                "image_url": str(r[4] or ""),
                "specs": specs,
                "_source": "db",
            })
        _obs("db", len(out))
        return out
    except Exception as exc:
        logger.debug("from_db failed: %s", exc)
        _obs("db", 0, error=True)
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
            _obs("vector", 0)
            return []
        out = [
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
        _obs("vector", len(out))
        return out
    except Exception as exc:
        logger.debug("from_vector failed: %s", exc)
        _obs("vector", 0, error=True)
        return []


# ── Caption / multimodal-RAG retrieval (pgvector product_embeddings) ──────────

def from_caption(query: str, *, top_k: int = 20) -> List[Dict[str, Any]]:
    """Semantic retrieval over the `product_embeddings` pgvector index — the rich
    text embedding (name + specs + VLM visual caption). This is the multimodal-RAG
    source: it reuses the EXISTING production embedding table + HNSW index +
    `search_products_by_embedding`, not a new store. Empty on SQLite / cold index
    (fail-open). RRF-merged alongside DB-keyword and CLIP-visual."""
    try:
        from src.app.services.embeddings import VectorStoreEmbeddings
        from src.app.repositories.embeddings import search_products_by_embedding

        emb = VectorStoreEmbeddings().embed_text_vector(query or "")
        if not emb:
            _obs("caption", 0)
            return []
        with db_session() as db:
            hits = search_products_by_embedding(db, emb, top_k=top_k)
            if not hits:
                _obs("caption", 0)
                return []
            dist = {str(h.get("product_id")): float(h.get("distance") or 0.0) for h in hits if h.get("product_id") is not None}
            ids = list(dist.keys())
            if not ids:
                _obs("caption", 0)
                return []
            rows = db.execute(
                _text(
                    "SELECT id, sku, name, brand, price_cents, image_url, specs "
                    "FROM products WHERE CAST(id AS TEXT) IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": ids},
            ).fetchall()
        out = [
            {
                "sku": str(r[1] or ""),
                "name": str(r[2] or ""),
                "brand": str(r[3] or ""),
                "price_cents": int(r[4] or 0),
                "image_url": str(r[5] or ""),
                "specs": r[6] if isinstance(r[6], dict) else {},
                "score": round(1.0 - dist.get(str(r[0]), 1.0), 6),
                "_source": "caption",
            }
            for r in rows
            if str(r[1] or "")
        ]
        out.sort(key=lambda x: -float(x.get("score") or 0.0))
        _obs("caption", len(out))
        return out
    except Exception as exc:
        logger.debug("from_caption failed: %s", exc)
        _obs("caption", 0, error=True)
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

def retrieve_with_statuses(
    query: str,
    *,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    brands: Optional[List[str]] = None,
    category: Optional[str] = None,
    top_n: int = 12,
    hide_oos: bool = False,
):
    """Like retrieve_and_merge, but ALSO returns a typed per-source status map so a
    degraded answer can say which leg errored/was empty (1.2). Each leg is timed and
    classified full/empty/error; the merged candidates are identical to
    retrieve_and_merge. Returns (candidates, {source: SourceStatus})."""
    import time as _t
    from src.app.services.commerce_source_status import SourceStatus

    statuses: Dict[str, Any] = {}

    def _timed(name: str, fn):
        t0 = _t.perf_counter()
        try:
            hits = fn() or []
            statuses[name] = SourceStatus.from_hits(name, hits, int((_t.perf_counter() - t0) * 1000))
            return hits
        except Exception as exc:  # legs fail-open, but defend the wrapper too
            statuses[name] = SourceStatus.errored(name, str(exc), int((_t.perf_counter() - t0) * 1000))
            return []

    db_hits = _timed("catalog_db", lambda: from_db(
        query, budget_min=budget_min, budget_max=budget_max, brands=brands, category=category))
    vec_hits = _timed("clip_visual", lambda: from_vector(query, top_k=top_n))
    cap_hits = _timed("caption_rag", lambda: from_caption(query, top_k=top_n))
    merged = merge_rrf(db_hits, vec_hits, cap_hits, top_n=top_n * 2)
    merged = apply_inventory_filter(merged, hide_oos=hide_oos)[:top_n]
    return merged, statuses


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
    """Single-call retrieval: DB-keyword + CLIP-visual + caption-RAG → RRF merge →
    inventory filter.

    Three RRF sources: DB keyword/filter (`from_db`), CLIP visual similarity
    (`from_vector`), and multimodal caption-RAG over pgvector (`from_caption`).
    Each fails open to [], so the merge degrades gracefully if any index is cold.
    """
    db_hits = from_db(query, budget_min=budget_min, budget_max=budget_max, brands=brands, category=category)
    vec_hits = from_vector(query, top_k=top_n)
    cap_hits = from_caption(query, top_k=top_n)
    merged = merge_rrf(db_hits, vec_hits, cap_hits, top_n=top_n * 2)
    return apply_inventory_filter(merged, hide_oos=hide_oos)[:top_n]
