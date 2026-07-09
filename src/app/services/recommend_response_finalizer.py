"""Recommendation response finalizer.

Single architectural boundary that converts raw scored candidates into a
frozen, stock-annotated, deduplicated, contract-validated response list.

MUST be called before _summarize_results() so the LLM, trace, and payload
all describe products in the same finalized order.  The late stock-annotation
pass at the bottom of recommend.py is a fallback only; this service is the
canonical stock-annotation path.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
This module is entirely CORE (vertical-agnostic).
  • Stock annotation, deduplication, price capping, contract validation —
    none of these depend on whether the product is a laptop or a medicine.
  • No electronics-specific tokens, spec names, or heuristics.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

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
            # collapse only HORIZONTAL whitespace — preserve \n\n paragraph breaks (the buyer chat splits
            # on blank lines). A blanket \s{2,}->' ' here was flattening every reply that contained a '['
            # (e.g. a "[512GB]" spec suffix triggered this path) into one blob.
            out = re.sub(r"[ \t]{2,}", " ", out).replace(" .", ".").replace(" ,", ",")
            out = re.sub(r"[ \t]+\n", "\n", out)      # no trailing spaces before a newline
            out = re.sub(r"\n{3,}", "\n\n", out)      # cap consecutive blank lines at one break
            payload["assistant_message"] = out.strip()
    except Exception:
        pass
    return payload


def _finalize_answer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Single-formatter normalization (COMMERCE_FORMATTER): guarantee assistant_message
    is never empty. Every response funnels through _with_trace, so this ONE pass
    retires the empty-answer-across-branches class. Behavior-preserving when an answer
    already exists (the 95% path). Never raises."""
    try:
        if str(payload.get("assistant_message") or "").strip():
            return payload  # already answered -> unchanged
        msg = str(payload.get("message") or "").strip()
        if msg:
            payload["assistant_message"] = msg
            return payload
        rec = _recovery_answer(payload.get("constraints_used"))
        payload["assistant_message"] = rec
        if not str(payload.get("message") or "").strip():
            payload["message"] = rec
    except Exception:
        pass
    return payload


def _demote_off_category(results: list, query: str | None) -> list:
    """EXCLUDE non-primary products (accessories: router/monitor/headset/bag/SSD/…)
    from headline results whenever PRIMARY products (laptop/desktop) are also present —
    so an off-TYPE item never reaches the buyer for a 'laptop for uni' query.

    Gates on product TYPE, not a price band or a keyword denylist: a $59 product can be
    perfectly valid (it's a real range-extender price) — the problem is it's the wrong
    TYPE for a laptop request. Type classification + the type→primary mapping are the
    agnostic core (services/product_classifier.py + the StoreProfile). Excluded
    accessories aren't discarded — they're the cart-upsell pool (companion_types_for).

    Keeps everything if results are ALL accessories (user searched 'headset') or ALL
    primary. Query-independent; safe on every path; never empties."""
    try:
        if not isinstance(results, list) or len(results) < 2:
            return results
        from src.app.services.product_classifier import is_primary_product
        primary, accessory = [], []
        for r in results:
            if not isinstance(r, dict):
                primary.append(r)
                continue
            specs = r.get("specs") if isinstance(r.get("specs"), dict) else None
            (primary if is_primary_product(r.get("name"), specs) else accessory).append(r)
        return primary if (primary and accessory) else results
    except Exception:
        return results


def drop_untyped_for_primary_intent(results: list, *, primary_intent: bool) -> list:
    """X1 (2026-07-09): cross-vertical retrieval bleed — 'fine tune a 7b model under 2500'
    returned HAND SANITISER and paracetamol (pharmacy demo SKUs): nothing in the query matched
    electronics tokens, and _demote_off_category keeps everything when NO primaries exist.
    Discriminator: foreign-vertical items fall into the GENERIC 'accessory' fallback (no
    specific type rule matches), while real catalog items get specific types (laptop/monitor/
    bag/...). When the turn has PRIMARY-DEVICE INTENT (workload floors / use-case /
    must_have_gpu), drop generic-fallback items — an honest empty result beats selling
    sanitiser to an AI engineer. Specific accessory types (monitor, bag, headset) survive;
    only the unclassifiable are removed. Never raises."""
    try:
        if not primary_intent or not isinstance(results, list) or not results:
            return results
        from src.app.services.product_classifier import classify_product_type, is_primary_product
        # When a primary-device turn has ANY real device, keep it and drop only the generic-
        # 'accessory' fallback noise (original behavior). But when a hard floor zeroed out every
        # device (e.g. an AI query's 32GB-RAM floor eliminates all 16GB laptops) and ONLY
        # accessories survived, those accessories are pure noise — an honest no-match beats
        # selling a Wi-Fi extender or a laptop bag for AI training (2026-07-09).
        has_primary = any(
            isinstance(r, dict) and is_primary_product(
                r.get("name"), r.get("specs") if isinstance(r.get("specs"), dict) else None)
            for r in results
        )
        if not has_primary:
            return []
        kept = []
        for r in results:
            if not isinstance(r, dict):
                kept.append(r)
                continue
            specs = r.get("specs") if isinstance(r.get("specs"), dict) else None
            t = classify_product_type(str(r.get("name") or ""), specs)
            if str(t or "accessory") != "accessory":
                kept.append(r)
        return kept
    except Exception:
        return results


