"""Recommendation response finalizer.

Single architectural boundary that converts raw scored candidates into a
frozen, stock-annotated, deduplicated, contract-validated response list.

MUST be called before _summarize_results() so the LLM, trace, and payload
all describe products in the same finalized order.  The late stock-annotation
pass at the bottom of recommend.py is a fallback only; this service is the
canonical stock-annotation path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)


@dataclass
class FinalizerResult:
    results: List[Dict[str, Any]]
    oos_removed: List[Dict[str, Any]] = field(default_factory=list)
    contract_valid: bool = True
    contract_violations: List[str] = field(default_factory=list)


def finalize_recommendation_response(
    results: List[Dict[str, Any]],
    constraints: Dict[str, Any],
    uid: Optional[str] = None,
    stock_filter_opted: bool = False,
) -> FinalizerResult:
    """Transform raw scored candidates into a frozen, contract-valid response list.

    Steps:
    1. Defensive type filter — drop non-dict entries
    2. Deduplicate by SKU — keep first (highest-scored) occurrence
    3. Batch stock lookup — single SQL round-trip via inventory_query_service
    4. Annotate stock_level, stock_status, stock_urgency, cart_eligible
    5. Sort OOS items to end (or remove them when stock_filter_opted=True)
    6. Ensure every result has a non-empty `why` list
    7. Validate contract: sku, name, stock_level, why present on all items

    Args:
        results:           Scored candidates assembled by recommend.py
        constraints:       Current query constraints dict
        uid:               User ID (for logging only)
        stock_filter_opted: True when user has opted "in-stock only" — removes OOS items

    Returns:
        FinalizerResult with the finalized list and contract validation status.
        On any exception the caller should fall back to the raw results list.
    """
    if not results:
        return FinalizerResult(results=[], contract_valid=True)

    # 1. Defensive type filter
    clean: List[Dict[str, Any]] = [r for r in results if isinstance(r, dict)]

    # 2. Deduplicate by SKU
    seen_skus: set = set()
    deduped: List[Dict[str, Any]] = []
    for r in clean:
        sku = str(r.get("sku") or "").strip()
        if sku:
            if sku in seen_skus:
                continue
            seen_skus.add(sku)
        deduped.append(r)

    # 3. Batch stock lookup
    skus_to_check = [
        str(r.get("sku") or "")
        for r in deduped
        if str(r.get("sku") or "").strip()
    ]
    stock_map: Dict[str, int] = {}
    if skus_to_check:
        try:
            from src.app.services.inventory_query_service import batch_stock_levels
            stock_map = dict(batch_stock_levels(skus_to_check) or {})
        except Exception as exc:
            _log.debug("finalizer: batch_stock_levels unavailable: %s", exc)
            # Fall back to whatever stock/stock_level is already on each result
            for r in deduped:
                sku = str(r.get("sku") or "").strip()
                if sku:
                    stock_map[sku] = int(r.get("stock") or r.get("stock_level") or 0)

    # 4+5. Annotate and sort
    oos_removed: List[Dict[str, Any]] = []
    annotated: List[Dict[str, Any]] = []
    for r in deduped:
        sku = str(r.get("sku") or "").strip()
        # Use live stock from map; fall back to value already on result
        stock = int(
            stock_map.get(sku, r.get("stock") or r.get("stock_level") or 0)
        )
        r["stock_level"] = stock
        r["cart_eligible"] = stock > 0

        if stock == 0:
            r["stock_status"] = "out_of_stock"
            # Accumulate rather than overwrite in case caller set a penalty earlier
            r["_rank_penalty"] = float(r.get("_rank_penalty") or 0.0) + 0.5
            if stock_filter_opted:
                oos_removed.append(r)
                continue
        elif stock <= 3:
            r["stock_status"] = "very_low_stock"
            r["stock_urgency"] = f"Only {stock} left"
        elif stock <= 10:
            r["stock_status"] = "low_stock"
            r["stock_urgency"] = f"{stock} units remaining"
        else:
            r["stock_status"] = "in_stock"
            r.pop("stock_urgency", None)

        # 6. Ensure why is populated
        if not r.get("why"):
            _pos = list(((r.get("factors") or {}).get("positive") or []))[:3]
            r["why"] = [str(f).lstrip("+") for f in _pos] if _pos else ["matched your query"]

        annotated.append(r)

    # Sort: OOS items (penalty > 0) to end, preserve relative order within tiers
    annotated.sort(key=lambda r: float(r.get("_rank_penalty") or 0.0))

    # 7. Contract validation
    violations: List[str] = []
    for i, r in enumerate(annotated[:10]):
        if not r.get("sku"):
            violations.append(f"results[{i}] missing sku")
        if not r.get("name"):
            violations.append(f"results[{i}] missing name")
        if r.get("stock_level") is None:
            violations.append(f"results[{i}] stock_level is null")
        if not isinstance(r.get("why"), list) or not r["why"]:
            violations.append(f"results[{i}] why is empty or not a list")
        if r.get("price_cents") is None and r.get("price") is None:
            violations.append(f"results[{i}] missing price")

    if violations:
        _log.warning(
            "finalizer contract violations uid=%s count=%d first=%s",
            uid or "anon",
            len(violations),
            violations[0],
        )

    return FinalizerResult(
        results=annotated,
        oos_removed=oos_removed,
        contract_valid=len(violations) == 0,
        contract_violations=violations,
    )
