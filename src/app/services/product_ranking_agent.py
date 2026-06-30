"""Product Ranking Agent — listwise reranking, contrastive WHY, diversity enforcement.

Upgrades the recommendation pipeline's reranking pass with:
1. Listwise scoring: evaluates ALL candidates together (not pairwise)
2. Contrastive WHY: per-product explanation of why it was chosen vs. rejected ones
3. Diversity enforcement: prevent N near-identical products dominating the top results
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.app.services.price_conversion import cents_to_dollars


def apply_stock_penalty(
    scored: List[Dict[str, Any]],
    *,
    batch_stock_fn: Callable[[List[str]], Dict[str, Any]],
    oos_penalty: float = 0.5,
    unknown_penalty: float = 0.1,
) -> List[Dict[str, Any]]:
    """Penalize out-of-stock / unknown-stock candidates BEFORE results assembly so ranking reflects
    live stock reality (OOS -0.5, unknown -0.1), then re-sort by score. Mutates item['score'] and
    candidate['_stock_penalty'] in place; batch_stock_fn(skus)->{sku: level} is injected. No-op when
    there are no SKUs; never raises (a stock-lookup failure leaves ranking untouched). Vertical-blind."""
    if not scored:
        return scored
    skus = [
        str((i or {}).get("candidate", {}).get("sku") or "")
        for i in scored
        if isinstance(i, dict) and isinstance(i.get("candidate"), dict)
    ]
    skus = [s for s in skus if s]
    if not skus:
        return scored
    try:
        stock = batch_stock_fn(skus) or {}
    except Exception:
        return scored
    for item in scored:
        if not isinstance(item, dict):
            continue
        cand = item.get("candidate") or {}
        sku = str(cand.get("sku") or "")
        if not sku:
            continue
        lvl = stock.get(sku)
        if lvl is None:
            item["score"] = float(item.get("score") or 0.0) - unknown_penalty
            cand["_stock_penalty"] = "unknown"
        elif lvl == 0:
            item["score"] = float(item.get("score") or 0.0) - oos_penalty
            cand["_stock_penalty"] = "out_of_stock"
    scored.sort(key=lambda x: float((x or {}).get("score") or 0.0), reverse=True)
    return scored


def identity_anchor_boost(
    scored: List[Dict[str, Any]],
    *,
    identity_model: Optional[str] = None,
    boost: float = 0.6,
) -> List[Dict[str, Any]]:
    """Multimodal anchoring — float candidates that MATCH an image-identified product line to the top.

    `scored` is the in-pipeline list of {"score": float, "candidate": {...}} items. When an uploaded
    image identified a specific model (e.g. "ThinkPad X1"), candidates whose name/model/title contain
    those tokens get a score bump proportional to how many tokens match, then the list is re-sorted in
    place. No-op when there is no identity_model. Pure (no I/O); vertical-blind."""
    model = str(identity_model or "").strip().lower()
    if not model or not scored:
        return scored
    tokens = [t for t in re.split(r"[^a-z0-9]+", model) if len(t) >= 2]
    if not tokens:
        return scored
    changed = False
    for item in scored:
        if not isinstance(item, dict):
            continue
        cand = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        hay = f"{cand.get('name', '')} {cand.get('model', '')} {cand.get('title', '')}".lower()
        hits = sum(1 for t in tokens if t in hay)
        if hits:
            frac = hits / len(tokens)
            item["score"] = float(item.get("score") or 0.0) + boost * frac
            cand["_identity_anchor"] = round(frac, 3)
            changed = True
    if changed:
        scored.sort(key=lambda x: float((x or {}).get("score") or 0.0), reverse=True)
    return scored


@dataclass
class RankedProduct:
    """A product with its ranking score and explanation."""
    product_id: str
    score: float = 0.0
    rank: int = 0
    contrastive_why: str = ""
    diversity_group: str = ""
    component_scores: Dict[str, float] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)
    delta_vs_anchor: Dict[str, str] = field(default_factory=dict)


def _extract_diversity_key(product: Dict[str, Any]) -> str:
    """Generate a diversity group key from product attributes.

    Products with the same diversification key are considered "near-identical"
    for diversity enforcement.  Key is brand + cpu_family + ram_tier.
    """
    brand = (product.get("brand") or "unknown").lower().strip()
    cpu = (product.get("cpu_family") or product.get("cpu") or "unknown").lower().strip()
    # Normalize cpu family (e.g. "Intel Core i5-13xxx" → "i5-13")
    for prefix in ("intel core ", "amd ryzen "):
        if cpu.startswith(prefix):
            cpu = cpu[len(prefix):]
    cpu_fam = cpu[:5]  # first 5 chars as family
    ram = product.get("ram_gb") or 0
    ram_tier = "low" if ram <= 8 else ("mid" if ram <= 16 else "high")
    return f"{brand}|{cpu_fam}|{ram_tier}"


# ── Category-specific ranking signal definitions ──
_CATEGORY_RANKING_DIMENSIONS: Dict[str, list] = {
    # Each entry: (required_spec_key, product_key, comparison_mode)
    # comparison_mode: "ratio" (higher is better), "exact" (must match), "bool" (has/not)
    "laptop": [
        ("min_ram_gb", "ram_gb", "ratio"),
        ("gpu_needed", "has_dedicated_gpu", "bool"),
        ("min_gpu_vram_gb", "gpu_vram_gb", "ratio"),
        ("min_storage_gb", "storage_gb", "ratio"),
        ("min_display_inches", "display_inches", "ratio"),
        ("min_refresh_hz", "refresh_hz", "ratio"),
        ("touch_screen_required", "has_touch_screen", "bool"),
    ],
    "clothing": [
        ("size", "size", "exact"),
        ("color", "color", "exact"),
        ("material", "material", "exact"),
        ("occasion", "occasion", "exact"),
        ("gender", "gender", "exact"),
    ],
    "kitchen": [
        ("capacity", "capacity", "ratio"),
        ("power_watts", "power_watts", "ratio"),
        ("energy_rating", "energy_rating", "exact"),
        ("material", "material", "exact"),
    ],
    "furniture": [
        ("max_width_cm", "width_cm", "ratio_inverse"),  # product must be ≤ max
        ("max_height_cm", "height_cm", "ratio_inverse"),
        ("material", "material", "exact"),
        ("style", "style", "exact"),
        ("seats", "seats", "ratio"),
    ],
    "tv": [
        ("min_screen_inches", "screen_inches", "ratio"),
        ("display_tech", "display_tech", "exact"),  # OLED/QLED/LED
        ("min_refresh_hz", "refresh_hz", "ratio"),
        ("smart_platform", "smart_platform", "exact"),
        ("hdr_support", "hdr_support", "bool"),
    ],
    "phone": [
        ("min_storage_gb", "storage_gb", "ratio"),
        ("min_ram_gb", "ram_gb", "ratio"),
        ("platform", "platform", "exact"),  # ios/android
        ("min_screen_inches", "screen_inches", "ratio"),
        ("camera_mp", "camera_mp", "ratio"),
    ],
}


def _detect_product_category(product: Dict[str, Any]) -> str:
    """Infer category from product metadata."""
    cat = str(product.get("category") or product.get("product_type") or "").lower()
    if cat in _CATEGORY_RANKING_DIMENSIONS:
        return cat
    # Heuristic fallback
    if product.get("ram_gb") or product.get("cpu"):
        return "laptop"
    if product.get("size") and product.get("material"):
        return "clothing"
    return "laptop"  # default


def _spec_match_score(
    product: Dict[str, Any],
    required_specs: Dict[str, Any],
) -> float:
    """Score how well a product matches required specs (0.0 - 1.0).

    Uses category-specific ranking dimensions when available.
    Each matched dimension contributes equally.  Over-spec gives full credit,
    under-spec is penalized proportionally.
    """
    if not required_specs:
        return 0.5  # neutral when no requirements

    category = _detect_product_category(product)
    dims = _CATEGORY_RANKING_DIMENSIONS.get(category, _CATEGORY_RANKING_DIMENSIONS["laptop"])

    dimensions = 0
    total = 0.0

    for spec_key, prod_key, mode in dims:
        req_val = required_specs.get(spec_key)
        prod_val = product.get(prod_key)
        if req_val is None:
            continue

        if mode == "ratio":
            if prod_val and req_val:
                try:
                    dimensions += 1
                    total += min(float(prod_val) / float(req_val), 1.0)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
        elif mode == "ratio_inverse":
            # Product value must be ≤ required (e.g., max width)
            if prod_val and req_val:
                try:
                    dimensions += 1
                    total += 1.0 if float(prod_val) <= float(req_val) else max(0.0, 1.0 - (float(prod_val) - float(req_val)) / float(req_val))
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
        elif mode == "exact":
            if prod_val:
                dimensions += 1
                total += 1.0 if str(prod_val).lower().strip() == str(req_val).lower().strip() else 0.2
        elif mode == "bool":
            dimensions += 1
            total += 1.0 if prod_val else 0.0

    if dimensions == 0:
        return 0.5
    return total / dimensions


def _budget_fit_score(
    price: Optional[float],
    budget_min: Optional[int],
    budget_max: Optional[int],
) -> float:
    """Score budget fit (0.0 - 1.0).  Perfect fit in range = 1.0."""
    if price is None:
        return 0.5
    if budget_min is not None and budget_max is not None:
        if budget_min <= price <= budget_max:
            return 1.0
        # Penalty for being out of range
        if price < budget_min:
            return max(0.0, 1.0 - (budget_min - price) / budget_min)
        return max(0.0, 1.0 - (price - budget_max) / budget_max)
    if budget_max is not None:
        return 1.0 if price <= budget_max else max(0.0, 1.0 - (price - budget_max) / budget_max)
    if budget_min is not None:
        return 1.0 if price >= budget_min else max(0.0, 1.0 - (budget_min - price) / budget_min)
    return 0.5


def _brand_preference_score(
    product: Dict[str, Any],
    brands_positive: List[str],
    brands_negative: List[str],
) -> float:
    """Score brand preference (0.0 - 1.0)."""
    brand = (product.get("brand") or "").lower().strip()
    if brand in [b.lower() for b in brands_negative]:
        return 0.0
    if not brands_positive:
        return 0.5
    if brand in [b.lower() for b in brands_positive]:
        return 1.0
    return 0.3  # neutral for unknown brands


def listwise_rerank(
    candidates: Sequence[Dict[str, Any]],
    required_specs: Optional[Dict[str, Any]] = None,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    brands_positive: Optional[List[str]] = None,
    brands_negative: Optional[List[str]] = None,
    prior_scores: Optional[Dict[str, float]] = None,
    max_per_diversity_group: int = 2,
    top_n: int = 5,
    weights: Optional[Dict[str, float]] = None,
    seasonal_boosts: Optional[Dict[str, float]] = None,
    use_case_priority_factors: Optional[List[str]] = None,
) -> List[RankedProduct]:
    """Listwise reranking of all candidates.

    Evaluates all candidates together, applies diversity enforcement, and
    generates contrastive WHY per selected product.

    Args:
        candidates: list of product dicts
        required_specs: hardware requirements from use-case / games / software
        budget_min/max: price range constraints
        brands_positive/negative: brand preferences
        prior_scores: optional existing scores from upstream pass (product_id → score)
        max_per_diversity_group: diversity cap per group
        top_n: how many to return
        weights: per-component weight overrides
        seasonal_boosts: optional dict of priority_factor → multiplier (e.g. {"portability": 1.2})
        use_case_priority_factors: priority factors for the active use-case (e.g. ["battery", "portability"])

    Returns: ranked list of RankedProduct with WHY explanations
    """
    w = {
        "spec_match": 0.35,
        "budget_fit": 0.25,
        "brand_pref": 0.10,
        "prior_score": 0.20,
        "diversity_bonus": 0.10,
        **(weights or {}),
    }

    scored: List[RankedProduct] = []
    for prod in candidates:
        pid = prod.get("product_id") or prod.get("id") or str(id(prod))
        price = prod.get("price")
        if isinstance(price, str):
            try:
                price = float(price.replace(",", "").replace("$", "").replace("£", "").replace("€", ""))
            except ValueError:
                price = None

        c_scores: Dict[str, float] = {}
        c_scores["spec_match"] = _spec_match_score(prod, required_specs or {})
        c_scores["budget_fit"] = _budget_fit_score(price, budget_min, budget_max)
        c_scores["brand_pref"] = _brand_preference_score(
            prod,
            brands_positive or [],
            brands_negative or [],
        )
        c_scores["prior_score"] = (prior_scores or {}).get(pid, 0.5)
        c_scores["diversity_bonus"] = 0.5  # placeholder, adjusted below

        total = sum(c_scores[k] * w.get(k, 0.0) for k in c_scores)

        scored.append(RankedProduct(
            product_id=pid,
            score=total,
            diversity_group=_extract_diversity_key(prod),
            component_scores=c_scores,
            raw=prod,
        ))

    # Sort by score descending
    scored.sort(key=lambda r: -r.score)

    # ── Diversity enforcement ──
    group_counts: Dict[str, int] = {}
    diverse_result: List[RankedProduct] = []
    deferred: List[RankedProduct] = []

    for rp in scored:
        count = group_counts.get(rp.diversity_group, 0)
        if count < max_per_diversity_group:
            group_counts[rp.diversity_group] = count + 1
            diverse_result.append(rp)
        else:
            # Penalize diversity score
            rp.component_scores["diversity_bonus"] = 0.0
            rp.score = sum(rp.component_scores[k] * w.get(k, 0.0) for k in rp.component_scores)
            deferred.append(rp)

    # Fill remaining slots from deferred if needed
    final = diverse_result[:top_n]
    if len(final) < top_n:
        deferred.sort(key=lambda r: -r.score)
        final.extend(deferred[: top_n - len(final)])

    # Assign ranks
    for i, rp in enumerate(final):
        rp.rank = i + 1

    # ── Seasonal boost ──
    # When seasonal_boosts and use_case_priority_factors are both provided,
    # apply a small score multiplier (capped at +12%) to each ranked product.
    # This is non-disruptive: it only nudges rankings, never overrides hard signals.
    if seasonal_boosts and use_case_priority_factors:
        overlap_boost = sum(
            float(seasonal_boosts.get(f, 1.0)) - 1.0
            for f in use_case_priority_factors
            if f in seasonal_boosts
        )
        n_factors = max(1, len(use_case_priority_factors))
        multiplier = 1.0 + min(0.12, max(0.0, overlap_boost / n_factors))
        if multiplier > 1.0:
            for rp in final:
                rp.score = round(rp.score * multiplier, 6)
            # Re-sort by boosted scores (may change relative order within final set)
            final.sort(key=lambda r: -r.score)
            for i, rp in enumerate(final):
                rp.rank = i + 1

    # ── Contrastive WHY + delta explanations (deterministic, spec-specific) ──
    # The #1 pick is the anchor; runners-up are explained by their ACTUAL spec deltas vs #1
    # ("why this one, not the top pick") rather than a generic phrase. No LLM call — the deltas
    # are already computed, so this is zero-latency and deterministic.
    if final:
        anchor = final[0]
        for rp in final[1:]:
            rp.delta_vs_anchor = compute_product_delta(anchor.raw, rp.raw)

        rejected = [r for r in scored if r not in final]
        if rejected:
            avg_rejected = {
                k: sum(r.component_scores.get(k, 0) for r in rejected) / len(rejected)
                for k in ("spec_match", "budget_fit", "brand_pref")
            }
        else:
            avg_rejected = {"spec_match": 0.5, "budget_fit": 0.5, "brand_pref": 0.5}

        for rp in final:
            brand = (rp.raw.get("brand") or "").strip()
            name = (rp.raw.get("name") or rp.raw.get("title") or rp.product_id).strip()
            label = f"{brand} {name}".strip()
            if rp.rank == 1:
                cs = rp.component_scores
                adv: List[str] = []
                if cs.get("spec_match", 0) > avg_rejected.get("spec_match", 0) + 0.1:
                    adv.append("the strongest spec match for your needs")
                if cs.get("budget_fit", 0) > avg_rejected.get("budget_fit", 0) + 0.1:
                    adv.append("the best value within your budget")
                if cs.get("brand_pref", 0) > avg_rejected.get("brand_pref", 0) + 0.1:
                    adv.append("your preferred brand")
                reason = "; ".join(adv[:2]) if adv else "the strongest overall score across your criteria"
                rp.contrastive_why = f"{label}: top pick — {reason}."
            else:
                salient = _salient_deltas(rp.delta_vs_anchor, k=2)
                if salient:
                    rp.contrastive_why = f"{label}: vs the top pick — {'; '.join(salient)}."
                else:
                    rp.contrastive_why = f"{label}: closely matches the top pick on the specs that matter."

    return final


# Decision-relevant delta dimensions, most→least salient for a one-line "why not #1" explanation.
_DELTA_SALIENCE = ("price", "gpu", "cpu", "ram", "refresh_rate", "storage", "display")


def _salient_deltas(deltas: Dict[str, str], k: int = 2) -> List[str]:
    """Pick the k most decision-relevant deltas, skipping 'Same'/'Similar' (no signal)."""
    out: List[str] = []
    for key in _DELTA_SALIENCE:
        d = (deltas or {}).get(key)
        if d and not d.lower().startswith(("same", "similar")):
            out.append(d)
        if len(out) >= k:
            break
    return out


def compute_product_delta(
    anchor: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, str]:
    """Compute human-readable spec deltas between anchor and candidate products.

    Returns a dict of dimension → description like:
      {"ram": "Same 16GB", "price": "42% cheaper ($599 vs $1,039)", "gpu": "Lower tier GPU"}
    """
    deltas: Dict[str, str] = {}

    # Price
    try:
        a_price = _parse_price(anchor.get("price"))
        c_price = _parse_price(candidate.get("price"))
        if a_price is not None and c_price is not None and a_price > 0:
            pct = ((c_price - a_price) / a_price) * 100
            if abs(pct) < 3:
                deltas["price"] = f"Similar price (${c_price:,.0f})"
            elif pct < 0:
                deltas["price"] = f"{abs(pct):.0f}% cheaper (${c_price:,.0f} vs ${a_price:,.0f})"
            else:
                deltas["price"] = f"{pct:.0f}% more expensive (${c_price:,.0f} vs ${a_price:,.0f})"
    except Exception:
        pass

    # RAM
    try:
        a_ram = int(anchor.get("ram_gb") or 0)
        c_ram = int(candidate.get("ram_gb") or 0)
        if a_ram and c_ram:
            if a_ram == c_ram:
                deltas["ram"] = f"Same {c_ram}GB RAM"
            elif c_ram > a_ram:
                deltas["ram"] = f"{c_ram - a_ram}GB more RAM ({c_ram}GB vs {a_ram}GB)"
            else:
                deltas["ram"] = f"{a_ram - c_ram}GB less RAM ({c_ram}GB vs {a_ram}GB)"
    except Exception:
        pass

    # Storage
    try:
        a_stor = int(anchor.get("storage_gb") or 0)
        c_stor = int(candidate.get("storage_gb") or 0)
        if a_stor and c_stor:
            if a_stor == c_stor:
                deltas["storage"] = f"Same {c_stor}GB storage"
            elif c_stor > a_stor:
                deltas["storage"] = f"Larger storage ({c_stor}GB vs {a_stor}GB)"
            else:
                deltas["storage"] = f"Smaller storage ({c_stor}GB vs {a_stor}GB)"
    except Exception:
        pass

    # CPU tier comparison
    try:
        a_cpu = (anchor.get("cpu_family") or anchor.get("cpu") or "").strip()
        c_cpu = (candidate.get("cpu_family") or candidate.get("cpu") or "").strip()
        if a_cpu and c_cpu:
            if a_cpu.lower() == c_cpu.lower():
                deltas["cpu"] = f"Same CPU ({c_cpu})"
            else:
                deltas["cpu"] = f"Different CPU ({c_cpu} vs {a_cpu})"
    except Exception:
        pass

    # GPU
    try:
        a_gpu = bool(anchor.get("has_dedicated_gpu"))
        c_gpu = bool(candidate.get("has_dedicated_gpu"))
        a_vram = int(anchor.get("gpu_vram_gb") or 0)
        c_vram = int(candidate.get("gpu_vram_gb") or 0)
        if a_gpu and c_gpu:
            if a_vram == c_vram:
                deltas["gpu"] = f"Same GPU tier ({c_vram}GB VRAM)"
            elif c_vram > a_vram:
                deltas["gpu"] = f"Higher GPU ({c_vram}GB vs {a_vram}GB VRAM)"
            else:
                deltas["gpu"] = f"Lower GPU ({c_vram}GB vs {a_vram}GB VRAM)"
        elif a_gpu and not c_gpu:
            deltas["gpu"] = "No dedicated GPU (integrated only)"
        elif not a_gpu and c_gpu:
            deltas["gpu"] = f"Has dedicated GPU ({c_vram}GB VRAM)"
    except Exception:
        pass

    # Display
    try:
        a_disp = float(anchor.get("display_inches") or 0)
        c_disp = float(candidate.get("display_inches") or 0)
        if a_disp and c_disp:
            if abs(a_disp - c_disp) < 0.3:
                deltas["display"] = f"Similar display ({c_disp}\")"
            elif c_disp > a_disp:
                deltas["display"] = f"Larger display ({c_disp}\" vs {a_disp}\")"
            else:
                deltas["display"] = f"Smaller display ({c_disp}\" vs {a_disp}\")"
    except Exception:
        pass

    # Refresh rate
    try:
        a_hz = int(anchor.get("refresh_hz") or 0)
        c_hz = int(candidate.get("refresh_hz") or 0)
        if a_hz and c_hz:
            if a_hz == c_hz:
                deltas["refresh_rate"] = f"Same {c_hz}Hz"
            elif c_hz > a_hz:
                deltas["refresh_rate"] = f"Higher refresh ({c_hz}Hz vs {a_hz}Hz)"
            else:
                deltas["refresh_rate"] = f"Lower refresh ({c_hz}Hz vs {a_hz}Hz)"
    except Exception:
        pass

    return deltas


def _parse_price(val: Any) -> Optional[float]:
    """Parse a price value that may be string or numeric."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("£", "").replace("€", ""))
    except (ValueError, TypeError):
        return None


