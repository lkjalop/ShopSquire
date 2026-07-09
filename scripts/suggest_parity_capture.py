#!/usr/bin/env python
"""E1 parity net — capture the full /suggest payload for a query battery so a refactor of
suggest()'s response assembly can be proven behavior-identical. Deterministic fields only:
the LLM narration (async, non-deterministic) is EXCLUDED; we compare the deterministic answer,
products, ranking, verdicts, gates, and the structural keys the extraction touches.

    python -m scripts.suggest_parity_capture capture   # -> scratch/parity_baseline.json
    python -m scripts.suggest_parity_capture compare    # diff live vs baseline, exit 1 on drift
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

from tests.utils import default_headers

# Cold-session salt: reused uids accumulate Redis session state (budget_viability,
# needs_disambiguation drift between runs from memory carryover, NOT code) — every request
# gets a unique uid so capture and compare both start from an empty session. This is itself
# the E1 lesson: the response assembly is stateful, so parity must isolate the turn.
_SALT = uuid.uuid4().hex[:8]

BASE = "http://127.0.0.1:8080"
H = default_headers()
SCRATCH = os.getenv("SCRATCHPAD_DIR", ".")
OUT = os.path.join(SCRATCH, "parity_baseline.json")

# Query battery — every response-assembly branch the extraction touches:
QUERIES = [
    ("search_basic", "gaming laptop under 2000 with good battery"),
    ("budget_question", "is 1800 enough for gaming?"),
    ("fit_conflict", "i need something for training llm models, is 3500 enough?"),
    ("compound", "i need 15 work laptops under 1400 and a 27 inch monitor"),
    ("spec_deep", "what's the real difference between an 8gb and 16gb gpu for AI work?"),
    ("non_laptop_monitor", "i need a 27 inch 240hz gaming monitor"),
    ("game_fit", "gaming laptop for valorant under 1900"),
    ("game_clarify", "can this run cyberpunk 2077 and fortnite under 1900"),
    ("off_catalog", "i need 5 rack-mount GPU servers with A100s, budget 80k"),
    ("ai_workload", "i want to fine tune a 7b model locally under 2500"),
    ("bulk_sourcing", "i need 30 dell laptops for my team by next month"),
    ("payment_plan", "spending 25000 for my team — do you offer payment plans?"),
    ("faq_returns", "what is your returns policy?"),
    ("zero_result", "purple unicorn quantum laptop with 500gb vram"),
    ("brand_budget", "cheapest lenovo thinkpad you have"),
]

# Deterministic structural keys to compare (exclude timing, trace ids, llm job ids, narration prose).
KEYS = [
    "assistant_message", "view_mode", "needs_disambiguation", "confidence_band",
    "ambiguity_reason", "off_catalog", "workload_fit", "turn_type",
    "budget_viability", "use_case_analysis", "sourcing_intent", "claim_guard_result",
]
VOLATILE = {"trace_id", "decision_trace_id", "decision_id", "llm_summary_job_id",
            "timing_breakdown", "summary_pending", "_trace_recommendation_persisted"}


def _norm(payload: dict) -> dict:
    prods = payload.get("products") or payload.get("results") or []
    prod_sig = [
        {"sku": p.get("sku"), "price": p.get("price") or p.get("price_cents"),
         "why": (p.get("why") or [])[:2], "stock_status": p.get("stock_status")}
        for p in prods if isinstance(p, dict)
    ]
    out = {"n_products": len(prod_sig), "product_sig": prod_sig}
    for k in KEYS:
        v = payload.get(k)
        # sourcing_intent carries a per-request PR identifier (PR-default-<date>-<nonce>) — an
        # ID, not behavior; drop it so parity isn't polluted by a fresh nonce each call
        if k == "sourcing_intent" and isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if kk != "pr_id"}
            if isinstance(v.get("lines"), list):
                v["lines"] = [{lk: lv for lk, lv in ln.items() if lk != "name"} if isinstance(ln, dict) else ln
                              for ln in v["lines"]]
        # workload_fit verdicts: keep the verdict flags, drop any prose
        if k == "workload_fit" and isinstance(v, dict):
            v = {"floors": v.get("floors"),
                 "verdicts": [{"sku": x.get("sku"), "meets_minimum": x.get("meets_minimum"),
                               "meets_recommended": x.get("meets_recommended")}
                              for x in (v.get("verdicts") or [])]}
        out[k] = v
    return out


def _fetch(name: str, q: str) -> dict:
    r = httpx.Client(timeout=120).get(f"{BASE}/api/v1/recommend/suggest", headers=H,
                                      params={"uid": f"parity-{_SALT}-{name}", "query": q, "include_summary": "false"})
    return r.json() if r.status_code == 200 else {"_status": r.status_code}


def capture() -> int:
    snap = {}
    for name, q in QUERIES:
        snap[name] = _norm(_fetch(name, q))
        print(f"  captured {name}: {snap[name]['n_products']}p")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"[baseline] {OUT}")
    return 0


def compare() -> int:
    with open(OUT, encoding="utf-8") as f:
        base = json.load(f)
    drift = 0
    for name, q in QUERIES:
        live = _norm(_fetch(name, q))
        b = base.get(name, {})
        if json.dumps(live, sort_keys=True) != json.dumps(b, sort_keys=True):
            drift += 1
            print(f"  DRIFT {name}:")
            for k in set(live) | set(b):
                if json.dumps(live.get(k), sort_keys=True) != json.dumps(b.get(k), sort_keys=True):
                    print(f"    [{k}] base={json.dumps(b.get(k))[:120]}")
                    print(f"    [{k}] live={json.dumps(live.get(k))[:120]}")
        else:
            print(f"  ok    {name}")
    print(f"\n{'DRIFT: ' + str(drift) + ' queries changed' if drift else 'PARITY: identical'}")
    return 1 if drift else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "capture"
    raise SystemExit(capture() if mode == "capture" else compare())
