"""Intrinsic quality gate (M2-B2 — GPT-5.6 review-4 #1 / spec B2).

Until now `gates_pass` measured parity and honesty but NOTHING about whether the products are
GOOD — a known_wrong workload case "passed" while returning zero products. This is the missing
gate: v2-intrinsic metrics over a run, thresholded, wired into summarize_run so a promotion
can not happen on safe-but-useless output.

Two metric families, honestly separated:
  LABEL-FREE (computed on EVERY case): constraint-satisfaction rate, empty-rate,
    unauthorized-product-rate (budget violations, duplicate SKUs), brand diversity.
  LABELED (computed only where a human-sealed relevance label exists): precision@10 and
    NDCG@10 — graded relevance from tests/golden/relevance_labels.json. Labels are DATA,
    reviewed like the taxonomy: this module never invents ground truth, and the gate
    HONESTLY FAILS on insufficient label coverage instead of passing vacuously (a gate that
    silently skips its hardest metric is the mute-layer class).

Precision alone is gameable (return ONE safe product → 1.0): the gate therefore also
requires NDCG (rank-aware, graded) and bounds empty-rate — returning almost nothing cannot
score well. Vertical-blind: SKUs, grades, cents; no product vocabulary."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shopsquire.recommendation_core.quality")

_LABELS_PATH = Path(__file__).resolve().parents[4] / "tests" / "golden" / "relevance_labels.json"

# Promotion thresholds — reviewed as data; ratchet UP as the corpus grows, never down to pass.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "precision_at_10_min": 0.60,
    "ndcg_at_10_min": 0.60,
    "constraint_satisfaction_min": 0.70,   # of verdict-carrying shown products, meets-share
    "empty_rate_max": 0.15,                # product-expected cases returning zero products
    "unauthorized_rate_max": 0.0,          # over-budget/duplicate SKUs shown: NEVER acceptable
    "diversity_min": 0.30,                 # distinct-brand share in shown sets (degenerate-slate guard)
    "labeled_coverage_min": 0.30,          # share of product-expected cases carrying labels
}


def load_labels(path: Optional[Path] = None) -> Dict[str, Any]:
    """The sealed relevance-label set: {case_id: {sku: grade}} with a dev/test split.
    Grades: 2 = highly relevant, 1 = acceptable, 0 = irrelevant (explicit negative)."""
    p = path or _LABELS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("relevance labels unavailable (%s): %s", p, repr(exc)[:80])
        return {}


def case_labels(labels: Dict[str, Any], case_id: str) -> Optional[Dict[str, int]]:
    entry = ((labels.get("cases") or {}).get(str(case_id)) or {})
    lab = entry.get("labels")
    if not isinstance(lab, dict) or not lab:
        return None
    return {str(k): int(v) for k, v in lab.items()}


# ── labeled metrics ──────────────────────────────────────────────────────────────

def precision_at_k(shown_skus: List[str], lab: Dict[str, int], k: int = 10) -> float:
    """Share of the top-k shown that are relevant (grade ≥ 1). Unlabeled shown SKUs count as
    NOT relevant — the label set must cover the case's plausible slate (sealed-data duty)."""
    top = [s for s in shown_skus[:k]]
    if not top:
        return 0.0
    return sum(1 for s in top if lab.get(s, 0) >= 1) / len(top)


def ndcg_at_k(shown_skus: List[str], lab: Dict[str, int], k: int = 10) -> float:
    """Graded, rank-aware: DCG over the shown order / ideal DCG over the label set. The
    anti-gaming metric — one safe-but-irrelevant product scores ~0 here."""
    def dcg(grades: List[int]) -> float:
        return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))
    got = dcg([lab.get(s, 0) for s in shown_skus[:k]])
    ideal = dcg(sorted(lab.values(), reverse=True)[:k])
    return round(got / ideal, 4) if ideal > 0 else 0.0


# ── per-case evaluation ──────────────────────────────────────────────────────────

