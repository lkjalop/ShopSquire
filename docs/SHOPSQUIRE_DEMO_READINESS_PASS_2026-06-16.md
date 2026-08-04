# ShopSquire — Demo-Readiness Pass (file:line roadmap + NLP validation)

Date: 2026-06-16
Goal: a recordable live demo of the laptop-flavoured ShopSquire, WITHOUT touching
architecture. Grounded in the actual code (file:line verified 2026-06-16).

## 0. What's already built (so we don't rebuild it)

The "answer-first" narration the demo needs is **already implemented and wired** —
the task is to VALIDATE it and surface the supporting signals, not build it.

| Capability | Where it lives (verified) |
|---|---|
| Query decomposition (pure, no LLM) | `src/app/services/query_decomposer.py:168` `decompose()` → `QueryPlan` |
| Decomposer wired into /suggest | `recommend.py:203, 4462-4465, 6269-6272, 11963, 13159-13160` |
| Budget yes/no answer ("Yes, $X is enough…") | `recommend.py:4887` `_build_brand_budget_answer`, `:5114` `_v2`, generic floor `:4925+`, phrasing `:5751` |
| Comparison/knowledge conceptual answer | `recommend.py:4316` `_build_knowledge_answer` (uses `comparison_subjects`), injected `:195` `_maybe_inject_knowledge_answer`, `:231-232` |
| Grounded claim-guard (anti-hallucination) | `src/app/services/product_claim_guard.py` wired `recommend.py:~12760` (flag `COMMERCE_NARRATION_GUARD`) |
| Deterministic floor message | `recommend.py:5767` `_deterministic_assistant_message`, used `:12785, :12818` |
| Typed retrieval status | `src/app/services/commerce_source_status.py` + `candidate_retriever.retrieve_with_statuses()` |
| Latency accounting | `src/app/observability/stage_timer.py`; payload `recommend.py:~12128` via `_summarize_timing_safe` |

## 1. Validation: does the NLP actually answer the question? (the real ask)

### 1a. Already proven (ran `python -m eval.run_eval`, 2026-06-16)
Deterministic core = **100%**: intent routing 24/24, constraint extraction 14/14,
knowledge-path routing 5/5, identity grounding 12/12, claim grounding 8/8,
security P/R 100%/100% (0% FP). **The routing/extraction layer is solid.**

### 1b. The gap: answer-SHAPE is not yet asserted
`eval/run_eval.py` validates that a query ROUTES correctly and that constraints are
EXTRACTED, and `--live` checks faithfulness (no dropped brand in prose). It does NOT
assert that the final `assistant_message` actually ANSWERS the question. That is the
one validation to add.

### 1c. New: answer-shape eval (the deliverable)
Add `eval_answer_shape()` to `eval/run_eval.py` + dataset `eval/datasets/answer_shape.jsonl`.
Runs the real `/suggest` (live) and asserts, per intent:

| Intent | Assertion on `assistant_message` |
|---|---|
| budget question ("is $1800 enough for gaming?") | first sentence is a direct verdict: starts with `yes`/`no`/`it depends` OR matches `\$\d+ is (more than )?enough\|tight\|not enough` |
| comparison ("4060 vs 4070 for school+gaming?") | names BOTH `comparison_subjects` AND contains a recommendation verb (`pick`/`go with`/`worth it`/`unless`); NOT a bare product list |
| knowledge ("do i need 32gb ram?") | conceptual answer present; `results` may be empty and that's OK (`answer_without_products`) |
| multi-intent ("gaming + video editing, portable, <2000") | every detected `use_case` reflected; budget honoured |
| product_search ("gaming laptop 1300-1800") | ≥1 in-budget product AND a per-product `why` |

Scoring: `% of cases whose assistant_message satisfies its intent's assertion`. This
is the NUMBER that means "the NLP answers the question," distinct from routing.

Dataset shape:
```json
{"id":"as01","query":"is $1800 enough for a gaming laptop?","intent":"budget","must_match":"^(yes|no|it depends|\\$1?800 is)"}
{"id":"as02","query":"rtx 4060 vs 4070 for school and gaming?","intent":"comparison","must_contain_all":["4060","4070"],"must_contain_any":["pick","worth","unless","go with"]}
{"id":"as03","query":"do i need 32gb ram for gaming?","intent":"knowledge","allow_no_products":true,"must_contain_any":["32gb","16gb","ram"]}
```

Wiring: `eval_answer_shape()` calls `TestClient(create_app()).get("/api/v1/recommend/suggest", params=...)`,
reads `body["assistant_message"]`, applies the regex/contains assertions. No new infra
— reuses the in-process client pattern.

