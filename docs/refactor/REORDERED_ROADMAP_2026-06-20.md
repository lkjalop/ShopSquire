# Reordered Roadmap — post-Tier-1 (2026-06-20)

Reflects: latency **solved** for text, baseline frozen, and the key insight that **excision and
feature work are the same work per stage**. Supersedes the ordering in
SHOPSQUIRE_SEARCH_LATENCY_SIMILARITY_ROADMAP for sequencing.

## ✅ Done this session
- **Tier 0 — baseline frozen** (`64f7bce`): LLM narration = 85–91% of route latency; deterministic
  pipeline <140ms. `docs/refactor/benchmarks/RECOMMEND_BASELINE_2026-06-20.md`.
- **Tier 1 — narration latency SOLVED** (`30f0ea5`): `RECOMMEND_NARRATION_MODE=skip|async|blocking`
  (env overrides config; default blocking = zero-risk). **Measured: skip p50 615ms vs 5176ms
  blocking — ~8.4× faster**, summary_ms=0, deterministic grounded answer. *To turn on:* set
  `RECOMMEND_NARRATION_MODE=skip` (or `async`).
- **A1 parallel VLM** (`69842d9`, flag off), **B0 analyzer** (`1a2dc72`/`b2ae8dc`), **SuggestContext
  Pass 1–6** — extraction prerequisites done.

## The key sequencing insight
**Each feature improvement IS a stage extraction.** Building Tier-2 hybrid retrieval = extracting
the retriever stage; finishing async narration = extracting the narration stage; image similarity =
the identity/image stage. So the **excise-to-core/adapter** work is not a separate track — it
happens *as* each feature lands, using the proven pattern:

> ctx-access analyzer (`scripts/ctx_access_map.py`) → reader-migrate the block's reads to `ctx.*`
> → lift `run_stage(ctx, *few_scalars) -> ctx` → golden contract + full regression + ratchets →
> commit. Tail-first; **constraints last**.

## Reordered priority (next)

1. **Tier 1b — finish latency (turn it on + async).**
   - Turn `RECOMMEND_NARRATION_MODE=skip` on in the demo/prod profile; re-run the live bench.
   - `async`: add a job store + tiny poll endpoint so blocking-quality prose arrives out-of-band
     (deterministic answer instant, prose upgrades when ready). **Extract the narration stage** here.
   - Turn on parallel VLM (`PARALLEL_VISION_IDENTITY`) measured + add timeout/cache/prewarm.

2. **Tier 2 — hybrid text retrieval: shadow → measured fusion.**
   - Add parity metrics (top-k overlap, budget/stock adherence, latency by leg) FIRST; then flag to
     fusion; never flip V2 to primary blind. **Extract the retriever stage** here (it already has
     `merge_rrf` + `from_caption`).

3. **Safe internet search** (elevated per request — *after* Tier 2's source-status framework exists).
   - New `ExternalProductResearchPort` behind hard guardrails: **domain allowlist; NO PII outbound;
     cache + freshness label; mark "not sold by this store" unless mapped to a real SKU; never
     auto-add-to-cart or auto-contact-supplier without SKU mapping + human approval.** Plugs in as
     another labeled source in the same RRF/source-status framework (so it never silently
     contaminates owned inventory). Treat OCR/QR/page text as data, never as tool instructions.

4. **Tier 3 — image → visually-similar products** (uses Tier 2's framework). Safe image lane only
   (visual embedding + safe labels); security/forensics lane stays separate. **Extract the
   identity/image stage** here.

5. **Tier 6 — agnostic hardening**: profile JSON schema + parity linter; then remove inline
   electronics ranking/spec fallbacks → flavour-*free*.

6. **Background, continuous**: remaining stage extraction (memory → security → ranking →
   constraints) via the analyzer, shrinking `recommend.py` toward <5k. **Do not chase line count
   ahead of 1–4.**

7. **Deferred**: bounded-autonomy supplier ports (Tier 7).

## What NOT to do (carried from the source roadmap)
- Don't flip `RECOMMEND_PIPELINE_V2` to primary without parity metrics.
- Don't blend external/internet research into owned inventory; always label + SKU-gate.
- Don't let OCR/QR/prompt-like image or web text steer tools or policy.
- Don't claim sub-second text until `RECOMMEND_NARRATION_MODE` is actually `skip`/`async` in the run.
- Don't remove inline electronics fallbacks before profile schema + parity prove coverage.

## Resume point (after the pause)
Start at **Tier 1b**: turn `skip` on in the live profile + re-bench, then build `async` (job store +
poll) while extracting the narration stage. Everything is committed and green.