def evaluate_case_quality(case: Dict[str, Any], response: Dict[str, Any],
                          labels: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One case's quality row. `case` needs: id; optional budget_max (dollars), expects_products
    (default True for SEARCH-ish cases; False for refusal/clarify-expected cases).
    `response` is the v2 legacy-shape payload (products: [{sku, price, brand, workload_fit}])."""
    products = [p for p in (response.get("products") or []) if isinstance(p, dict)]
    shown = [str(p.get("sku")) for p in products if p.get("sku")]
    expects = bool(case.get("expects_products", True))

    row: Dict[str, Any] = {"case_id": str(case.get("id") or ""), "shown": len(shown),
                           "expects_products": expects, "empty": expects and not shown}

    # budget/duplicate violations (review-6 #18 — HONEST scope: this metric checks the two
    # things measurable from the payload — over-budget shown products and duplicate SKUs. It does
    # NOT verify tenant / active-status / sold-taxonomy / catalog provenance; those are a
    # per-product server-side authorization check tracked as a follow-up. A missing/unparseable
    # price when a budget is set counts as a violation — an unverifiable price is not "in budget"
    # (was silently treated as 0 and evaded the check).
    violations = 0
    budget_max = case.get("budget_max")
    if budget_max is not None:
        for p in products:
            raw = p.get("price")
            try:
                price = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                price = None
            if price is None or price > float(budget_max) + 1e-9:
                violations += 1
    dupes = len(shown) - len(set(shown))
    violations += max(0, dupes)
    row["unauthorized"] = violations   # key kept (gate threshold) — see honest scope above

    # constraint satisfaction over verdict-carrying products (fit rides each card)
    verdicts = [str((p.get("workload_fit") or {}).get("overall") or "")
                for p in products if isinstance(p.get("workload_fit"), dict)]
    row["verdict_count"] = len(verdicts)
    row["meets_count"] = sum(1 for v in verdicts if v == "meets")
    row["fails_shown"] = sum(1 for v in verdicts if v == "fails")

    # diversity: distinct-brand share of the shown slate (1.0 when brands unknown → no signal)
    brands = [str(p.get("brand") or "").lower() for p in products if p.get("brand")]
    row["diversity"] = round(len(set(brands)) / len(brands), 4) if brands else None

    # labeled metrics, only where the sealed set covers this case
    lab = case_labels(labels or {}, row["case_id"]) if labels else None
    row["labeled"] = lab is not None
    if lab is not None:
        row["precision_at_10"] = round(precision_at_k(shown, lab), 4)
        row["ndcg_at_10"] = ndcg_at_k(shown, lab)
    return row


# ── run-level rollup + the gate ──────────────────────────────────────────────────

def summarize_quality(rows: List[Dict[str, Any]],
                      thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Aggregate a run's quality rows and apply the promotion thresholds. The gate FAILS
    honestly when labeled coverage is below the floor — 'could not measure relevance' must
    never read as 'relevance is fine'."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    expected = [r for r in rows if r.get("expects_products")]
    n_exp = max(1, len(expected))
    empty_rate = sum(1 for r in expected if r.get("empty")) / n_exp
    shown_total = sum(r.get("shown", 0) for r in rows)
    unauthorized_rate = (sum(r.get("unauthorized", 0) for r in rows) / shown_total
                         if shown_total else 0.0)
    verdict_total = sum(r.get("verdict_count", 0) for r in rows)
    constraint_sat = (sum(r.get("meets_count", 0) for r in rows) / verdict_total
                      if verdict_total else None)
    diversities = [r["diversity"] for r in rows if r.get("diversity") is not None]
    diversity = sum(diversities) / len(diversities) if diversities else None
    # coverage arithmetic (review-6 #19): numerator and denominator must be the SAME population —
    # labeled PRODUCT-EXPECTED cases over product-expected cases. Counting a labeled refusal case
    # in the numerator inflated coverage.
    labeled = [r for r in rows if r.get("labeled") and r.get("expects_products")]
    labeled_coverage = len(labeled) / n_exp
    precision = (sum(r["precision_at_10"] for r in labeled) / len(labeled)) if labeled else None
    ndcg = (sum(r["ndcg_at_10"] for r in labeled) / len(labeled)) if labeled else None

    failures: List[str] = []
    if empty_rate > th["empty_rate_max"]:
        failures.append(f"empty_rate {empty_rate:.3f} > {th['empty_rate_max']}")
    if unauthorized_rate > th["unauthorized_rate_max"]:
        failures.append(f"unauthorized_rate {unauthorized_rate:.4f} > {th['unauthorized_rate_max']}")
    if constraint_sat is not None and constraint_sat < th["constraint_satisfaction_min"]:
        failures.append(f"constraint_satisfaction {constraint_sat:.3f} < {th['constraint_satisfaction_min']}")
    if diversity is not None and diversity < th["diversity_min"]:
        failures.append(f"diversity {diversity:.3f} < {th['diversity_min']}")
    if labeled_coverage < th["labeled_coverage_min"]:
        failures.append(f"labeled_coverage {labeled_coverage:.3f} < {th['labeled_coverage_min']} "
                        f"(relevance UNMEASURED is a failure, not a pass)")
    else:
        if precision is not None and precision < th["precision_at_10_min"]:
            failures.append(f"precision@10 {precision:.3f} < {th['precision_at_10_min']}")
        if ndcg is not None and ndcg < th["ndcg_at_10_min"]:
            failures.append(f"ndcg@10 {ndcg:.3f} < {th['ndcg_at_10_min']}")

    return {"cases": len(rows), "product_expected_cases": len(expected),
            "empty_rate": round(empty_rate, 4), "unauthorized_rate": round(unauthorized_rate, 4),
            "constraint_satisfaction": (round(constraint_sat, 4) if constraint_sat is not None else None),
            "diversity": (round(diversity, 4) if diversity is not None else None),
            "labeled_cases": len(labeled), "labeled_coverage": round(labeled_coverage, 4),
            "precision_at_10": (round(precision, 4) if precision is not None else None),
            "ndcg_at_10": (round(ndcg, 4) if ndcg is not None else None),
            "thresholds": th,
            "gates": {"pass": not failures, "failures": failures}}