def build_contrastive_explanations(
    scored: List[Dict[str, Any]],
    *,
    required_specs: Optional[Dict[str, Any]] = None,
    budget_min: Any = None,
    budget_max: Any = None,
    brands_positive: Optional[List[str]] = None,
    brands_negative: Optional[List[str]] = None,
    top_n: int = 12,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Build {sku: contrastive_why} + {sku: delta_vs_anchor} for the top-N via listwise_rerank.

    Normalizes each scored candidate into a rank input (product_id + dollar price), runs the listwise
    reranker for its human-facing explanations, and maps them by SKU. Returns ({}, {}) on any failure
    so the route degrades to no-explanations rather than erroring. Pure (no I/O)."""
    why_by_sku: Dict[str, str] = {}
    delta_by_sku: Dict[str, Dict[str, str]] = {}
    try:
        rank_inputs: List[Dict[str, Any]] = []
        for it in (scored or []):
            cand = dict((it or {}).get("candidate") or {})
            cand["product_id"] = cand.get("sku") or cand.get("product_id") or cand.get("id")
            if cand.get("price") is None and cand.get("price_cents") is not None:
                try:
                    cand["price"] = cents_to_dollars(cand.get("price_cents"))
                except Exception:
                    pass
            rank_inputs.append(cand)
        ranked = listwise_rerank(
            rank_inputs,
            required_specs=required_specs or {},
            budget_min=budget_min,
            budget_max=budget_max,
            brands_positive=brands_positive or [],
            brands_negative=brands_negative or [],
            top_n=min(int(top_n), len(rank_inputs) or int(top_n)),
        )
        for rp in (ranked or []):
            sku = str((rp.raw or {}).get("sku") or rp.product_id or "")
            if not sku:
                continue
            why_by_sku[sku] = str(rp.contrastive_why or "")
            delta_by_sku[sku] = dict(rp.delta_vs_anchor or {})
    except Exception:
        return {}, {}
    return why_by_sku, delta_by_sku
