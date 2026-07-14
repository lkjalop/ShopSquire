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
    "classified_shown_rate_min": 0.98,     # review-9-followup #A3: shown products carrying an
    #                                        approved classification (onboarding coverage gate)
    "p95_latency_ms_max": 8000.0,          # V2 (GPT-5.6 review-11b): reliability gate — the replay
    "timeout_rate_max": 0.01,              #   had 34-35s cases + a model timeout; promotion needs p95
    #                                        under 8s and model-timeout/fallback under 1%.
}


def load_labels(path: Optional[Path] = None) -> Dict[str, Any]:
    """The sealed relevance-label set. Schema (validated):
        {"cases": {"<case:turn>": {"labels": {"<sku>": grade0-2}}}, "split": {"dev": [...], "test": [...]}}
    Grades: 2 = highly relevant, 1 = acceptable, 0 = irrelevant. A malformed file is reported LOUDLY
    (the gate then fails on zero coverage) rather than silently treated as 'no labels'."""
    p = path or _LABELS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("relevance labels unavailable (%s): %s", p, repr(exc)[:80])
        return {}
    if not isinstance(data, dict):
        return {}
    problems = validate_labels(data)
    if problems:
        logger.warning("relevance_labels.json has %d schema problem(s): %s",
                       len(problems), "; ".join(problems[:6]))
    return data


def validate_labels(labels: Dict[str, Any]) -> List[str]:
    """Structural validation → list of problems (empty = clean). Grades must be 0/1/2; every split
    key must reference a real case; a case in a split must carry labels. Enforces the ONE schema."""
    problems: List[str] = []
    cases = labels.get("cases")
    if cases is not None and not isinstance(cases, dict):
        return ["'cases' must be an object"]
    cases = cases or {}
    for cid, entry in cases.items():
        lab = (entry or {}).get("labels") if isinstance(entry, dict) else None
        if not isinstance(lab, dict) or not lab:
            problems.append(f"case '{cid}': missing 'labels' object")
            continue
        for sku, grade in lab.items():
            try:
                if int(grade) not in (0, 1, 2):
                    problems.append(f"case '{cid}' sku '{sku}': grade {grade} not in 0..2")
            except (TypeError, ValueError):
                problems.append(f"case '{cid}' sku '{sku}': grade {grade!r} not an int")
    split = labels.get("split") or {}
    if not isinstance(split, dict):
        problems.append("'split' must be an object with 'dev'/'test' key lists")
    else:
        for name in ("dev", "test"):
            for cid in (split.get(name) or []):
                if str(cid) not in cases:
                    problems.append(f"split.{name} references unknown case '{cid}'")
    return problems


def _split_keys(labels: Dict[str, Any], split: Optional[str]) -> Optional[set]:
    """The set of case keys in `split` ('dev'|'test'), or None to accept ALL labeled cases."""
    if not split:
        return None
    return {str(k) for k in ((labels.get("split") or {}).get(split) or [])}


def case_labels(labels: Dict[str, Any], case_id: str,
                split: Optional[str] = None) -> Optional[Dict[str, int]]:
    """Graded labels for a case — but ONLY if it belongs to `split` when one is given (so a `dev`
    label can never leak into the sealed `test` gate). split=None keeps the all-cases behaviour."""
    keys = _split_keys(labels, split)
    if keys is not None and str(case_id) not in keys:
        return None
    entry = ((labels.get("cases") or {}).get(str(case_id)) or {})
    lab = entry.get("labels")
    if not isinstance(lab, dict) or not lab:
        return None
    try:
        return {str(k): int(v) for k, v in lab.items()}
    except (TypeError, ValueError):
        return None


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

