"""Demo queries harness for recommendation API.

Prereqs:
  - Start API server (e.g., uvicorn on 127.0.0.1:8081)
  - Set `x-api-key` if required (default: local-merchant-key)

Run:
  python scripts/demo_queries.py

Outputs a concise summary: products count, top SKUs, slots, intents, and trace.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Dict, Any, List

import requests


BASE = os.getenv("API_BASE", "http://127.0.0.1:8081")
KEY = os.getenv("API_KEY", "local-merchant-key")

QUERIES: List[str] = [
    "I have a budget between 900 and 1400. Can I play games in ultra high graphics?",
    "show me laptops I can use for university between 1800 and 2100",
    "I got a bag that can fit 14 inches and my budget is 1800",
]


def summarize_result(j: Dict[str, Any]) -> Dict[str, Any]:
    items = j.get("results") or []
    skus = [it.get("sku") or it.get("id") or it.get("name") for it in items]
    nlp = (j.get("proposal") or {}).get("nlp") or {}
    trace_id = j.get("trace_id") or j.get("decision_id")
    return {
        "status": j.get("status"),
        "count": len(items),
        "top_skus": skus[:6],
        "slots": nlp.get("slots") or {},
        "intents": [i.get("intent") for i in (nlp.get("intent_chain") or [])],
        "trace_id": trace_id,
        "model_tier": j.get("model_tier"),
        "llm_model": j.get("llm_model"),
    }


def fetch_trace(trace_id: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"{BASE}/api/v1/decisions/{trace_id}", headers={"x-api-key": KEY}, timeout=6)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


def run_query(q: str):
    u = f"{BASE}/api/v1/recommend/suggest"
    print("\n=== Query ===")
    print(q)
    t0 = time.perf_counter()
    r = requests.get(u, params={"uid": "demo", "query": q}, headers={"x-api-key": KEY}, timeout=8)
    dt = (time.perf_counter() - t0) * 1000.0
    print("HTTP:", r.status_code, f"{dt:.1f}ms")
    if not r.ok:
        print("Error:", r.text[:400])
        return
    j = r.json()
    s = summarize_result(j)
    print("Summary:", s)
    if s.get("trace_id"):
        t = fetch_trace(s["trace_id"]) or {}
        print("Trace: keys:", sorted(t.keys())[:10])


def main():
    print("BASE:", BASE)
    print("API_KEY:", KEY)
    for q in QUERIES:
        run_query(q)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
