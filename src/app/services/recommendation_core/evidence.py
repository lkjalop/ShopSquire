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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.catalog_read_model import VariantView, search_variants
from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope
from src.app.services.taxonomy_registry import grounding_status, sells_within


@dataclass
class EvidenceBundle:
    variants: List[VariantView] = field(default_factory=list)
    grounding: str = "grounded"                 # grounded | empty | error
    retrieval_mode: str = "legacy"
    tenant_id: str = "default"
    total_before_budget: int = 0
    budget_filtered: int = 0

    @property
    def count(self) -> int:
        return len(self.variants)


def gather_evidence(db, envelope: TurnEnvelope, *, text_query: Optional[str] = None,
                    category: Optional[str] = None, product_type: Optional[str] = None,
                    limit: int = 50, mode: Optional[str] = None) -> EvidenceBundle:
    """Facade-only retrieval, tenant-scoped, budget applied in CENTS at the evidence edge
    (one budget surface — never re-parsed downstream). Never raises; an empty bundle with
    grounding='error' is the failure shape."""
    tenant = envelope.tenant_id
    bundle = EvidenceBundle(tenant_id=tenant, grounding=grounding_status(db, tenant_id=tenant))
    try:
        variants = search_variants(
            db, text_query=text_query or (envelope.query or None), category=category,
            product_type=product_type, limit=limit, tenant_id=tenant, mode=mode)
    except Exception:
        variants = []
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
