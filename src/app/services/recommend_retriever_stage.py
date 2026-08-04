"""Retrieval mode + fusion stage (Tier 2). CORE / vertical-blind.

RECOMMEND_RETRIEVAL_MODE (env overrides config flag; default 'shadow'):
  - shadow : primary (monolith) results are authoritative; V2 runs for parity metrics only. DEFAULT.
  - fusion : RRF-merge primary + V2, then the CALLER re-applies budget/stock/security filters to the
             merged set (V2 candidates never bypass guards — fusion happens BEFORE ranking/filters).
  - primary: V2 first; monolith fallback when V2 is empty/unavailable.

Cutover to fusion/primary is gated on parity metrics (recommend_retrieval_metrics) from a live run.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from src.app.services.candidate_retriever import merge_rrf

MODES = ("shadow", "fusion", "primary")


def resolve_retrieval_mode(flags: Dict[str, Any] | None = None) -> str:
    raw = os.getenv("RECOMMEND_RETRIEVAL_MODE", "")
    if not raw and isinstance(flags, dict):
        raw = str(flags.get("RECOMMEND_RETRIEVAL_MODE") or "")
    m = str(raw or "shadow").strip().lower()
    return m if m in MODES else "shadow"


def fuse(primary: List[Dict[str, Any]], v2: List[Dict[str, Any]], *, top_n: int = 60) -> List[Dict[str, Any]]:
    """RRF-merge two candidate lists (dedup by sku). Degenerate cases return the non-empty list."""
    p = [c for c in (primary or []) if isinstance(c, dict) and c.get("sku")]
    v = [c for c in (v2 or []) if isinstance(c, dict) and c.get("sku")]
    if not v:
        return list(p)
    if not p:
        return list(v)
    return merge_rrf(p, v, top_n=top_n)


def apply_retrieval_mode(
    mode: str, *, primary: List[Dict[str, Any]], v2: List[Dict[str, Any]], top_n: int = 60
) -> List[Dict[str, Any]]:
    """Return the candidate list for the mode. The caller re-applies rank/stock/budget/security
    filters afterwards (this never filters or bypasses guards itself)."""
    if mode == "fusion":
        return fuse(primary, v2, top_n=top_n)
    if mode == "primary":
        v = [c for c in (v2 or []) if isinstance(c, dict) and c.get("sku")]
        return list(v) if v else list(primary or [])  # monolith fallback on empty/unavailable V2
    return list(primary or [])  # shadow


def run_retrieval_mode_stage(
    *,
    flags: Dict[str, Any] | None,
    candidates: List[Dict[str, Any]],
    v2_holder: Dict[str, Any] | None = None,
    timing_breakdown: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Route wrapper: resolve RECOMMEND_RETRIEVAL_MODE and fuse/swap the V2 hybrid candidates when
    ready (fusion/primary) — BEFORE ranking, so V2 never bypasses the downstream ranking/stock/budget/
    security guards. Returns the (possibly fused) candidate list and records retrieval_mode +
    retrieval_fused_count in timing_breakdown. Degrades to the primary candidates when V2 isn't ready
    (non-blocking). Raises on internal error so the caller can trace it (matches _trace_system_error)."""
    mode = resolve_retrieval_mode(flags)
    if isinstance(timing_breakdown, dict):
        timing_breakdown["retrieval_mode"] = mode
    v2h = v2_holder or {}
    if mode in ("fusion", "primary") and v2h.get("done") and v2h.get("cands"):
        fused = apply_retrieval_mode(mode, primary=candidates, v2=v2h.get("cands") or [])
        if fused:
            candidates = fused
            if isinstance(timing_breakdown, dict):
                timing_breakdown["retrieval_fused_count"] = len(candidates)
    return candidates
