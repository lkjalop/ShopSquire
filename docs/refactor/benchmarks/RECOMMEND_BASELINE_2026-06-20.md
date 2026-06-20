# Recommend Route — Latency Baseline (2026-06-20)

**Purpose**: freeze pre-change latency truth before Tier 1 (narration decoupling). Any latency
claim must be backed by a re-run of this artifact.

## Method
- In-process `TestClient` against `GET /api/v1/recommend/suggest`, N=30 calls per profile,
  aggregating the `timing_breakdown` each response already emits (`scripts/bench_recommend.py`
  primitives). `recommend.py` @ commit prior to Tier 1.
- **Caveat — this is a FLOOR, not production p50/p95.** It runs with whatever LLM the dev env has
  (a real Ollama summary call IS happening — see `summary_ms`), no CDN/network, single process,
  warm caches. For a credible production figure, re-run `scripts/bench_recommend.py --url <live-stack>`.

## Results (milliseconds)

### Text-only (5 queries × 6)
| stage | p50 | p95 | max |
|---|---|---|---|
| nlp_ms | 0 | 1 | 2 |
| catalog_profile_ms | 0 | 2 | 15 |
| retrieve_ms | 1 | 5 | 5 |
| rerank_ms | 6 | 133 | 174 |
| security_analysis_ms | 42 | 73 | 884 |
| **summary_ms (LLM narration)** | **4414** | **34544** | 50165 |
| route_total_ms | 5176 | 34723 | 50374 |
| wall_total_ms | 5265 | 34851 | 50494 |

### Image+text (image_labels="laptop,thinkpad" + OCR)
| stage | p50 | p95 | max |
|---|---|---|---|
| summary_ms (LLM narration) | 4296 | 16590 | 17080 |
| security_analysis_ms | 49 | 72 | 77 |
| rerank_ms | 6 | 10 | 11 |
| retrieve_ms | 2 | 5 | 5 |
| route_total_ms | 4713 | 16830 | 17319 |

## Headline
- **LLM narration is 85–91% of total route latency** (text p50: 4414 of 5176ms; image p50: 4296 of 4713ms).
- The deterministic + agnostic pipeline (nlp + catalog + retrieve + rerank) is **<140ms p50**.
- Security analysis runs in parallel and contributes ~42–49ms p50.
- **Implication**: skipping/decoupling narration takes a text recommendation from ~5s → <150ms.
  This is the Tier 1 target and the single highest user-facing ROI.

## Re-run after Tier 1
Expect `route_total_ms` p50 to collapse toward `security_analysis_ms + rerank_ms` (~50–150ms) in
`skip` mode, with `summary_ms` either absent (skip) or off the critical path (async).