def _annotate_type_and_price_integrity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Tag every result with product_type and run the price-anomaly (poisoning) guard.

    SECURITY (shift-left, agnostic core): a price outside its TYPE band is a data-
    integrity signal, not a pricing opinion. Underpriced is the dangerous case — a
    poisoned feed/import/DB row that reads a $1,800 laptop as $45 bleeds margin on
    every checkout, at scale. We DON'T silently sell it: anomalous items are dropped
    from buyer results (when priced items remain) and summarised in payload
    ['data_integrity'] for the admin trace / source_statuses. Never raises."""
    try:
        from src.app.services.product_classifier import annotate_product
        # X1 choke point (2026-07-09): several retrieval lanes never pass the in-suggest drop
        # sites, so foreign-vertical items (pharmacy SKUs on an AI query) survived to the
        # response. This wrapper runs on EVERY path; when the turn carries workload floors
        # (primary-device intent by definition), remove generic-fallback items here.
        try:
            if (payload.get("workload_fit") or {}).get("floors"):
                for _k in ("results", "products"):
                    if isinstance(payload.get(_k), list) and payload[_k]:
                        payload[_k] = drop_untyped_for_primary_intent(payload[_k], primary_intent=True)
        except Exception:
            pass
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return payload
        flagged: List[Dict[str, Any]] = []
        clean: List[Dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                clean.append(r)
                continue
            annotate_product(r)
            if r.get("price_anomaly"):
                flagged.append({
                    "sku": r.get("sku"), "name": r.get("name"),
                    "price": r.get("price"), "product_type": r.get("product_type"),
                    "anomaly": r.get("price_anomaly"),
                })
            else:
                clean.append(r)
        if flagged:
            # Quarantine poisoned-price items from buyer results when clean ones remain;
            # always surface them for the admin/security trace.
            if clean:
                payload["results"] = clean
                if isinstance(payload.get("products"), list):
                    payload["products"] = clean
            payload["data_integrity"] = {
                "price_anomalies": flagged,
                "quarantined": bool(clean),
                "note": "Price(s) outside expected type band — possible catalog/feed poisoning. "
                        "Quarantined from buyer results pending review." if clean else
                        "Price(s) outside expected type band — flagged for review.",
            }
    except Exception:
        pass
    return payload


def _composer_enabled() -> bool:
    """COMMERCE_COMPOSER flag — gates the educational security challenge + compound
    answer composition. Default off = today's behaviour unchanged."""
    return str(os.getenv("COMMERCE_COMPOSER", "0")).strip().lower() in ("1", "true", "yes")


def _formatter_enabled() -> bool:
    """COMMERCE_FORMATTER flag — gates the never-empty single-formatter pass."""
    return str(os.getenv("COMMERCE_FORMATTER", "0")).strip().lower() in ("1", "true", "yes")


def finalize_response_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """SINGLE owner of buyer-facing answer shaping (P1 one-writer).

    Runs the pure response transforms in one fixed order so the result is identical
    no matter which branch produced the payload. Idempotent (each step only fills/
    excludes/flags what isn't already done), so it is safe to call at more than one
    choke point. Does NOT do I/O — the LLM-dependent compound composition stays in the
    route (it needs a model call + request context) and runs BEFORE this.

    Order: price-fill -> off-type exclusion -> price-poisoning guard -> [N] deref ->
    security challenge -> never-empty formatter. Never raises."""
    try:
        payload = _ensure_result_prices(payload)                       # price_cents -> price
        payload["results"] = _demote_off_category(payload.get("results") or [], None)
        if isinstance(payload.get("products"), list):
            payload["products"] = payload["results"]
        payload = _annotate_type_and_price_integrity(payload)          # price-poisoning guard
        payload = _dereference_product_labels(payload)                 # [N] -> product name
        payload = _maybe_apply_security_challenge(payload)             # educational image-security
        if _formatter_enabled():
            payload = _finalize_answer(payload)                        # never-empty guarantee
    except Exception:
        pass
    return payload


def _build_security_challenge_text(payload: Dict[str, Any]) -> str | None:
    """Gather image-security signals from the payload and produce ONE educational,
    category-specific buyer challenge. Never echoes the payload."""
    try:
        from src.app.services.answer_composer import security_challenge
        signals: Dict[str, Any] = {}
        sh = payload.get("safe_image_hints") if isinstance(payload.get("safe_image_hints"), dict) else {}
        uf = sh.get("unsafe_flags") if isinstance(sh.get("unsafe_flags"), dict) else {}
        signals.update(uf or {})
        isec = payload.get("image_security") if isinstance(payload.get("image_security"), dict) else {}
        for k, v in (isec or {}).items():
            if isinstance(v, (bool, int, float)):
                signals[k] = v
        if sh.get("trust_state"):
            signals["trust_state"] = sh.get("trust_state")
        if payload.get("image_flagged") or payload.get("image_untrusted"):
            signals["image_flagged"] = True
        return security_challenge(signals)
    except Exception:
        return None


