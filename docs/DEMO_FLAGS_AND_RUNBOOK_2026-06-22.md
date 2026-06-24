# ShopSquire — Demo Flags & Pre-Flight Runbook (2026-06-22)

Authoritative reference for the feature flags that change recommend/CV/security
behaviour, their **current defaults**, the **resolution order**, and the
**precondition that gates flipping each one**. Written for a live demo where the
priority is: deterministic, grounded answers + visible security signals, with no
surprise latency or half-wired experimental paths.

> Standing rule baked into this doc: **do not flip `PARALLEL_VISION_IDENTITY`,
> `RECOMMEND_NARRATION_MODE`, or `RECOMMEND_RETRIEVAL_MODE` off their defaults
> without bench data.** Each "flip when" below names the bench/index artifact that
> must exist first. Until then, the safe demo config == the shipped defaults.

## Resolution order (important)

For the recommend/research/retrieval toggles, **the environment variable wins
over `config/feature_flags.json`.** Code paths:

- `RECOMMEND_NARRATION_MODE` — env override wins, else config flag
  ([recommend.py:10560](../src/app/routers/recommend.py#L10560)).
- `RECOMMEND_RETRIEVAL_MODE` — env wins, else config
  ([recommend_retriever_stage.py:22](../src/app/services/recommend_retriever_stage.py#L22)).
- `EXTERNAL_RESEARCH_ENABLED` — env wins, else config
  ([external_product_research_service.py:166](../src/app/services/external_product_research_service.py#L166)).
- `IMAGE_SIMILARITY_ENABLED` — read from config flags
  ([recommend.py:10220](../src/app/routers/recommend.py#L10220)); readiness also
  requires a built FAISS index
  ([commerce_feature_readiness.py:27](../src/app/services/commerce_feature_readiness.py#L27)).

So for a demo you can leave `config/feature_flags.json` as-is and toggle per-run
with env vars, or pin the JSON. Pick one; don't fight yourself across both.

## Flag table

| Flag | Default | Demo value | Flip when |
|------|---------|-----------|-----------|
| `RECOMMEND_NARRATION_MODE` | `blocking` | **`blocking`** (keep) | `async` only after `bench_recommend` shows LLM narration is the latency bottleneck AND Ollama is warm. `async` returns the deterministic grounded answer instantly, then streams prose. `skip` = deterministic only (no LLM) — use as the **offline/Ollama-down fallback**. |
| `RECOMMEND_RETRIEVAL_MODE` | `shadow` | **`shadow`** (keep) | `fusion`/`primary` only after the V2 hybrid (DB+vector+caption RRF) shows parity in `recommend_retrieval_metrics`. Shadow is measurement-only, NOT customer-affecting. |
| `IMAGE_SIMILARITY_ENABLED` | `false` | `true` **only after** `build_demo_visual_index` | Needs CLIP + a built FAISS index; readiness gate returns "off" / "index not ready" otherwise. Leaving it off is safe (text path still works). |
| `EXTERNAL_RESEARCH_ENABLED` | `false` | **`false`** (keep) | Requires a configured `EXTERNAL_RESEARCH_ALLOWLIST` (currently `[]`). Guardrails: allowlist-only, no PII outbound, SKU-gated, never auto-cart/supplier, web text is data not instructions. Keep OFF unless the demo explicitly shows safe internet search with the allowlist populated. |
| `PARALLEL_VISION_IDENTITY` | `false` | **`false`** (keep) | Only after `bench_vlm_latency` shows the parallel vision+identity path is faster AND stable. Default sequential path is correct. |
| `RECOMMEND_PIPELINE_V2` | `0` (off) | **off** (keep) | Shadow scatter-gather pipeline; non-customer-affecting measurement only ([recommend.py:4202](../src/app/routers/recommend.py#L4202)). |
| `FRAUD_ADAPTIVE_WEIGHTS` | `0` (off) | **off** (keep) | Learned signal multipliers; needs `record_fraud_outcome` history wired into incident resolution before it has signal ([fraud_scorer.py:323](../src/app/services/fraud_scorer.py#L323)). |
| `MODEL_THEFT_GUARD_ENABLED` | `1` (ON) | **`1`** (keep ON) | It's a security selling point. Caveat: 50 identical queries from one uid trip the structural-probe guard → 429. Demo with *varied* queries, or set `0` only for a throughput/latency clip. |
| `AUTO_LLM_RERANK_HIGH_COMPLEXITY` | `true` | `true` | LLM rerank fires when complexity ≥ `LLM_RERANK_COMPLEXITY_MIN` (6) and budget ≤ `LLM_RERANK_CHEAP_BUDGET_MAX` (1200). Needs Ollama; degrades gracefully if absent. |

## Net demo config

**The safe demo config is the shipped defaults.** The only deliberate flips
are gated on live-stack artifacts you build first:

1. Build `build_demo_visual_index` → then `IMAGE_SIMILARITY_ENABLED=true` (optional, only if demoing visual search).
2. Run `bench_recommend` / `bench_vlm_latency` → only then consider `RECOMMEND_NARRATION_MODE=async` and/or `PARALLEL_VISION_IDENTITY=true`.

Everything else stays default. `EXTERNAL_RESEARCH_ENABLED` stays off unless the
allowlist demo is in scope.

## Environment that actually needs to be set (non-flag)

- `OWNER_API_KEY` — must match what the email lab / admin UI sends, or you get
  the "SECURITY REVIEW — ERROR" 401/403 artifact (not an engine failure). Set
  `localStorage.setItem('ss_owner_key', <key>)` in the browser to match.
- `MERCHANT_API_KEY` — default `local-merchant-key` in tests; set explicitly for
  the storefront/recommend demo.
- `CV_VISION_ENABLED` — needs Ollama for the VLM leg; CV degrades (QR/OCR/steg
  still run) if the model is offline. For a deterministic demo without Ollama,
  the deterministic recommend path + non-VLM CV signals are the reliable core.
- `USE_LLM_SUMMARY` / `USE_LLM_RERANK` / `USE_OLLAMA_INTENT` — need Ollama.
  With Ollama down, set narration `skip` and rely on the deterministic grounded
  answer (the never-empty CRAG recovery means responses are never blank).

## Ollama-down fallback (fully deterministic demo)

```
RECOMMEND_NARRATION_MODE=skip
USE_LLM_SUMMARY=0
USE_LLM_RERANK=0
USE_OLLAMA_INTENT=0
CV_VISION_ENABLED=0
```

This gives grounded, evidence-cited answers (spec-by-[N] format, per-product
`why`, budget verdicts, security flags) with zero LLM dependency — the safest
demo if the box has no GPU/Ollama. The deterministic assistant message has a
never-empty recovery branch, so zero-result turns still answer with an upgrade
path rather than a blank reply.
