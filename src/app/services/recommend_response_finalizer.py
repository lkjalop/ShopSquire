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
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)


# ── Answer-shaping helpers (P1: moved from recommend.py — single owner) ────────
# These are pure, dependency-light transforms over the response payload. They were
# scattered as inline helpers in the 14.9k-line recommend.py route; consolidating
# them here gives one place that owns answer shape. recommend.py keeps thin
# re-export shims so existing imports/call-sites are unchanged (parity-tested by
# tests/services/test_finalizer_characterization.py).

def _recovery_answer(constraints: Dict[str, Any] | None) -> str:
    """Verdict-first no-match recovery (CRAG): never a dead end, always an upgrade
    path; budget/brand-aware. Shared by the no-candidates branch and the formatter."""
    c = constraints or {}
    bmax = c.get("budget_max")
    bmin = c.get("budget_min")
    brands = c.get("brands") or c.get("brand_hints") or []
    try:
        brand_txt = f" {str(brands[0]).upper()}" if brands else ""
    except Exception:
        brand_txt = ""
    band = ""
    try:
        if bmax is not None:
            band = f" under ${int(bmax):,}"
        elif bmin is not None:
            band = f" above ${int(bmin):,}"
    except Exception:
        band = ""
    return (
        f"No in-stock{brand_txt} match{band} right now. "
        "You can raise your budget, allow other brands, or I can show the "
        "nearest in-stock options."
    )


def _ensure_result_prices(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Frontend product cards read result['price'] (dollars); the pipeline carries
    'price_cents'. Populate 'price' from 'price_cents' so cards don't render $0.
    Never raises."""
    try:
        for key in ("results", "products"):
            items = payload.get(key)
            if isinstance(items, list):
                for r in items:
                    if isinstance(r, dict) and not r.get("price"):
                        pc = r.get("price_cents")
                        if pc:
                            r["price"] = round(int(pc) / 100)
    except Exception:
        pass
    return payload


def _dereference_product_labels(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Replace LLM '[N]' citation placeholders in the answer with the product NAME.

    The summary prompt asks the model to cite products by their [N] catalog label;
    that notation must NOT leak into buyer-facing prose ("the [1] is a solid pick").
    Map [N] -> results[N-1].name. Always-on (a buyer-visible bug fix). Never raises."""
    try:
        am = payload.get("assistant_message")
        results = payload.get("results") or []
        if am and "[" in am and results:
            def _repl(m):
                i = int(m.group(1)) - 1
                if not (0 <= i < len(results) and isinstance(results[i], dict)):
                    return m.group(0)
                nm = str(results[i].get("name") or "").strip()
                if not nm:
                    return m.group(0)
                # If the product name already precedes this label (LLM wrote
                # "Name [N]"), the label is redundant -> drop it instead of doubling.
                pre = m.string[max(0, m.start() - len(nm) - 6):m.start()].lower()
                key = " ".join(nm.lower().split()[:2])
                if key and key in pre:
                    return ""
                return " " + nm
            out = re.sub(r"\s*\[(\d+)\]", _repl, str(am))
            out = re.sub(r"\s{2,}", " ", out).replace(" .", ".").replace(" ,", ",")
            payload["assistant_message"] = out.strip()
    except Exception:
        pass
    return payload


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