def catalog_authorization(db, shown_skus: List[str], *,
                          tenant_id: str = "default") -> Dict[str, Any]:
    """SERVER-SIDE authorization + classification-coverage check (review-9 #2, review-9-followup
    #A1/#A3). Each SHOWN sku must (a) exist, (b) be active, (c) not sit in a taxonomy node the
    tenant EXPLICITLY does not sell. Returns:
      {violations, measured, shown, classified} where
      - measured=False when the DB read FAILS — a broken measurement must FAIL the gate, never
        read as clean (the promotion-gate honesty rule; fail-CLOSED, not fail-open);
      - classified = count of shown skus with an approved classification (coverage is a SEPARATE
        gate — an unclassified but real+active product is NOT an authorization violation)."""
    out = {"violations": 0, "measured": True, "shown": len(shown_skus), "classified": 0}
    if not shown_skus:
        return out
    if db is None:
        out["measured"] = False
        return out
    try:
        from sqlalchemy import text as _t
        params = {f"s{i}": s for i, s in enumerate(shown_skus)}
        ph = ", ".join(f":{k}" for k in params)
        rows = db.execute(_t(f"SELECT sku, COALESCE(active,1) FROM products WHERE sku IN ({ph})"),
                          params).fetchall()
        found = {str(r[0]): bool(r[1]) for r in rows}
        v = sum(1 for s in shown_skus if s not in found)          # phantom sku
        v += sum(1 for s in shown_skus if found.get(s) is False)  # inactive shown
        from src.app.services.taxonomy_registry import sells_within
        cls = db.execute(_t(
            f"SELECT sku, node_handle FROM product_classification "
            f"WHERE sku IN ({ph}) AND tenant_id = :t AND status = 'approved'"),
            {**params, "t": str(tenant_id)}).fetchall()
        classified = {str(sku) for sku, _ in cls}
        for sku, node in cls:
            if sells_within(db, str(node), tenant_id=str(tenant_id)) is False:
                v += 1                                             # explicitly-unsold node
        out["violations"] = v
        out["classified"] = len(classified & set(shown_skus))
        return out
    except Exception as exc:
        logger.debug("catalog authorization UNREADABLE (gate must fail-closed): %s", repr(exc)[:80])
        out["measured"] = False
        return out


def catalog_authorization_violations(db, shown_skus: List[str], *,
                                     tenant_id: str = "default") -> int:
    """Back-compat shim (count only). Prefer catalog_authorization() for the measured flag."""
    return catalog_authorization(db, shown_skus, tenant_id=tenant_id)["violations"]


