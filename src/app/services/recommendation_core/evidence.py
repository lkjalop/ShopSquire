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
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from src.app.services.catalog_read_model import VariantView, get_variants, search_variants
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
    queries: int = 0                            # retrieval-leg DB round-trips (M2-B3: O(1) not O(N))

    @property
    def count(self) -> int:
        return len(self.variants)

    def as_trace(self) -> Dict[str, Any]:
        return {"status": self.status, "grounding": self.grounding, "count": self.count,
                "retrieval_mode": self.retrieval_mode, "errors": self.errors[:5],
                "budget_filtered": self.budget_filtered,
                "total_before_budget": self.total_before_budget, "latency_ms": self.latency_ms,
                "queries": self.queries}


class _CountingDB:
    """Counts retrieval-leg round-trips (M2-B3): the bundle records its own query cost so an
    N+1 regression is a visible number in every trace, not a profiler session."""
    def __init__(self, inner):
        self._inner = inner
        self.queries = 0

    def execute(self, *a, **kw):
        self.queries += 1
        return self._inner.execute(*a, **kw)


def _skus_for_node(db, node_handle: str, tenant_id: str, limit: int) -> List[str]:
    """SKUs classified into the node's SUBTREE (product_classification is the retrieval index).
    ORDER BY sku (M2-B3): an unordered LIMIT page is engine-arbitrary — the candidate slate
    must be deterministic across runs. Raises on DB error — the caller sets
    bundle.status='error' (never silently '[]')."""
    from sqlalchemy import text as _sql
    rows = db.execute(_sql(
        "SELECT sku FROM product_classification WHERE tenant_id=:t "
        "AND (node_handle = :h OR node_handle LIKE :hp) ORDER BY sku LIMIT :lim"),
        {"t": tenant_id, "h": node_handle, "hp": node_handle + "-%",
         "lim": max(1, int(limit))}).fetchall()
    return [str(r[0]) for r in rows]


def _attach_taxonomy_nodes(db, variants: List[VariantView], tenant_id: str) -> List[VariantView]:
    """Batch-enrich catalog views with their approved taxonomy identity.

    Both catalog adapters intentionally share ``VariantView`` but historically left its
    documented taxonomy slot empty. Recommendation continuity and audit evidence must use the
    approved classification table, not infer categories from product names.
    """
    if not variants:
        return variants
    from sqlalchemy import text as _sql

    params: Dict[str, Any] = {f"s{i}": variant.sku for i, variant in enumerate(variants)}
    params["t"] = tenant_id
    placeholders = ", ".join(f":s{i}" for i in range(len(variants)))
    try:
        rows = db.execute(_sql(
            "SELECT sku, node_handle FROM product_classification "
            f"WHERE tenant_id=:t AND status='approved' AND sku IN ({placeholders})"
        ), params).fetchall()
    except Exception as exc:
        _log.warning("taxonomy view enrichment skipped (tenant=%s): %s",
                     tenant_id, repr(exc)[:120])
        return variants
    nodes = {str(row[0]): str(row[1]) for row in rows if row[0] and row[1]}
    return [replace(variant, taxonomy_node_id=nodes.get(variant.sku)) for variant in variants]


def gather_evidence(db, envelope: TurnEnvelope, *, node_handle: Optional[str] = None,
                    text_query: Optional[str] = None, category: Optional[str] = None,
                    product_type: Optional[str] = None, limit: int = 50,
                    mode: Optional[str] = None, broad: bool = False,
                    exact_skus: Optional[List[str]] = None) -> EvidenceBundle:
    """Facade-only retrieval, tenant-scoped, budget applied in CENTS at the evidence edge
    (one budget surface — never re-parsed downstream). PRIMARY key: the routed TAXONOMY NODE
    (subtree lookup over product_classification — the phrase 'a laptop with A100-like
    performance' retrieves by el-6-6 membership, not by LIKE-matching marketing prose);
    text search is the fallback when no node routed or the node is empty. Never raises;
    an empty bundle with grounding='error' is the failure shape."""
    tenant = envelope.tenant_id
    t0 = time.perf_counter()
    bundle = EvidenceBundle(tenant_id=tenant, grounding=grounding_status(db, tenant_id=tenant))
    counted = _CountingDB(db)      # retrieval legs only; grounding/refusal reads not in scope
    variants: List[VariantView] = []
    if exact_skus:
        try:
            variants = [variant for variant in get_variants(
                counted, list(exact_skus), tenant_id=tenant, mode=mode
            ) if variant.active]
            bundle.retrieval_mode = "exact_product_alias"
        except Exception as exc:
            bundle.errors.append(f"exact_product_lookup:{type(exc).__name__}")
            variants = []
    elif node_handle:
        try:
            # BATCH (M2-B3): one sku-list query + one query per table — was ~3 × N per turn
            skus = _skus_for_node(counted, node_handle, tenant, limit)
            variants = [v for v in get_variants(counted, skus, tenant_id=tenant, mode=mode)
                        if v.active]
        except Exception as exc:   # typed: a lookup FAILURE is 'error', not 'no products'
            _log.warning("taxonomy sku lookup FAILED (node=%s): %s", node_handle, repr(exc)[:120])
            bundle.errors.append(f"taxonomy_lookup:{type(exc).__name__}")
            variants = []
    if variants and not exact_skus:
        bundle.retrieval_mode = f"taxonomy:{node_handle}"
    elif not variants and not exact_skus:
        # TEXT FALLBACK always attempted (review #1): a taxonomy-leg ERROR must still fall
        # through to text search — the old code did, and dropping it turned a transient
        # product_classification blip into a buyer-visible 'couldn't verify catalog'. The
        # taxonomy error is recorded either way; the turn only DEGRADES if BOTH legs fail.
        text_errored = False
        try:
            variants = search_variants(
                counted, text_query=None if broad else (text_query or envelope.query or None),
                category=category, product_type=product_type, limit=limit,
                tenant_id=tenant, mode=mode)
        except Exception as exc:
            _log.warning("text retrieval FAILED (tenant=%s): %s", tenant, repr(exc)[:120])
            bundle.errors.append(f"text_retrieval:{type(exc).__name__}")
            text_errored = True
            variants = []
        # a taxonomy error that the text leg RECOVERED from is no longer a turn error
        if variants and not text_errored:
            bundle.errors = [e for e in bundle.errors if not e.startswith("taxonomy_lookup")]
    if (not bundle.retrieval_mode.startswith("taxonomy:")
            and bundle.retrieval_mode != "exact_product_alias"):
        bundle.retrieval_mode = mode or "default"
    variants = _attach_taxonomy_nodes(counted, variants, tenant)
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
    bundle.queries = counted.queries
    return bundle


def refusal_allowed(db, node_handle: str, *, tenant_id: str = "default") -> bool:
    """THE off-catalog gate: True ONLY on an explicit sells_within()==False.
    True → the caller may refuse (with supplier-RFQ honesty). None/True → never refuse."""
    return sells_within(db, node_handle, tenant_id=tenant_id) is False


def degraded_response(envelope: TurnEnvelope, *, reason: str,
                      grounding: str = "error") -> CoreResponse:
    """The ONLY way to answer a turn whose catalog verification failed OR whose tenant is not
    yet onboarded — an honest degraded envelope: no products, no guesses, reason recorded for
    the trace. `grounding` is preserved (error vs empty) so telemetry/shadow can tell an
    infra failure from an un-onboarded tenant."""
    return CoreResponse(envelope=envelope, lane="SEARCH", grounding=grounding, degraded=True,
                        extras={"degraded_reason": reason}).finalize()
