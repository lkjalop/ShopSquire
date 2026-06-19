#!/usr/bin/env python3
"""Latency bench for the recommend route — turns "feels fast" into p50/p95 spans.

Drives GET /api/v1/recommend/suggest N times over a fixed query set and aggregates the
`timing_breakdown` already emitted in each response (guard_ms, security_analysis_ms, nlp_ms,
catalog_profile_ms, summary_ms, route_total_ms, …). No production change — it reads what the route
already measures. Run against a live stack:

    python scripts/bench_recommend.py --url http://localhost:8080 --n 30

This is the gate the roadmap requires BEFORE any latency-improvement claim (trace batching,
narration skip): capture a baseline, change one thing, re-run, compare the spans.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

_DEFAULT_QUERIES = [
    "gaming laptop between 1300 and 1800",
    "lightweight laptop for university under 1200",
    "is $1500 enough for video editing?",
    "show me business laptops",
    "best laptop for programming",
]


def percentile(values: List[float], p: float) -> float:
    """Nearest-rank percentile (p in [0,100]). Pure + dependency-free."""
    xs = sorted(v for v in values if isinstance(v, (int, float)))
    if not xs:
        return 0.0
    if p <= 0:
        return float(xs[0])
    if p >= 100:
        return float(xs[-1])
    import math
    rank = max(1, math.ceil(p / 100.0 * len(xs)))
    return float(xs[min(rank, len(xs)) - 1])


def aggregate(samples: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """samples = list of timing_breakdown dicts → {stage: {p50, p95, max, n}}. Pure."""
    keys: set[str] = set()
    for s in samples:
        if isinstance(s, dict):
            keys.update(k for k, v in s.items() if isinstance(v, (int, float)))
    out: Dict[str, Dict[str, float]] = {}
    for k in sorted(keys):
        vals = [float(s[k]) for s in samples if isinstance(s, dict) and isinstance(s.get(k), (int, float))]
        if vals:
            out[k] = {"p50": percentile(vals, 50), "p95": percentile(vals, 95), "max": max(vals), "n": len(vals)}
    return out


def _print_table(agg: Dict[str, Dict[str, float]]) -> None:
    print(f"{'stage':<26}{'p50(ms)':>10}{'p95(ms)':>10}{'max(ms)':>10}{'n':>6}")
    print("-" * 62)
    # route_total_ms last for readability
    order = sorted(agg, key=lambda k: (k == "route_total_ms", k))
    for k in order:
        a = agg[k]
        print(f"{k:<26}{a['p50']:>10.0f}{a['p95']:>10.0f}{a['max']:>10.0f}{int(a['n']):>6}")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8080", help="base URL of a running stack")
    ap.add_argument("--n", type=int, default=20, help="requests per query")
    ap.add_argument("--uid", default="bench-uid")
    ap.add_argument("--header-profile", default=None, help="X-Store-Profile (vertical) to bench")
    args = ap.parse_args(argv)

    import httpx

    headers = {"X-Store-Profile": args.header_profile} if args.header_profile else {}
    samples: List[Dict[str, Any]] = []
    with httpx.Client(base_url=args.url, timeout=30.0) as client:
        for q in _DEFAULT_QUERIES:
            for _ in range(args.n):
                try:
                    r = client.get("/api/v1/recommend/suggest", params={"uid": args.uid, "query": q}, headers=headers)
                    tb = (r.json() or {}).get("timing_breakdown") or {}
                    if isinstance(tb, dict):
                        samples.append(tb)
                except Exception as exc:  # bench is best-effort; a failed sample is skipped, not fatal
                    print(f"[skip] {q!r}: {exc}", file=sys.stderr)
    if not samples:
        print("no samples collected — is the stack up at", args.url, "?", file=sys.stderr)
        return 1
    agg = aggregate(samples)
    _print_table(agg)
    print("\nJSON:", json.dumps(agg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
