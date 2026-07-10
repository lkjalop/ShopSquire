"""Full-response parity differ (V2 Phase 0) — extends the recommend_retrieval_metrics
pattern from "candidate lists" to the WHOLE /suggest payload.

Purpose: given a legacy-suggest() response and a recommendation_core (V2) response for the
same request, classify their divergence so shadow/canary promotion is a MEASURED decision
(roadmap Phase 5 gates: message-class match >=98%, product-set Jaccard >=0.9, zero
security/gate regressions).

Design rules:
  - Pure functions, no I/O — runnable offline over recorded corpus files.
  - Compare MEANING, not prose: LLM narration text varies run-to-run, so message
    comparison is by CLASS (refusal / off-catalog / clarify / answer / empty), never bytes.
  - Every dimension yields {match: bool, detail}; the roll-up assigns a severity so a
    shadow run can histogram divergences by class.

Severity ladder:
  BLOCKER — a safety/honesty regression (off-catalog verdict flip, refusal dropped,
            security route change, products shown where v1 refused).
  MAJOR   — user-visible outcome change (message class, product set beyond tolerance,
            clarify-vs-answer flip).
  MINOR   — same outcome, different furniture (right_panel keys, tier split, field drift).
  INFO    — expected nondeterminism (trace ids, timings, watermarks, job ids).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Fields whose values are EXPECTED to differ between any two runs (identity, timing,
# watermarking, async job handles). The structure differ ignores value drift here.
NONDETERMINISTIC_FIELDS = frozenset({
    "trace_id", "decision_id", "decision_trace_id", "llm_summary_job_id",
    "model_output_fingerprint", "model_watermark", "timing_breakdown", "risk_score",
    "confidence_calibrated", "_trace_recommendation_persisted", "learn_more_url",
    "hippograph_insights_shadow", "hippograph_shadow_counterfactual", "session_summary",
    "storefront_emphasis", "sales_response_nudge", "trace_tags", "source_statuses",
})


def message_class(payload: Dict[str, Any]) -> str:
    """Collapse a response to its user-outcome class. Prose varies; the CLASS must not."""
    if not isinstance(payload, dict):
        return "invalid"
    if payload.get("off_catalog"):
        return "off_catalog"
    if payload.get("refusal_note"):
        return "refusal"
    products = payload.get("products") or []
    msg = str(payload.get("assistant_message") or payload.get("message") or "").strip()
    if not products:
        if payload.get("needs_disambiguation") and payload.get("next_questions"):
            return "clarify_no_products"
        return "no_results" if msg else "empty"
    if payload.get("needs_disambiguation") and payload.get("next_questions"):
        return "answer_with_clarify"
    return "answer"


def _sku_list(payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for p in payload.get("products") or []:
        if isinstance(p, dict):
            sku = p.get("sku") or p.get("id") or p.get("SKU")
            if sku:
                out.append(str(sku))
    return out


def product_set_diff(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    sa, sb = _sku_list(a), _sku_list(b)
    set_a, set_b = set(sa), set(sb)
    union = set_a | set_b
    jaccard = (len(set_a & set_b) / len(union)) if union else 1.0
    return {
        "match": set_a == set_b,
        "jaccard": round(jaccard, 3),
        "top3_match": sa[:3] == sb[:3],
        "only_a": sorted(set_a - set_b)[:10],
        "only_b": sorted(set_b - set_a)[:10],
        "count_a": len(sa),
        "count_b": len(sb),
    }


def _gate_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The safety-relevant slice: everything here diverging is a BLOCKER candidate."""
    sec = payload.get("security") or {}
    oc = payload.get("off_catalog") or None
    return {
        "off_catalog_class": (oc or {}).get("class") if isinstance(oc, dict) else None,
        "off_catalog_set": bool(oc),
        "refusal": bool(payload.get("refusal_note")),
        "policy_route": (sec.get("policy_route") if isinstance(sec, dict) else None),
        "image_untrusted": (sec.get("image_untrusted") if isinstance(sec, dict) else None),
        "autonomy_tier": payload.get("autonomy_tier"),
        "escalation": bool(payload.get("escalation")),
        "degraded": bool(payload.get("degraded")),
        "products_despite_refusal": bool(oc) and bool(payload.get("products")),
    }


