"""Evidence stage (V2 Phase 4, step 2) — tenant-scoped catalog truth for one turn.

Everything the brain will reason over comes through HERE, and only through the facade:
no stage ever touches a table, so the legacy→canonical storage flip stays a mode switch.

Honesty rules carried by this stage:
  • grounding=error is a DEGRADED turn, never a recommend-as-healthy turn (the
    GPT-5.6 #3 ruling, enforced where evidence enters — degraded_response() is the one
    way to answer without catalog verification).
  • refusal_allowed() implements the doctrine end-to-end: refuse ONLY on an explicit
    sells_within()==False. None (ungrounded/unknown) can never refuse.
  • The bundle records HOW it was retrieved (mode, tenant, counts) so parity divergences
    are attributable at the evidence level, not guessed at the response level.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.catalog_read_model import VariantView, search_variants
from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope
from src.app.services.taxonomy_registry import grounding_status, sells_within

_log = logging.getLogger("shopsquire.recommendation_core.evidence")


@dataclass
class EvidenceBundle:
    variants: List[VariantView] = field(default_factory=list)
    grounding: str = "grounded"                 # grounded | empty | error
    retrieval_mode: str = "legacy"
    tenant_id: str = "default"
    total_before_budget: int = 0
    budget_filtered: int = 0
    # TYPED OUTCOME (GPT-5.6 review-2/3 #9): a retrieval FAILURE must be distinguishable from a
    # valid EMPTY result — 'error' means the caller should degrade, 'empty' means honestly no
    # match. errors carries the reasons; latency_ms feeds the per-stage deadline picture.
    status: str = "ok"                          # ok | empty | error
    errors: List[str] = field(default_factory=list)
    latency_ms: int = 0

    @property
    def count(self) -> int:
        return len(self.variants)

    def as_trace(self) -> Dict[str, Any]:
        return {"status": self.status, "grounding": self.grounding, "count": self.count,
                "retrieval_mode": self.retrieval_mode, "errors": self.errors[:5],
                "budget_filtered": self.budget_filtered,
                "total_before_budget": self.total_before_budget, "latency_ms": self.latency_ms}


def _skus_for_node(db, node_handle: str, tenant_id: str, limit: int) -> List[str]:
    """SKUs classified into the node's SUBTREE (product_classification is the retrieval index).
    Raises on DB error — the caller sets bundle.status='error' (never silently '[]')."""
    from sqlalchemy import text as _sql
    rows = db.execute(_sql(
        "SELECT sku FROM product_classification WHERE tenant_id=:t "
        "AND (node_handle = :h OR node_handle LIKE :hp) LIMIT :lim"),
        {"t": tenant_id, "h": node_handle, "hp": node_handle + "-%",
         "lim": max(1, int(limit))}).fetchall()
    return [str(r[0]) for r in rows]


def gather_evidence(db, envelope: TurnEnvelope, *, node_handle: Optional[str] = None,
                    text_query: Optional[str] = None, category: Optional[str] = None,
                    product_type: Optional[str] = None, limit: int = 50,
                    mode: Optional[str] = None, broad: bool = False) -> EvidenceBundle:
    """Facade-only retrieval, tenant-scoped, budget applied in CENTS at the evidence edge
    (one budget surface — never re-parsed downstream). PRIMARY key: the routed TAXONOMY NODE
    (subtree lookup over product_classification — the phrase 'a laptop with A100-like
    performance' retrieves by el-6-6 membership, not by LIKE-matching marketing prose);
    text search is the fallback when no node routed or the node is empty. Never raises;
    an empty bundle with grounding='error' is the failure shape."""
    tenant = envelope.tenant_id
    t0 = time.perf_counter()
    bundle = EvidenceBundle(tenant_id=tenant, grounding=grounding_status(db, tenant_id=tenant))
    variants: List[VariantView] = []
    if node_handle:
        from src.app.services.catalog_read_model import get_variant
        try:
            for sku in _skus_for_node(db, node_handle, tenant, limit):
                v = get_variant(db, sku, tenant_id=tenant, mode=mode)
                if v is not None and v.active:
                    variants.append(v)
        except Exception as exc:   # typed: a lookup FAILURE is 'error', not 'no products'
            _log.warning("taxonomy sku lookup FAILED (node=%s): %s", node_handle, repr(exc)[:120])
            bundle.errors.append(f"taxonomy_lookup:{type(exc).__name__}")
    if variants:
        bundle.retrieval_mode = f"taxonomy:{node_handle}"
    elif not bundle.errors:
        try:
            variants = search_variants(
                db, text_query=None if broad else (text_query or envelope.query or None),
                category=category, product_type=product_type, limit=limit,
                tenant_id=tenant, mode=mode)
        except Exception as exc:
            _log.warning("text retrieval FAILED (tenant=%s): %s", tenant, repr(exc)[:120])
            bundle.errors.append(f"text_retrieval:{type(exc).__name__}")
            variants = []
    if not bundle.retrieval_mode.startswith("taxonomy:"):
        bundle.retrieval_mode = mode or "default"
    bundle.total_before_budget = len(variants)
    lo, hi = envelope.budget_min_cents, envelope.budget_max_cents
    if lo is not None or hi is not None:
        kept = [v for v in variants if v.price_cents is not None
                and (lo is None or v.price_cents >= lo)
                and (hi is None or v.price_cents <= hi)]
        bundle.budget_filtered = len(variants) - len(kept)
        variants = kept
    bundle.variants = variants
    # TYPED OUTCOME: error if a retrieval leg failed; else empty vs ok by result count.
    bundle.status = "error" if bundle.errors else ("ok" if variants else "empty")
    if bundle.errors and bundle.grounding != "error":
        bundle.grounding = "error"   # a retrieval failure degrades grounding — caller degrades
    bundle.latency_ms = int((time.perf_counter() - t0) * 1000)
    return bundle


def refusal_allowed(db, node_handle: str, *, tenant_id: str = "default") -> bool:
    """THE off-catalog gate: True ONLY on an explicit sells_within()==False.
    True → the caller may refuse (with supplier-RFQ honesty). None/True → never refuse."""
    return sells_within(db, node_handle, tenant_id=tenant_id) is False


def degraded_response(envelope: TurnEnvelope, *, reason: str) -> CoreResponse:
    """The ONLY way to answer a turn whose catalog verification failed: an honest degraded
    envelope — no products, no guesses, reason recorded for the trace."""
    return CoreResponse(envelope=envelope, lane="SEARCH", grounding="error", degraded=True,
                        extras={"degraded_reason": reason}).finalize()
