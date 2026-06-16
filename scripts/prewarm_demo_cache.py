#!/usr/bin/env python
"""WS1.4 — pre-warm the semantic response cache for a live demo.

Runs the exact demo queries once so the LLM prose is cached; on the day each
query returns in ~0.5s instead of 12-25s. Also warms the Ollama model into RAM.

Usage:
    python scripts/prewarm_demo_cache.py                      # in-process (TestClient)
    python scripts/prewarm_demo_cache.py --base http://localhost:8080 --key local-merchant-key

Env: set OLLAMA_SUMMARY_MODEL=qwen3:14b (recommended for demos) before running so
the cache is warmed for the SAME model the live server uses.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Bootstrap repo root onto sys.path so `import src...` works when run as
# `python scripts/prewarm_demo_cache.py` (the documented demo-day invocation).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# The canonical demo script. Edit to match what you'll actually type on stage.
DEMO_QUERIES = [
    {"query": "what's good to get for gaming? 1500-1900? why?", "budget_min": 1500, "budget_max": 1900},
    {"query": "is $1500 enough for a good gaming laptop?", "budget_max": 1500},
    {"query": "what is the difference between the RTX 4060 and RTX 4070 gaming laptops?"},
    {"query": "i need a laptop for gaming and video editing, portable, under 2000", "budget_max": 2000},
    {"query": "best for competitive esports valorant at 240fps under 1900?", "budget_max": 1900},
]


def _run_in_process() -> int:
    from fastapi.testclient import TestClient
    from src.app.main import create_app

    client = TestClient(create_app())
    headers = {"x-api-key": "local-merchant-key"}
    ok = 0
    for i, q in enumerate(DEMO_QUERIES):
        params = {"uid": f"prewarm_{i}", **q}
        t0 = time.time()
        try:
            r = client.get("/api/v1/recommend/suggest", params=params, headers=headers)
            dt = time.time() - t0
            msg = (r.json().get("assistant_message") or "")[:60]
            print(f"[{r.status_code}] {dt:5.1f}s  {q['query'][:50]!r} -> {msg!r}")
            if r.status_code == 200:
                ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {q['query'][:50]!r}: {exc}")
    print(f"\nPrewarmed {ok}/{len(DEMO_QUERIES)} queries. Run again to confirm sub-second cache hits.")
    return 0 if ok == len(DEMO_QUERIES) else 1


def _run_http(base: str, key: str) -> int:
    import httpx

    ok = 0
    with httpx.Client(timeout=120.0) as client:
        for i, q in enumerate(DEMO_QUERIES):
            params = {"uid": f"prewarm_{i}", **q}
            t0 = time.time()
            try:
                r = client.get(f"{base.rstrip('/')}/api/v1/recommend/suggest",
                               params=params, headers={"x-api-key": key})
                dt = time.time() - t0
                msg = (r.json().get("assistant_message") or "")[:60]
                print(f"[{r.status_code}] {dt:5.1f}s  {q['query'][:50]!r} -> {msg!r}")
                if r.status_code == 200:
                    ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[ERR] {q['query'][:50]!r}: {exc}")
    print(f"\nPrewarmed {ok}/{len(DEMO_QUERIES)} queries.")
    return 0 if ok == len(DEMO_QUERIES) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="Base URL of a running server (omit for in-process TestClient)")
    ap.add_argument("--key", default="local-merchant-key", help="x-api-key")
    args = ap.parse_args()
    print("Pre-warming demo cache. Tip: set OLLAMA_SUMMARY_MODEL=qwen3:14b and "
          "SEMANTIC_CACHE_MAX_DISTANCE=0.12 to match recommended demo settings.\n")
    return _run_http(args.base, args.key) if args.base else _run_in_process()


if __name__ == "__main__":
    sys.exit(main())