def structure_diff(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    ka, kb = set(a or {}), set(b or {})
    return {
        "match": ka == kb,
        "only_a": sorted(ka - kb)[:20],
        "only_b": sorted(kb - ka)[:20],
    }


def diff_responses(v1: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two /suggest payloads for the SAME request. v1 = legacy oracle, v2 = candidate.
    Returns {severity, dimensions:{...}} — severity is the worst non-matching dimension."""
    v1, v2 = v1 or {}, v2 or {}

    mc1, mc2 = message_class(v1), message_class(v2)
    dims: Dict[str, Dict[str, Any]] = {}

    g1, g2 = _gate_view(v1), _gate_view(v2)
    dims["gates"] = {"match": g1 == g2, "v1": g1, "v2": g2, "severity": "BLOCKER"}

    dims["message_class"] = {"match": mc1 == mc2, "v1": mc1, "v2": mc2, "severity": "MAJOR"}

    ps = product_set_diff(v1, v2)
    # tolerance: identical sets ideal; jaccard >= 0.9 with same top-3 counts as MINOR drift
    ps["severity"] = "MAJOR" if (ps["jaccard"] < 0.9 or not ps["top3_match"]) else "MINOR"
    ps_match = ps["match"]
    dims["product_set"] = {**ps, "match": ps_match}

    dims["turn"] = {
        "match": (v1.get("turn_intent") == v2.get("turn_intent")
                  and bool(v1.get("needs_disambiguation")) == bool(v2.get("needs_disambiguation"))),
        "v1": {"intent": v1.get("turn_intent"), "clarify": bool(v1.get("needs_disambiguation"))},
        "v2": {"intent": v2.get("turn_intent"), "clarify": bool(v2.get("needs_disambiguation"))},
        "severity": "MAJOR",
    }

    wf1, wf2 = v1.get("workload_fit") or {}, v2.get("workload_fit") or {}
    dims["workload"] = {
        "match": (wf1.get("floors") == wf2.get("floors")
                  and len(wf1.get("verdicts") or []) == len(wf2.get("verdicts") or [])),
        "severity": "MAJOR",
    }

    rp1, rp2 = v1.get("right_panel") or {}, v2.get("right_panel") or {}
    dims["right_panel"] = {
        "match": set(rp1) == set(rp2) and rp1.get("mode") == rp2.get("mode"),
        "only_v1": sorted(set(rp1) - set(rp2))[:10],
        "only_v2": sorted(set(rp2) - set(rp1))[:10],
        "severity": "MINOR",
    }

    sd = structure_diff(
        {k: 1 for k in v1 if k not in NONDETERMINISTIC_FIELDS},
        {k: 1 for k in v2 if k not in NONDETERMINISTIC_FIELDS},
    )
    dims["structure"] = {**sd, "severity": "MINOR"}

    order = {"BLOCKER": 3, "MAJOR": 2, "MINOR": 1, "INFO": 0}
    worst = "INFO"
    for d in dims.values():
        if not d.get("match") and order[d["severity"]] > order[worst]:
            worst = d["severity"]
    return {"severity": worst, "identical_outcome": all(d.get("match") for d in dims.values()),
            "dimensions": dims}


def summarize_run(diffs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll a shadow run's per-request diffs into the promotion-gate scorecard."""
    n = max(1, len(diffs))
    by_sev: Dict[str, int] = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0, "INFO": 0}
    mc_match = ps_ok = gate_match = 0
    for d in diffs:
        by_sev[d.get("severity", "INFO")] = by_sev.get(d.get("severity", "INFO"), 0) + 1
        dims = d.get("dimensions", {})
        if dims.get("message_class", {}).get("match"):
            mc_match += 1
        ps = dims.get("product_set", {})
        if ps.get("match") or (ps.get("jaccard", 0) >= 0.9 and ps.get("top3_match")):
            ps_ok += 1
        if dims.get("gates", {}).get("match"):
            gate_match += 1
    return {
        "total": len(diffs),
        "by_severity": by_sev,
        "message_class_match_rate": round(mc_match / n, 4),
        "product_set_ok_rate": round(ps_ok / n, 4),
        "gate_match_rate": round(gate_match / n, 4),
        # roadmap Phase 5 promotion gates
        "gates_pass": (by_sev["BLOCKER"] == 0 and mc_match / n >= 0.98 and ps_ok / n >= 0.9),
    }
