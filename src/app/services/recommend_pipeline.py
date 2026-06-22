from __future__ import annotations

"""Scatter-gather recommendation pipeline (Sprint R5 foundation).

This module is the TARGET architecture for recommend.py refactoring.
It implements the parallel scatter-gather pattern described in the platform
architecture docs:

  Stage 1 (scatter — all parallel via asyncio.gather):
    - DB keyword/filter search
    - Vector/semantic search
    - Fraud scoring (Redis + rules)
    - Inventory batch check
    - CV analysis (only when image present)

  Stage 2 (gather + merge):
    - RRF merge of DB + vector hits
    - Apply fraud security gate
    - Apply inventory filter + OOS penalties
    - Apply CV labels to re-rank

  Stage 3 (conditional deepening — only for complexity_score >= 7):
    - UseCase specialist agent
    - Budget analyst agent
    - Merge deep signals

  Stage 4 (serial):
    - NQE evaluation (should we ask a question?)
    - LLM summarization
    - Response assembly

STATUS: WIRED IN SHADOW (not a dead scaffold). The route runs the V2 hybrid
candidates produced here and fuses/swaps them via
services/recommend_retriever_stage.run_retrieval_mode_stage() BEFORE ranking, so
V2 never bypasses the downstream rank/stock/budget/security guards. Default mode
is RECOMMEND_RETRIEVAL_MODE=shadow (measurement-only, NOT customer-affecting);
fusion/primary are gated on live parity proof (see recommend_retrieval_metrics).
The legacy monolith remains the authoritative path until parity promotes a mode.

Usage:
    result = await run_recommend_pipeline(payload, context)
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shopsquire.recommend_pipeline")

# ── Per-leg timeout budgets (silent-hang guard) ───────────────────────────────
# A hung scatter leg (slow vector DB / LLM caption / CV / fraud lookup) must NEVER
# block the whole scatter-gather. Each leg gets a hard budget; on timeout it logs,
# the gather(return_exceptions=True) captures the TimeoutError, and the leg falls back
# to its empty default — the rest of the results still return within the request budget.
_LEG_TIMEOUT_S = float(os.getenv("RECOMMEND_LEG_TIMEOUT_S", "8.0"))
_CV_TIMEOUT_S = float(os.getenv("RECOMMEND_CV_TIMEOUT_S", "12.0"))
_DEEP_TIMEOUT_S = float(os.getenv("RECOMMEND_DEEP_TIMEOUT_S", "10.0"))


async def _bounded(coro, budget_s: float, label: str, errors: Optional[Dict[str, str]] = None):
    """Run `coro` under a hard timeout. On timeout OR any leg failure, record the reason
    into `errors[label]` (so it surfaces in the trace, never only in logs) and re-raise so
    the caller's gather(return_exceptions=True) captures it and falls back to default.
    This is the single guard that turns an unbounded gather into a bounded, observable one."""
    try:
        return await asyncio.wait_for(coro, timeout=budget_s)
    except asyncio.TimeoutError:
        logger.warning("scatter leg timed out: %s (budget=%.1fs)", label, budget_s)
        if errors is not None:
            errors[label] = f"timeout>{budget_s}s"
        raise
    except Exception as exc:
        logger.warning("scatter leg failed: %s — %s", label, exc)
        if errors is not None:
            errors[label] = f"{type(exc).__name__}: {str(exc)[:120]}"
        raise


# ── Stage 1 scatter agents ────────────────────────────────────────────────────

async def _scatter_db(
    query: str,
    budget_min: Optional[int],
    budget_max: Optional[int],
    brands: Optional[List[str]],
    category: Optional[str],
) -> List[Dict[str, Any]]:
    """Async wrapper for DB keyword/filter retrieval. Exceptions propagate to _bounded,
    which records them in the leg-errors map and re-raises (gather falls back to []) — so a
    leg failure is observable in the trace instead of silently swallowed."""
    return await asyncio.to_thread(
        _sync_db_search, query, budget_min, budget_max, brands, category
    )


def _sync_db_search(query, budget_min, budget_max, brands, category) -> List[Dict[str, Any]]:
    from src.app.services.candidate_retriever import from_db
    return from_db(query, budget_min=budget_min, budget_max=budget_max, brands=brands, category=category)


async def _scatter_vector(query: str, top_k: int = 20) -> List[Dict[str, Any]]:
    """Async wrapper for vector/semantic search. Exceptions propagate to _bounded (recorded
    + re-raised); gather falls back to [] — failure is observable, not silent."""
    return await asyncio.to_thread(_sync_vector_search, query, top_k)


def _sync_vector_search(query: str, top_k: int) -> List[Dict[str, Any]]:
    from src.app.services.candidate_retriever import from_vector
    return from_vector(query, top_k=top_k)


async def _scatter_caption(query: str, top_k: int = 20) -> List[Dict[str, Any]]:
    """Async wrapper for multimodal caption-RAG (pgvector product_embeddings). Exceptions
    propagate to _bounded (recorded + re-raised); gather falls back to [] — observable, not silent."""
    return await asyncio.to_thread(_sync_caption_search, query, top_k)


def _sync_caption_search(query: str, top_k: int) -> List[Dict[str, Any]]:
    from src.app.services.candidate_retriever import from_caption
    return from_caption(query, top_k=top_k)


async def _scatter_fraud(uid: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Async wrapper for fraud scoring."""
    try:
        return await asyncio.to_thread(_sync_fraud_score, uid, context)
    except Exception as exc:
        logger.debug("scatter_fraud failed: %s", exc)
        return {"score": 0.0, "level": "low", "evidence": []}