def _maybe_apply_security_challenge(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Prepend the educational security challenge to the buyer message for ANY flagged
    image (not just compound queries). Content-idempotent — safe to call at multiple
    choke points. Replaces the older terse '⚠️ [SECURITY] Image flagged — …' prefix
    with the category-specific challenge. Flag-gated by COMMERCE_COMPOSER. Never raises."""
    try:
        if not _composer_enabled():
            return payload
        txt = _build_security_challenge_text(payload)
        if not txt:
            return payload
        msg = str(payload.get("assistant_message") or "").strip()
        if txt[:40] in msg:  # already applied (idempotent by content)
            return payload
        # Drop the older terse security prefix if present, then prepend the challenge.
        msg = re.sub(r"^⚠️\s*\[SECURITY\][^.]*\.\s*", "", msg).strip()
        composed = ("⚠️ " + txt + (" " + msg if msg else "")).strip()
        payload["assistant_message"] = composed
        payload["message"] = composed
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


def run_finalizer(
    *,
    results: List[Dict[str, Any]],
    constraints: Dict[str, Any],
    uid: Optional[str],
    kv: Optional[Dict[str, Any]],
    query: Optional[str],
    payload: Dict[str, Any],
    demote_off_category: Optional[Callable[[Any, Any], Any]] = None,
    finalize_fn: Optional[Callable[..., "FinalizerResult"]] = None,
    log: Any = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Route wrapper for the canonical finalizer: stock annotation + contract validation +
    off-category demotion, writing the frozen list into ``payload`` (results + products). Returns
    (results, finalizer_ran). On any failure returns (results unchanged, False) so the late fallback
    annotation pass still runs. Never raises. Off-category demoter defaults to the module-local one."""
    finalizer_ran = False
    demote = demote_off_category or _demote_off_category
    try:
        fn = finalize_fn or finalize_recommendation_response
        stock_filter_opted = bool((kv or {}).get("stock_filter_preference") == "in_stock_only")
        fin = fn(results=results, constraints=constraints, uid=uid, stock_filter_opted=stock_filter_opted)
        results = fin.results
        results = demote(results, query)  # drop off-category (e.g. a router for a laptop query)
        if isinstance(payload, dict):
            payload["results"] = results
            payload["products"] = results
            if getattr(fin, "oos_removed", None):
                payload["oos_removed_count"] = len(fin.oos_removed)
            if not getattr(fin, "contract_valid", True):
                payload["_contract_violations"] = list(getattr(fin, "contract_violations", []))[:5]
        finalizer_ran = True
    except Exception as exc:
        if log is not None:
            try:
                log.warning("recommend_finalizer failed, continuing with pre-finalized results: %s", exc)
            except Exception:
                pass
    return results, finalizer_ran


def build_result_rows(
    scored: List[Dict[str, Any]],
    *,
    baseline_pos: Optional[Dict[str, int]] = None,
    why_by_sku: Optional[Dict[str, str]] = None,
    delta_by_sku: Optional[Dict[str, Any]] = None,
    normalize_score: Callable[[float], float],
) -> List[Dict[str, Any]]:
    """Assemble the per-product response rows from scored candidates + rerank metadata. Pure:
    maps each {score, candidate, factors} into the response row — specs (spread) + why
    (factors.positive) + why_not (factors.negative) + contrastive_why + delta_vs_anchor + rank /
    rerank deltas + normalized score. normalize_score is injected (it depends on the score range, which
    the route also reuses for the image-lane fill). Vertical-blind; never raises on a malformed item."""
    baseline_pos = baseline_pos or {}
    why_by_sku = why_by_sku or {}
    delta_by_sku = delta_by_sku or {}
    top_score = float(scored[0].get("score") or 0.0) if scored else 0.0
    rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(scored or []):
        if not isinstance(item, dict):
            continue
        c = item.get("candidate") or {}
        score_val = float(item.get("score") or 0.0)
        sku = c.get("sku")
        baseline_rank = baseline_pos.get(sku) if sku in baseline_pos else None
        rerank_delta = (baseline_rank - idx) if baseline_rank is not None else None
        factors = item.get("factors") or {}
        rows.append({
            **c,
            "confidence": item.get("confidence"),
            "factors": item.get("factors"),
            "why": list((factors.get("positive") or []))[:3],
            "score": score_val,
            "score_norm": normalize_score(score_val),
            "rank_delta": round(top_score - score_val, 2),
            "why_not": list((factors.get("negative") or []))[:3],
            "contrastive_why": why_by_sku.get(str(sku or ""), ""),
            "delta_vs_anchor": delta_by_sku.get(str(sku or ""), {}),
            "baseline_rank": baseline_rank,
            "rerank_delta": rerank_delta,
        })
    return rows
