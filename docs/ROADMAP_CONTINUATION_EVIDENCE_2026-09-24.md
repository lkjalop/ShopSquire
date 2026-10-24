# Roadmap continuation evidence — 24 September 2026

This continues [the first execution report](ROADMAP_EXECUTION_2026-09-24.md). The roadmap is not complete. This pass adds bounded live browser/model evidence, real PostgreSQL effect races, and a larger provisional model comparison. It also fixes failures discovered while collecting evidence. Existing unrelated workspace changes were preserved; nothing was committed, deployed, or sent to a real supplier.

## Fixes supported by new evidence

- **Unsupported qualification in a question:** a browser screenshot showed “Stretch to $1919 for the real fit” while terminal authority was unknown and no product was qualified. Terminal question projection now removes the budget/capability-gap offer when catalogue authority is not permitted. Other material questions remain.
- **Cart authorization race:** missing or malformed expiry fails closed. The transactional claim compares tenant, buyer, exact serialized plan, and unexpired deadline against the values evaluated before execution. A changed plan cannot inherit the previous authorization. Expired rows may remain stored as proposed, but cannot execute.
- **Refund identity and completion:** an idempotency key cannot be reused for a different tenant/order/amount/currency/intent/approval. A successful receipt settles only the matching provider refund reference, not every submitted refund on the payment intent. Partial refunds no longer mark the entire order returned. PostgreSQL order locking serializes duplicate reconciliation before ledger insertion.
- **Refund receipt ingestion:** authenticated successful individual refund objects supply exact references and amounts. A cumulative charge refund amount is no longer treated as a new individual refund. Charge events and individual refund events share replay-safe reconciliation. Old queued charge-only reconciliation payloads fail closed and require reconciliation. Embedded charge refund lists may be truncated; historical backfill is not implemented. This follows the individual object contract in [Stripe's refund API](https://docs.stripe.com/api/refunds) and the embedded-list limitation in [Stripe's refund listing documentation](https://docs.stripe.com/api/refunds/list).
- **Market evidence consumption:** expired demand, available-to-promise and economics evidence cannot authorize replenishment. Demand observations more than five minutes in the future are rejected. This does not certify every legacy evidence path as fresh.
- **False forecast confidence:** absent history previously became 180 fabricated zero-demand days and apparently perfect interval coverage. It now remains empty, reports insufficient history and undefined calibration, and selects no model. Source availability reflects observations for the target SKU. Computation version is now `forecast_intelligence_v2`.
- **Model configuration:** the shared Ollama transport explicitly supplies the configured context length, defaulting to 4096, unless deliberately overridden by transport options.

## Browser and mixed-model evidence

The live stack used an isolated SQLite proof database, temporary Redis on 6385, backend 8085, Vite 5175, dedicated Ollama 11435, and the existing SearXNG service on 8888. Browser software compositing avoided sharing the display GPU with inference. Models and network research were real.

Browser result: **nine-turn projection test passed**, with per-turn elapsed times from 1.758 to 16.401 seconds; **fresh-case research test passed** in 25.7 seconds. The nine-turn sequence repeats university shopping, Blender workload and a request for official research three times. Assertions compare the rendered assistant response, API terminal outcome, Decision Trace revision and accepted-claim count, and prohibit commerce authority and the unsupported budget-upgrade button. The fresh-case explicit research request returned one accepted official requirement with partial coverage; the rendered answer, UI evidence count and revision-bound trace agreed. Qualification and commerce remained blocked. The university-to-Blender sequence did not expose a research action in one completed run; passing projection checks alone does not close that continuity issue.

One earlier attempt failed because its first request overlapped a backend restart; the failed trace is retained in `.artifacts/continuation-browser-final`. Another completed all nine projection checks but failed the research-action assertion; see `.artifacts/continuation-browser-verified`. Nine-turn recordings are in [continuation-browser-confirmed](../.artifacts/continuation-browser-confirmed), with a [turn summary](../.artifacts/continuation-browser-summary.json). Its fresh-case subtest initially failed an incorrect start-button expectation: research had already completed automatically in response to the explicit request. The corrected assertion checks the accepted result, rendered answer and trace; see [fresh-case recordings](../.artifacts/continuation-browser-research) and [passing log](../.artifacts/continuation-browser-research.log). The repeated conversation issue remains open: the case research plan is built from the original retained purpose, which can omit the later workload.

The separate gateway soak completed **9/9 calls**: three text → image → text cycles using `qwen3.5:9b-q4_K_M` and `qwen3-vl:8b`. Model digests, image hash, timings, scheduler receipts and resident-model checkpoints are recorded. Each checkpoint had one resident model. Vision calls took approximately 12 seconds; returning to text required approximately 8.7 seconds of reload work. This is bounded transport/residency evidence, not browser attachment coverage, vision-quality certification, long-duration stress or proof about every instant between checkpoints. [Mixed-model artifact](../.artifacts/continuation-mixed-soak.json); harness: `scripts/soak_local_models.py`.

## Effect and policy verification

| Verification group | Result | Evidence |
|---|---:|---|
| Cart, refunds, ledger, checkout, dispatch, returns, supplier boundary and forecast | 87 passed | [JUnit](../.artifacts/continuation-effects-tests.xml) |
| PostgreSQL integrity/effect races plus refund/API regression checks | 17 passed | [JUnit](../.artifacts/continuation-postgres-tests.xml) |
| Market policy, demand, proposals and fulfillment | 48 passed | [JUnit](../.artifacts/continuation-market-tests.xml) |
| Terminal qualification/projection checks | 23 passed | [JUnit](../.artifacts/continuation-terminal-tests.xml) |
| Final forecast version and qualification regressions | 15 passed | [JUnit](../.artifacts/continuation-final-regressions.xml) |

These groups overlap; their counts must not be summed as unique tests. The PostgreSQL group includes eight actual PostgreSQL tests, including three new races: competing outbound workers transmit once, concurrent refund settlement affects only the exact refund, and duplicate reconciliation produces one ledger entry while a partially refunded order remains paid. Provider transport was fake for effect tests; no live payment or supplier effect occurred. Function-size ratchet, undefined-name checks on changed Python code and whitespace checks passed. This is targeted verification, not the full repository suite.

Broader effect coverage is improved, not universal. Pending-refund expiry/revocation, every effect sink, provider ambiguity recovery and historical refund backfill still need explicit coverage. A submitted outbound message remains unverified until separate completion evidence arrives.

## P2: tenant-relevant decision remains blocked by data

Read-only inspection covered the root database, the current proof database and both prior external-intelligence recording databases. All inspected databases with a market mapping table had **zero market subject mappings**. Commercial outcomes, reconciled purchase facts and forecast/actual pairs were also absent. Older recording databases contain explicitly seeded demo findings and session traffic aggregates; those do not establish current SKU demand. The earlier California weather observation has no verified relationship to an actual tenant SKU or Australian transport lane.

[Database audit](../.artifacts/continuation-market-readiness.json) and [actual no-history forecast evaluation](../.artifacts/continuation-forecast.json) preserve the evidence. No tenant mapping was invented. The requested real tenant/SKU or supplier-to-destination lane has not been supplied. A useful operational market decision requires that scope plus current governed observations; this gate remains open.

## P3: larger evidence, no model winner

The router comparison ran **9B → 14B → 14B → 9B**, with explicit warmups, fixed 4096 context, exact model digests and a frozen historical scenario cohort. Two invalid setup labels (`CART_MUTATION`, `OFF_DOMAIN`) were excluded consistently from all four runs because neither belongs to the runtime vocabulary. This leaves **21 unique cases, repeated twice per model**, not 42 independent cases. Original cohort bytes and raw results remain preserved. Future benchmark runs now reject invalid labels up front; the corrected future cohort is a different revision.

| Measure | Qwen 9B | Qwen 14B |
|---|---:|---:|
| Pipeline lane matches | 36/42 | 36/42 |
| Model-backed matches / model-backed answers | 34/40 | 30/36 |
| Deterministic observations | 2 | 2 |
| Timeout fallbacks | 0 | 4 |
| Median end-to-end routing time | 1.46 s | 13.52 s |
| p95 end-to-end routing time | 8.53 s | 40.01 s |

The 14B fallback lane happened to match expected labels in its four timeout cases, so pipeline accuracy must not be presented as model accuracy. Timings include taxonomy/embedding work and fallback, and embedding timeouts remain visible in logs. Warmup timings include both cold and warm starts for each model. Labels are agent-derived historical expectations, not independently reviewed production labels; repeated runs do not establish statistical superiority or downstream decision improvement. The 9B candidate showed lower latency and fewer timeouts in this environment; **no quality winner or model promotion is authorized**.

[Comparable summary](../.artifacts/continuation-router-summary.json), [run manifest](../.artifacts/continuation-router-runs.json), [original cohort](../.artifacts/continuation-router-original-cohort.json). Harnesses: `scripts/benchmark_local_router.py` and `scripts/summarize_router_comparison.py`.

The historical Hippograph shadow comparison covered eight recorded slates: mean NDCG@10 was **0.5051 both before and after**, delta zero, despite two changed slates. Labels still require a human second pass. Keep this feature evidence-only. This is not a Neo4j infrastructure benchmark or evaluation of the current V2 retriever. [Graph comparison](../.artifacts/continuation-graph-ab.json).

Current retrieval cannot reuse the historical relevance labels: **0 of 25 judged SKUs** exists in the inspected current catalogues. [Coverage audit](../.artifacts/continuation-retrieval-readiness.json). A representative retrieval comparison needs frozen current catalogue facts and independently reviewed relevance labels. Forecast model promotion similarly needs real outcome history; zero rows cannot serve as a quality benchmark.

## Remaining release gates

1. Resolve browser research continuity, demonstrate complete scoped qualification, and extend bounded checks to browser image uploads and sustained mixed workloads.
2. Supply and validate an actual tenant/SKU or transport-lane mapping, then record one decision using current relevant governed evidence.
3. Extend exact authorization, revocation and independent completion tests to remaining effect sinks.
4. Freeze representative current-catalogue labels and real demand/outcome history before retrieval, infrastructure, model or forecast promotion.

The dedicated backend, frontend and Ollama processes were stopped after verification; the temporary Redis and PostgreSQL containers were removed. Existing user Ollama and SearXNG services were left untouched. Local recordings and proof databases remain available for review.
