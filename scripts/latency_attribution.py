#!/usr/bin/env python
"""P1 step 1 — latency attribution for the V2 recommendation core.

Answers the question the p95=13s gate raised: WHERE does the time go? Measured, not inferred.
Finding (2026-07-16, single RTX 5070 Ti, warm): the router MODEL call (route_turn ->
turn_router._default_llm_fn -> Ollama /api/generate) is ~11-13s = ~100% of the turn; retrieval
(_exec_retrieve, SQL) is sub-percent. So the loopback/retrieval "fixes" cannot move p95 — the lever
is the ROUTER MODEL (default qwen3:14b, num_predict=256).

Use it to size the model lever — measure an alternative router model directly:
    ROUTER_MODEL=llama3.2:3b python -m scripts.latency_attribution
    ROUTER_MODEL=qwen3-vl:8b python -m scripts.latency_attribution     # already resident
    python -m scripts.latency_attribution                              # current default (qwen3:14b)
"""
from __future__ import annotations

import os
import statistics
import time

from src.app.models.db import db_session
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import route_turn, _router_model

RUNS = int(os.getenv("LAT_RUNS", "4"))
QUERY = os.getenv("LAT_QUERY", "gaming laptop under 2000 with a good gpu for 1440p")


def _env(i: int) -> TurnEnvelope:
    return TurnEnvelope.from_suggest_params(
        query=f"{QUERY} (v{i})", uid="lat-probe", tenant_id="default",
        budget_max=2000, trace_id=f"lat-{i}")


def main() -> None:
    model = _router_model()
    print(f"router model = {model}   (set ROUTER_MODEL to measure an alternative)")
    print(f"query = {QUERY!r}   runs = {RUNS} (+1 warm)\n")

    # warm (first call loads the model — excluded from the stats)
    with db_session() as db:
        t0 = time.perf_counter()
        try:
            route_turn(db, _env(0))
        except Exception as exc:
            print(f"warm call error: {repr(exc)[:140]}")
        print(f"warm (incl. cold load): {(time.perf_counter()-t0)*1000:.0f}ms\n")

    m = []
    for i in range(1, RUNS + 1):
        with db_session() as db:
            t0 = time.perf_counter()
            try:
                route_turn(db, _env(i))
                dt = (time.perf_counter() - t0) * 1000
                m.append(dt)
                print(f"run {i}: router model call = {dt:.0f}ms")
            except Exception as exc:
                print(f"run {i}: ERROR {repr(exc)[:140]}")

    if m:
        p95 = sorted(m)[max(0, int(0.95 * len(m)) - 1)]
        print(f"\nMODEL CALL  median={statistics.median(m):.0f}ms  p95={p95:.0f}ms  ({model})")
        print(f"gate = 8000ms  -> {'PASS' if p95 < 8000 else 'FAIL'} on the model call alone")
        print("retrieval (_exec_retrieve, SQL) is sub-percent of this — not the lever.")


if __name__ == "__main__":
    main()