def _sync_fraud_score(uid: str, context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from src.app.services.fraud_scorer import FraudScorer
        scorer = FraudScorer()
        return scorer.score(uid=uid, context=context)
    except Exception:
        return {"score": 0.0, "level": "low", "evidence": []}


async def _scatter_inventory(skus: List[str]) -> Dict[str, int]:
    """Batch inventory lookup (fast, single DB query)."""
    if not skus:
        return {}
    try:
        from src.app.services.inventory_query_service import batch_stock_levels
        return await asyncio.to_thread(batch_stock_levels, skus)
    except Exception as exc:
        logger.debug("scatter_inventory failed: %s", exc)
        return {}


async def _scatter_cv(image_bytes: bytes, query: str, trace_id: Optional[str]) -> Dict[str, Any]:
    """CV analysis — only called when image is present. Exceptions propagate to _bounded
    (recorded + re-raised); gather falls back to {} — observable, not silent."""
    from src.app.services.cv_tiered import TieredCVProvider
    from src.app.services.orchestrator import _run_async_safe
    cvp = TieredCVProvider()
    return await asyncio.to_thread(
        _run_async_safe,
        cvp.process(image_bytes, meta={"trace_id": trace_id, "query": query}),
    )


# ── Stage 2 gather ────────────────────────────────────────────────────────────

def _apply_fraud_gate(
    candidates: List[Dict[str, Any]],
    fraud_signals: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Exclude candidates that violate fraud policy."""
    fraud_score = float((fraud_signals or {}).get("score") or 0.0)
    if fraud_score >= 90:
        return []  # Full block — fraud score is extreme
    if fraud_score >= 70:
        # Soft block — limit to first 3 and flag
        return [{**c, "_fraud_flagged": True} for c in candidates[:3]]
    return candidates


# ── Stage 3 conditional deepening ────────────────────────────────────────────

async def _deep_usecase(
    candidates: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Use-case specialist: re-rank candidates based on use-case requirements."""
    use_case = str(context.get("use_case") or "").lower()
    if not use_case:
        return candidates
    # Simple heuristic deepening: boost candidates that mention the use case
    boosted = []
    for c in candidates:
        score = float(c.get("_rrf_score") or 0.0)
        name_lower = str(c.get("name") or "").lower()
        specs_lower = str(c.get("specs") or "").lower()
        if use_case in name_lower or use_case in specs_lower:
            score *= 1.25
        boosted.append({**c, "_rrf_score": round(score, 6)})
    return sorted(boosted, key=lambda x: x.get("_rrf_score") or 0.0, reverse=True)


async def _deep_budget(
    candidates: List[Dict[str, Any]],
    budget_max: Optional[int],
) -> List[Dict[str, Any]]:
    """Budget analyst: remove candidates above budget and annotate value scores."""
    if not budget_max:
        return candidates
    out = []
    for c in candidates:
        price = int(c.get("price_cents") or 0)
        if price > budget_max:
            continue
        value_score = max(0.0, 1.0 - (float(price) / float(budget_max)))
        out.append({**c, "_value_score": round(value_score, 3)})
    return sorted(out, key=lambda x: x.get("_rrf_score") or 0.0, reverse=True)


# ── Main pipeline entry point ─────────────────────────────────────────────────

async def run_recommend_pipeline(
    payload: Dict[str, Any],
    *,
    uid: str,
    query: str,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    brands: Optional[List[str]] = None,
    category: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    complexity_score: int = 0,
    trace_id: Optional[str] = None,
    top_n: int = 12,
) -> Dict[str, Any]:
    """Run the full scatter-gather recommendation pipeline.

    This is the Sprint R5 target entry point that replaces the monolithic
    recommend handler. Currently used only for testing — not yet wired into
    the main recommend route.

    Returns:
        {
            "candidates": [...],
            "fraud_signals": {...},
            "cv_signals": {...},
            "oos_fraction": float,
            "latency_ms": {...},
            "deepened": bool,
        }
    """
    t0 = time.perf_counter()
    timings: Dict[str, float] = {}
    # Per-leg failure map (label -> reason). Populated by _bounded on timeout/error and
    # surfaced in the return + trace so a degraded leg is visible during parity review,
    # not just buried in logs.
    leg_errors: Dict[str, str] = {}

    # ── Stage 1: Parallel scatter ─────────────────────────────────────────────
    # Three retrieval sources (db-keyword + CLIP-visual + caption-RAG) + fraud,
    # plus CV when an image is present. Index-safe unpacking so adding/removing a
    # leg can't silently misalign results.
    scatter_tasks = [
        _bounded(_scatter_db(query, budget_min, budget_max, brands, category), _LEG_TIMEOUT_S, "db", leg_errors),       # 0
        _bounded(_scatter_vector(query, top_k=top_n * 2), _LEG_TIMEOUT_S, "vector", leg_errors),                        # 1
        _bounded(_scatter_fraud(uid, payload), _LEG_TIMEOUT_S, "fraud", leg_errors),                                    # 2
        _bounded(_scatter_caption(query, top_k=top_n * 2), _LEG_TIMEOUT_S, "caption", leg_errors),                      # 3
    ]
    _leg_labels = ["db", "vector", "fraud", "caption"]
    cv_idx = None
    if image_bytes:
        cv_idx = len(scatter_tasks)
        scatter_tasks.append(_bounded(_scatter_cv(image_bytes, query, trace_id), _CV_TIMEOUT_S, "cv", leg_errors))
        _leg_labels.append("cv")

    scatter_results = await asyncio.gather(*scatter_tasks, return_exceptions=True)

    # Surface which legs timed out / errored (visible in trace; never silent).
    _timed_out = [lbl for lbl, r in zip(_leg_labels, scatter_results) if isinstance(r, asyncio.TimeoutError)]
    if _timed_out:
        timings["scatter_timeouts"] = _timed_out
    if leg_errors:
        timings["scatter_errors"] = dict(leg_errors)
        logger.warning("scatter leg failures: %s", leg_errors)

    def _res(i, default):
        if i is None or i >= len(scatter_results):
            return default
        r = scatter_results[i]
        return default if isinstance(r, Exception) else r

    db_hits = _res(0, [])
    vec_hits = _res(1, [])
    fraud_signals = _res(2, {})
    cap_hits = _res(3, [])
    cv_signals = _res(cv_idx, {})

    timings["scatter_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # ── Stage 2: Gather + merge ───────────────────────────────────────────────
    from src.app.services.candidate_retriever import merge_rrf, apply_inventory_filter

    candidates = merge_rrf(db_hits, vec_hits, cap_hits, top_n=top_n * 2)
    candidates = _apply_fraud_gate(candidates, fraud_signals)

    # Batch inventory check for merged candidates
    candidate_skus = [str(c.get("sku") or "") for c in candidates if c.get("sku")]
    stock_map = await _scatter_inventory(candidate_skus)
    candidates = apply_inventory_filter(candidates, stock_map=stock_map, hide_oos=False)[:top_n]

    oos_count = sum(1 for c in candidates if c.get("stock_status") == "out_of_stock")
    oos_fraction = float(oos_count) / float(max(1, len(candidates)))

    timings["gather_ms"] = round((time.perf_counter() - t0) * 1000 - timings["scatter_ms"], 1)

    # ── Stage 3: Conditional deepening (complexity_score >= 7) ───────────────
    deepened = False
    if complexity_score >= 7 and candidates:
        deep_results = await asyncio.gather(
            _bounded(_deep_usecase(candidates, payload), _DEEP_TIMEOUT_S, "deep_usecase", leg_errors),
            _bounded(_deep_budget(candidates, budget_max), _DEEP_TIMEOUT_S, "deep_budget", leg_errors),
            return_exceptions=True,
        )
        uc_ranked = deep_results[0] if not isinstance(deep_results[0], Exception) else None
        budget_ranked = deep_results[1] if not isinstance(deep_results[1], Exception) else None
        if uc_ranked:
            candidates = uc_ranked
        if budget_ranked:
            candidates = budget_ranked
        deepened = True
        timings["deep_ms"] = round((time.perf_counter() - t0) * 1000 - timings["gather_ms"] - timings["scatter_ms"], 1)

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "candidates": candidates[:top_n],
        "fraud_signals": fraud_signals if isinstance(fraud_signals, dict) else {},
        "cv_signals": cv_signals if isinstance(cv_signals, dict) else {},
        "oos_fraction": round(oos_fraction, 3),
        "stock_map": stock_map,
        "latency_ms": timings,
        "leg_errors": dict(leg_errors),
        "deepened": deepened,
    }