def evaluate_case_quality(case: Dict[str, Any], response: Dict[str, Any],
                          labels: Optional[Dict[str, Any]] = None,
                          catalog: Optional[Dict[str, Any]] = None,
                          catalog_violations: int = 0,
                          split: Optional[str] = None,
                          latency_ms: Optional[float] = None,
                          timed_out: bool = False) -> Dict[str, Any]:
    """One case's quality row. `case` needs: id; optional budget_max (dollars), expects_products
    (default True for SEARCH-ish cases; False for refusal/clarify-expected cases).
    `response` is the v2 legacy-shape payload (products: [{sku, price, brand, workload_fit}]).
    catalog = the SERVER-SIDE authorization result from catalog_authorization() (the caller holds
    the db): {violations, measured, shown, classified}. `catalog_violations` is the legacy
    count-only arg (still honored). unauthorized_rate is the honest COMPOSITE of payload + server
    checks; an UNMEASURED authorization (catalog.measured=False) fails the gate."""
    products = [p for p in (response.get("products") or []) if isinstance(p, dict)]
    shown = [str(p.get("sku")) for p in products if p.get("sku")]
    expects = bool(case.get("expects_products", True))
    cat = catalog or {"violations": catalog_violations, "measured": True,
                      "shown": len(shown), "classified": len(shown)}

    row: Dict[str, Any] = {"case_id": str(case.get("id") or ""), "shown": len(shown),
                           "expects_products": expects, "empty": expects and not shown,
                           "catalog_measured": bool(cat.get("measured", True)),
                           "shown_classified": int(cat.get("classified", 0)),
                           "latency_ms": (float(latency_ms) if latency_ms is not None else None),
                           "timed_out": bool(timed_out)}

    # PAYLOAD violations (review-6 #18): over-budget shown products and duplicate SKUs — the two
    # things measurable from the payload alone. Tenant/active/sold-taxonomy live in the SERVER-
    # SIDE check (catalog_authorization_violations, review-9 #2) whose count arrives via
    # catalog_violations; row["unauthorized"] is the honest composite of both. A missing/
    # unparseable price when a budget is set counts as a violation — an unverifiable price is
    # not "in budget" (was silently treated as 0 and evaded the check).
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
    row["payload_violations"] = violations
    row["catalog_violations"] = max(0, int(cat.get("violations", catalog_violations)))
    row["unauthorized"] = violations + row["catalog_violations"]   # the composite the gate reads

    # constraint satisfaction over verdict-carrying products (fit rides each card)
    verdicts = [str((p.get("workload_fit") or {}).get("overall") or "")
                for p in products if isinstance(p.get("workload_fit"), dict)]
    row["verdict_count"] = len(verdicts)
    row["meets_count"] = sum(1 for v in verdicts if v == "meets")
    row["fails_shown"] = sum(1 for v in verdicts if v == "fails")

    # diversity: distinct-brand share of the shown slate (1.0 when brands unknown → no signal)
    brands = [str(p.get("brand") or "").lower() for p in products if p.get("brand")]
    row["diversity"] = round(len(set(brands)) / len(brands), 4) if brands else None

    # labeled metrics, only where the sealed set covers this case IN THE GATED SPLIT (dev labels
    # never leak into the test gate — GPT-5.6 review-11b: the split was previously not enforced).
    lab = case_labels(labels or {}, row["case_id"], split=split) if labels else None
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
    # SERVER-SIDE authorization honesty (review-9-followup #A1): if ANY shown-slate authorization
    # was UNMEASURED (DB unreadable), the gate must fail — a broken check can't read as clean.
    authz_unmeasured = sum(1 for r in rows if r.get("shown", 0) and r.get("catalog_measured") is False)
    # classification coverage (review-9-followup #A3): a SEPARATE gate from authorization —
    # of shown products, the share carrying an approved classification (unclassified ≠ unauthorized).
    classified_shown = sum(r.get("shown_classified", 0) for r in rows)
    classified_shown_rate = (classified_shown / shown_total) if shown_total else None
    # coverage arithmetic (review-6 #19): numerator and denominator must be the SAME population —
    # labeled PRODUCT-EXPECTED cases over product-expected cases. Counting a labeled refusal case
    # in the numerator inflated coverage.
    labeled = [r for r in rows if r.get("labeled") and r.get("expects_products")]
    labeled_coverage = len(labeled) / n_exp
    precision = (sum(r["precision_at_10"] for r in labeled) / len(labeled)) if labeled else None
    ndcg = (sum(r["ndcg_at_10"] for r in labeled) / len(labeled)) if labeled else None
    # V2 reliability (GPT-5.6): p95 latency + model-timeout rate over the run.
    lats = sorted(float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None)
    p95_latency = lats[max(0, math.ceil(0.95 * len(lats)) - 1)] if lats else None
    timeout_rate = (sum(1 for r in rows if r.get("timed_out")) / len(rows)) if rows else 0.0

    failures: List[str] = []
    if empty_rate > th["empty_rate_max"]:
        failures.append(f"empty_rate {empty_rate:.3f} > {th['empty_rate_max']}")
    if unauthorized_rate > th["unauthorized_rate_max"]:
        failures.append(f"unauthorized_rate {unauthorized_rate:.4f} > {th['unauthorized_rate_max']}")
    if authz_unmeasured:
        failures.append(f"catalog_authorization UNMEASURED on {authz_unmeasured} case(s) "
                        f"(a broken authorization check fails the gate, never reads clean)")
    if classified_shown_rate is not None and classified_shown_rate < th["classified_shown_rate_min"]:
        failures.append(f"classified_shown_rate {classified_shown_rate:.3f} < "
                        f"{th['classified_shown_rate_min']} (onboarding coverage gap)")
    if constraint_sat is not None and constraint_sat < th["constraint_satisfaction_min"]:
        failures.append(f"constraint_satisfaction {constraint_sat:.3f} < {th['constraint_satisfaction_min']}")
    if diversity is not None and diversity < th["diversity_min"]:
        failures.append(f"diversity {diversity:.3f} < {th['diversity_min']}")
    if p95_latency is not None and p95_latency > th["p95_latency_ms_max"]:
        failures.append(f"p95_latency {p95_latency:.0f}ms > {th['p95_latency_ms_max']:.0f}ms")
    if timeout_rate > th["timeout_rate_max"]:
        failures.append(f"timeout_rate {timeout_rate:.3f} > {th['timeout_rate_max']}")
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
            "authz_unmeasured_cases": authz_unmeasured,
            "classified_shown_rate": (round(classified_shown_rate, 4)
                                      if classified_shown_rate is not None else None),
            "p95_latency_ms": (round(p95_latency, 1) if p95_latency is not None else None),
            "timeout_rate": round(timeout_rate, 4),
            "thresholds": th,
            "gates": {"pass": not failures, "failures": failures}}