### 1d. Run discipline
- `python -m eval.run_eval` (deterministic, must stay 100%) — gate every change.
- `python -m eval.run_eval --live --answer-shape` (the new prose check) — the demo gate.
- Capture the answer-shape % before/after any narration tweak. Don't tweak without the number.

## 2. Demo-readiness work items (exact targets)

### Item 6a — answer-shape eval (NEW; the validation)
- `eval/run_eval.py`: add `eval_answer_shape()` + `--answer-shape` flag + scorecard line.
- `eval/datasets/answer_shape.jsonl`: ~12 cases (3 per intent above).
- Validate: run it; fix only cases that fail (most should pass — the builders exist).

### Item 6b — fix only the MEASURED answer-shape failures
Likely weak spots to check against the eval (fix if red, leave if green):
- Budget without a brand → confirm `_generic_budget_floor` (`recommend.py:4925+`) fires (BUG-7 area).
- Comparison answer actually names both subjects → `_build_knowledge_answer:4316` + `_extract_comparison_subjects` (`query_decomposer.py:111`).
- Budget answer ordering: must come FIRST, before the product summary → check `_summarize_results` preface (`recommend.py:4505`) and the `brand_budget_answer` prepend (`recommend.py:12780-12783`).

### Item 2 — surface `source_statuses` in the response + trace (credibility)
- `src/app/services/recommend_pipeline.py`: switch the scatter retrieval to
  `candidate_retriever.retrieve_with_statuses(...)` and include the returned
  `{source: SourceStatus}` in the pipeline result.
- `recommend.py` payload (`~12128`): add `"source_statuses": [...]` (+ `degraded_sources`).
- Frontend `DecisionTrace.tsx`: render an "Evidence Sources" row (source / status / latency / hits).
- Validate: a query with a cold caption index shows `caption_rag: empty` not a silent gap.

### Item 3 — surface latency accounting (credibility)
- Payload already carries `timing_breakdown` with `accounted_ms`/`unaccounted_ms` (0.5).
- Frontend `DecisionTrace.tsx`: render a compact timing waterfall incl. accounted vs unaccounted.
- Validate: `unaccounted_ms` is small on the demo queries (if large, instrument the gap stage).

### Item 4 — flip the guard + prewarm + timeouts (config, not code)
- `COMMERCE_NARRATION_GUARD=1` for the demo env (anti-hallucination on camera).
- `python scripts/prewarm_demo_cache.py` for the two demo images (vision-cache warm → no 80s hang).
- Verify vision/LLM hard timeouts (CV_IDENTITY_TIMEOUT_SEC, summary model) keep demo queries bounded.

### Item 5 — recorded dry run
- Both images (apple-red.jpg unrelated, msi-SSN.png compromised) × 3 iterations
  (gaming $1300-1800, university, content creation).
- Fix ONLY what breaks on camera. Everything else is post-demo.

## 3. Explicitly NOT in the demo pass (post-demo strangler)
- De-flavour `product_claim_guard._KNOWN_BRANDS` / spec regex → store config (first post-demo task).
- Single formatter (recommend.py's 54 `assistant_message` writes → 1).
- 1.1 engine-isolation rework → unblocks the 95-test parity oracle.
- Evidence bundle, full answer-planner, adapter pack. See `SHOPSQUIRE_COMMERCE_CORE_ROADMAP`.

## 3b. Demo-day config + commands (verified 2026-06-16)

Set these env vars on the demo server, then prewarm:
```sh
export COMMERCE_NARRATION_GUARD=1          # anti-hallucination guard ON (verified toggles)
export OLLAMA_SUMMARY_MODEL=qwen3:14b      # faster prose, same quality
export SEMANTIC_CACHE_MAX_DISTANCE=0.12    # tighter cache match
export USE_LLM_SUMMARY=1                   # LLM narration ON for the live demo
# hard timeouts already wired: CV_ANALYZE_TIMEOUT / CV_QR_TIMEOUT / CV_VISION_TIMEOUT_SEC
python scripts/prewarm_demo_cache.py       # warms cache + Ollama into RAM (5/5 OK)
```
- `COMMERCE_NARRATION_GUARD=1` → `guard_enabled()` returns True (verified).
- `prewarm_demo_cache.py` runs clean (sys.path bootstrap fixed — was `ModuleNotFoundError: src`).
- Trace panel now shows **Evidence Sources + Latency** (`data-test=evidence-sources`).

## 4. Order of execution
1. **6a** answer-shape eval (gives the prose NUMBER) →
2. **6b** fix measured failures only →
3. **2 + 3** surface source_status + timing in trace →
4. **4** flip guard, prewarm, verify timeouts →
5. **5** recorded dry run.

Each step: `python -m eval.run_eval` stays 100% (deterministic gate) + the new
answer-shape % only goes up. Commit per step when green.
