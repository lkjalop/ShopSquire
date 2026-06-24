# ShopSquire Search, Latency, Similarity, And Core Extraction Roadmap

Date: 2026-06-20

## Executive Summary

The agnostic decomposition work is real and has moved the platform in the right direction. The core now has tenant/profile selection, profile-backed taxonomy, category, ranking/spec rules, persona patterns, brand SQL patterns, product identity, grounding, NQE deduplication, and a much stronger `SuggestContext` foundation.

The remaining capability gaps are not primarily "more decomposition." They are:

1. User-facing latency: LLM narration still blocks the response.
2. Search quality: the richer RRF/vector/caption retrieval path is still shadow-only.
3. Image similarity: visual product similarity exists as infrastructure, but is not live in the recommendation path.
4. VLM latency: image identity can be parallelized, but the flag is off and the VLM call is still slow.
5. Monolith shrink: `recommend.py` is smaller and better staged, but it is still the live orchestration monolith.

Recommended next order:

1. Baseline and freeze the current behavior with benchmark and contract tests.
2. Make narration skip/async/stream so text queries can return quickly.
3. Promote hybrid text similarity from shadow to measured fusion.
4. Wire image-to-visual-similar-products behind the existing safe image boundary.
5. Turn on parallel VLM gradually with timeout/cache/prewarm controls.
6. Continue stage extraction from `recommend.py` using `SuggestContext` and the ctx-access analyzer.

## Verified Current State

### What Is Now Substantially Done

- Agnostic core demarcation is materially improved.
- Request-boundary store profile selection exists and propagates through sync route execution.
- Category, taxonomy, grounding, ranking/spec extraction, product identity, persona, brand SQL, and NQE inputs have moved toward profile-backed behavior.
- `SuggestContext` now carries the hidden mutable bags needed for safe stage extraction:
  - `src/app/services/suggest_context.py:25`
  - `image_context`: `src/app/services/suggest_context.py:40`
  - `timing_breakdown`: `src/app/services/suggest_context.py:65`
  - `fraud_summary`: `src/app/services/suggest_context.py:68`
  - `kv_out`: `src/app/services/suggest_context.py:71`
  - `structured_state_out`: `src/app/services/suggest_context.py:72`
  - `nlp`: `src/app/services/suggest_context.py:75`
  - `constraints`: `src/app/services/suggest_context.py:78`
  - retrieval/ranking locals: `src/app/services/suggest_context.py:80`
  - dependency bag: `src/app/services/suggest_context.py:90`
- Static analysis support exists:
  - `scripts/ctx_access_map.py`
  - `tests/test_ctx_access_map.py`
- Current live monolith size is about 11,765 lines:
  - `src/app/routers/recommend.py`

### What Is Still Not Fixed

#### Pure-Text Latency

The deterministic parts are fast, but the response still waits on LLM narration in the live path.

Key anchors:

- `_summarize_results`: `src/app/routers/recommend.py:3375`
- `USE_LLM_SUMMARY`: `src/app/routers/recommend.py:3384`
- blocking summary timer: `src/app/routers/recommend.py:10598`
- summary call: `src/app/routers/recommend.py:10599`
- Ollama calls use `"stream": False`: `src/app/routers/recommend.py:3420`

Business impact:

- Users still experience multi-second delay even when the product answer can be determined from catalog, budget, stock, and constraints.
- Demo claims about sub-second text recommendations are not credible until narration is decoupled or skipped.

#### Hybrid Retrieval / Similarity

The richer path exists, but the live route still treats `RECOMMEND_PIPELINE_V2` as shadow-only.

Key anchors:

- Shadow-only comment: `src/app/routers/recommend.py:4162`
- shadow enabled check: `src/app/routers/recommend.py:4168`
- shadow thread: `src/app/routers/recommend.py:4208`
- RRF pipeline: `src/app/services/recommend_pipeline.py:223`
- DB/vector/caption fan-out: `src/app/services/recommend_pipeline.py:257`
- caption leg: `src/app/services/recommend_pipeline.py:117`
- RRF merge helper: `src/app/services/candidate_retriever.py:48`
- caption retrieval: `src/app/services/candidate_retriever.py:204`
- source status retrieval: `src/app/services/candidate_retriever.py:343`

Business impact:

- The platform has the ingredients for better semantic matching, but it is not yet the customer-affecting product-finding path.
- Search quality claims should say "implemented in shadow" until parity and cutover are complete.

#### Image-Based Product Similarity

Visual search infrastructure exists, but uploaded image to visually similar products is not a primary live recommendation path.

Key anchors:

- visual search service: `src/app/services/visual_search.py:277`
- visual index builder: `scripts/build_visual_index.py:37`
- embedding index mode: `scripts/build_visual_index.py:96`
- build modes: `scripts/build_visual_index.py:153`
- visual candidate leg by text/image-adjacent route: `src/app/services/candidate_retriever.py:166`

Business impact:

- "Find something like this image" is not yet a first-class product discovery workflow.
- Image upload currently helps identity and safe hints more than true visual similarity.

#### VLM Latency

VLM identity can be run in parallel, but the flag is off by default and the VLM itself can still take tens of seconds.

Key anchors:

- parallel vision flag commit added `PARALLEL_VISION_IDENTITY`
- parallel launcher: `src/app/routers/recommend.py:4798`
- `VisionReasoningService` import/call area: `src/app/routers/recommend.py:6690`
- future result join: `src/app/routers/recommend.py:6788`
- VLM perf test: `tests/pw/test_vision_upload_perf.py`
- parallel unit coverage: `tests/test_parallel_vision_identity.py`

Business impact:

- The architecture can avoid blocking on vision, but the live default still needs measured rollout.
- Without timeout/cache/prewarm, one slow image can still dominate perceived latency.

## Roadmap

## Tier 0: Baseline, Contract Freeze, And Docs Sync

Purpose: establish the truth before changing the live path.

### Work

- Run and record text-only, image+text, suspicious image, and empty-index benchmarks.
- Update stale docs that still show older `recommend.py` line counts or pre-SuggestContext status.
- Add one machine-readable benchmark artifact under `docs/refactor/benchmarks/`.

### Files

- Read:
  - `scripts/bench_recommend.py`
  - `docs/refactor/OPEN_BLOCKERS.md`
  - `docs/refactor/RECOMMEND_DECOMPOSITION_ROADMAP.md`
  - `docs/refactor/CORE_EXTRACTION_AND_PORTABILITY_ROADMAP_2026-06-20.md`
- Create:
  - `docs/refactor/benchmarks/RECOMMEND_BASELINE_2026-06-20.md`

### Tests / Commands

```powershell
python scripts/bench_recommend.py
python -m pytest tests/integration/test_recommend_contract_stability.py tests/test_no_flavour_in_core.py -q
```

### Done Criteria

- p50/p95 captured for text-only and image+text.
- Any latency claim in docs is backed by the benchmark artifact.
- Current state docs no longer contradict the code.

## Tier 1: Fix Text Latency By Decoupling Narration

Purpose: make deterministic product recommendations return quickly without waiting on LLM prose.

### Design

Introduce a narration mode:

- `blocking`: current behavior for compatibility.
- `skip`: deterministic answer only, no LLM summary.
- `async`: return products immediately, enqueue narration, attach `narration_pending=true`.
- `stream`: return first response immediately and stream LLM copy if the frontend supports it.

The deterministic answer should be assembled from structured evidence:

- user query understanding
- selected products
- exact matched constraints
- price/budget fit
- stock state
- safe image hints
- ranking reason codes
- source statuses

The LLM should never invent a product capability. It may only phrase claims already present in the evidence envelope.

### Files To Extract / Create / Modify

- Extract / create:
  - `src/app/services/recommend_narration_stage.py`
  - `src/app/services/recommend_response_evidence.py`
  - `src/app/services/recommend_response_finalizer.py` if the existing finalizer is not already the right home
- Modify:
  - `src/app/routers/recommend.py:3375` (`_summarize_results`)
  - `src/app/routers/recommend.py:10598` (`summary_ms` timing)
  - `src/app/routers/recommend.py:10599` summary call
  - `src/app/core/config.py` or feature flag loader for `RECOMMEND_NARRATION_MODE`
  - frontend response rendering if `narration_pending` is returned

### Tests

- Unit:
  - evidence envelope contains only structured product facts
  - deterministic finalizer returns useful copy without an LLM
  - unsupported product claims are rejected or omitted
- Route:
  - monkeypatch `_summarize_results` to sleep for 5 seconds
  - `skip` mode returns quickly
  - `async` mode returns products and `narration_pending=true`
  - `blocking` mode preserves current contract
- Regression:

```powershell
python -m pytest tests/integration/test_recommend_contract_stability.py tests/services -q
```

### Business Impact

- Immediate improvement to perceived speed for all text-only product questions.
- Reduced GPU/LLM reliance.
- Safer demos because the "why" answer is grounded in structured evidence.

## Tier 2: Promote Hybrid Text Similarity From Shadow To Measured Fusion

Purpose: make product-finding agnostic and semantically stronger without losing deterministic guardrails.

### Design

Add an explicit retrieval mode:

- `monolith`: current behavior.
- `hybrid_shadow`: current behavior plus RRF parity metrics.
- `hybrid_fusion`: merge monolith candidates with DB/vector/caption candidates, but keep existing filters and stock/budget gates.
- `hybrid_primary`: RRF retrieval is the main candidate source, with monolith fallback.

Do not flip directly to primary. First compare:

- top-k overlap
- budget adherence
- in-stock adherence
- category/use-case match
- empty/error leg rate
- latency by source

### Files To Modify

- `src/app/routers/recommend.py:4162`
  - replace "shadow only" with explicit retrieval mode handling.
- `src/app/services/recommend_pipeline.py:223`
  - return structured candidate source details and timings.
- `src/app/services/candidate_retriever.py:48`
  - keep RRF as the common merge primitive.
- `src/app/services/candidate_retriever.py:343`
  - surface source status in the route response/trace.
- `src/app/services/recommendations.py:1276`
  - reconcile older monolith retrieval with the new hybrid path.
- `src/app/repositories/embeddings.py:170`
  - keep 1536-dim product vector contract enforced.

### Files To Create

- `src/app/services/recommend_retriever_stage.py`
- `src/app/services/recommend_retrieval_metrics.py`
- `tests/services/test_recommend_retriever_stage.py`
- `tests/integration/test_recommend_hybrid_retrieval_modes.py`

### Tests

- RRF ranking is deterministic.
- Each retrieval leg can fail open with a visible source status.
- Hybrid fusion never returns out-of-budget products if monolith would not.
- Hybrid fusion respects active store profile.
- Caption/vector dimensions remain fixed.

```powershell
python -m pytest tests/services/test_candidate_retriever_caption.py tests/services/test_embedding_dim_contract.py tests/services/test_commerce_source_status.py -q
python -m pytest tests/integration/test_recommend_contract_stability.py -q
```

### Business Impact

- Better product matching for natural-language queries.
- Makes the "agnostic recommender" claim stronger because retrieval is less dependent on hardcoded SQL patterns.
- Lets operators prove the new path is better before cutover.

## Tier 3: Wire Image-To-Visual-Similar Products

Purpose: support "show me something like this" and image+text product discovery.

### Design

Image input must split into two lanes:

1. Safe visual similarity lane:
   - image embedding
   - visual nearest products
   - source label: `visual_similarity`
2. Security/forensics lane:
   - OCR/QR/prompt/PII/steganography analysis
   - quarantined raw payload
   - security matrix and trace

The image may influence search only through safe visual embedding and safe labels. OCR, QR payloads, links, or prompt-like text must never issue instructions or trigger tools.

Image/text relationship should be classified as:

- `on_topic`: image and query point to the same product intent.
- `adjacent`: image is related but not the target product, such as laptop plus laptop bag query.
- `off_topic`: image is unrelated or suspicious.

### Files To Modify

- `src/app/services/visual_search.py:277`
  - expose a clean `search_by_image_bytes` or equivalent product candidate API.
- `src/app/services/candidate_retriever.py:166`
  - add visual image candidate leg distinct from text-side visual search.
- `src/app/routers/recommend.py`
  - wire image visual candidates into the retrieval stage.
- `src/app/services/grounding_ladder.py`
  - use image relationship state as evidence, not as authority.
- `scripts/build_visual_index.py:153`
  - ensure `--mode both --captions` remains the documented pre-demo index build.

### Files To Create

- `src/app/services/image_query_relationship.py`
- `src/app/services/recommend_image_similarity_stage.py`
- `tests/services/test_image_query_relationship.py`
- `tests/integration/test_recommend_image_similarity.py`

### Tests

- Laptop image + laptop query boosts visually similar laptops.
- Laptop image + bag query treats image as adjacent, not overriding text intent.
- Apple image + gaming laptop query does not overpower the text query.
- Suspicious QR/OCR image still returns safe catalog recommendations but quarantines unsafe payload.
- Missing visual index degrades with source status, not empty silent failure.

### Business Impact

- Unlocks real multimodal product discovery.
- Improves trust because unrelated or adversarial images do not hijack recommendation.
- Strengthens the bounded-autonomy demo: commerce continues while suspicious input is traced.

## Tier 4: Make VLM Fast Enough And Safe Enough For Live Use

Purpose: use VLM identity when it helps, without making it the latency bottleneck.

### Work

- Turn on `PARALLEL_VISION_IDENTITY` only in measured percentage or demo profile.
- Add timeout and cancellation semantics for VLM futures.
- Use cache-first identity and prewarm known demo assets.
- Split VLM use into:
  - fast label/spec extraction
  - slower forensic/security analysis
- Allow identity to join late; do not block deterministic recommendation if catalog retrieval is already enough.

### Files

- `config/feature_flags.json`
- `src/app/routers/recommend.py:4798`
- `src/app/routers/recommend.py:6690`
- `src/app/routers/recommend.py:6788`
- `src/app/services/product_identity_agent.py`
- `src/app/services/vision_cache.py`
- `tests/test_parallel_vision_identity.py`
- `tests/pw/test_vision_upload_perf.py`

### Tests

- VLM timeout returns a product response with `vision_status=timeout`.
- Cache hit avoids VLM call.
- Parallel flag does not change product contract.
- Store profile context survives parallel execution.

### Business Impact

- Lower perceived latency for image uploads.
- Smaller GPU footprint because repeated demo/product images are cached.
- Safer operations because slow VLM does not stop sales.

## Tier 5: Continue `recommend.py` Stage Extraction

Purpose: shrink the live route into a typed orchestrator and make each behavior testable.

### Current Enabler

`SuggestContext` now carries enough state to extract stages without guessing hidden local mutation:

- `src/app/services/suggest_context.py:25`
- `scripts/ctx_access_map.py`

### Extraction Order

1. Memory/context stage
   - likely low risk, mostly enrichment.
   - create `src/app/services/recommend_memory_stage.py`
2. Security/fraud stage
   - keeps suspicious image and policy decisions testable.
   - create `src/app/services/recommend_security_stage.py`
3. Ranking stage
   - move post-retrieval scoring and ranking adjustment.
   - create `src/app/services/recommend_ranking_stage.py`
4. Product identity/image stage
   - unify VLM, safe hints, visual similarity, and image relationship.
   - create `src/app/services/recommend_identity_stage.py`
5. Narration stage
   - after Tier 1, move final prose and evidence envelope out of route.
   - create/extend `src/app/services/recommend_narration_stage.py`
6. Retrieval stage
   - after Tier 2, own monolith/hybrid modes.
   - create `src/app/services/recommend_retriever_stage.py`
7. NQE stage
   - already deduped; move only after retrieval/narration are stable.
8. Constraint engine
   - last, because it has the highest mutation/coupling surface.
   - create `src/app/services/recommend_constraint_engine.py`

### Do Not Use Line Count Alone As Done

Targets:

- short term: under 10,000 lines
- medium term: under 7,000 lines
- long term: under 4,000 to 5,000 lines

Actual done criteria:

- route orchestrates typed stages
- no vertical flavor in route
- no stage has hidden mutable locals outside `SuggestContext`
- each stage has unit tests and golden contract coverage
- source status and timing spans are preserved

### Tests

Before and after each stage extraction:

```powershell
python scripts/ctx_access_map.py src/app/routers/recommend.py
python -m pytest tests/integration/test_recommend_contract_stability.py -q
python -m pytest tests/test_no_flavour_in_core.py tests/services/test_suggest_context_adoption.py -q
```

## Tier 6: Profile Schema And Flavour-Fallback Hardening

Purpose: make "new vertical as JSON" reliable, not just possible.

### Work

- Add a formal StoreProfile JSON schema.
- Add a parity linter that confirms electronics profile preserves current behavior before inline fallbacks are removed.
- Remove inline electronics fallbacks once the schema and parity tests prove the profile contains the needed slots.

### Files

- Create:
  - `src/app/store_profiles/schema/store_profile.schema.json`
  - `tests/test_store_profile_schema.py`
  - `tests/test_store_profile_parity.py`
- Modify:
  - `src/app/services/recommend_utils.py`
  - `src/app/services/query_decomposer.py`
  - `src/app/services/use_case_advisor.py`
  - `src/app/flows/nqe.py`
  - `src/app/services/grounding_ladder.py`

### Business Impact

- Faster onboarding for new stores and verticals.
- Less risk of electronics assumptions leaking into pharmacy/fashion/other adapters.
- Cleaner commercial story: core code stays stable, adapter data changes per store.

## Tier 7: Bounded Autonomy Ports

Purpose: turn recommendations and inventory observations into safe bounded actions.

### Work

- Add `SupplierCommunicationPort`.
- Make supplier outreach draft-first by default.
- Route supplier contact through `decide("supplier_contact")`.
- Require human approval for:
  - supplier email send
  - purchase order
  - discount/deal changes
  - refund approval
  - product substitution that changes price/material customer outcome

### Files

- `src/app/services/inventory_agent.py:974`
- `src/app/services/inventory_agent.py:998`
- `src/app/policy/execution_gate.py:35`
- `src/app/services/playbook_action_adapters.py:91`
- create `src/app/ports/supplier_communication.py`
- create `src/app/services/supplier_communication_service.py`
- create `tests/services/test_supplier_communication_gate.py`

### Business Impact

- Moves toward autonomous retail operations without unbounded tool execution.
- Makes supplier communication auditable and reviewable.
- Keeps "machine-operated" defensible: the system can draft and recommend, but consequential actions are gated.

## Tier 8: External Product Research, Deferred

Purpose: answer questions about products not in the store catalog without confusing owned inventory.

This should be deferred until Tier 1 and Tier 2 are stable.

### Guardrails

- Keep external research separate from owned catalog retrieval.
- Add `ExternalProductResearchPort`.
- Use source allowlists.
- Send no PII outbound.
- Cache and label freshness.
- Mark products as "not sold by this store" unless mapped to a real SKU.
- Never add external products to cart or checkout without SKU mapping and policy approval.
- Never contact supplier based on external research without human review.

### Files To Create

- `src/app/ports/external_product_research.py`
- `src/app/services/external_product_research_service.py`
- `tests/services/test_external_product_research_guardrails.py`

## What To Do Next

### Step 1: Baseline

Run:

```powershell
python scripts/bench_recommend.py
python -m pytest tests/integration/test_recommend_contract_stability.py tests/test_no_flavour_in_core.py -q
```

Write:

- `docs/refactor/benchmarks/RECOMMEND_BASELINE_2026-06-20.md`

### Step 2: Narration Latency

Implement `RECOMMEND_NARRATION_MODE=skip|async|blocking` first. Do not start with streaming unless the frontend transport is already ready.

Why this first:

- It directly fixes the largest user-visible latency issue.
- It reduces LLM/GPU dependence.
- It lowers demo risk.
- It is independent of hybrid retrieval and image similarity.

### Step 3: Hybrid Retrieval Shadow-To-Fusion

Keep the old retrieval path as fallback. Add parity metrics first, then route a flag to fusion.

### Step 4: Image Similarity

Only after hybrid retrieval is instrumented. Image visual candidates should become another source in the same source-status/RRF framework.

### Step 5: VLM Parallel Rollout

Enable after timeout/cache/prewarm are in place.

### Step 6: Continue Stage Extraction

Use `ctx_access_map.py` on every extraction. Do not extract constraints first.

## What Not To Do

- Do not flip `RECOMMEND_PIPELINE_V2` directly to primary without parity metrics.
- Do not blend external product research into owned inventory.
- Do not let OCR/QR/prompt-like image text influence tools or policy.
- Do not claim sub-second text recommendations while blocking LLM narration is still enabled.
- Do not chase line count ahead of latency and search-quality fixes.
- Do not remove inline electronics fallbacks until profile schema and parity tests prove the adapter has equivalent coverage.

## Demo Readiness Definition

The platform is ready for a strong live demo when:

1. Text-only recommendation returns products quickly with deterministic "why" evidence.
2. LLM narration is skipped, async, or streamed instead of blocking product visibility.
3. Suspicious image upload still returns safe recommendations while quarantine/security trace is visible.
4. Hybrid retrieval source status is visible, even if still in shadow.
5. Product trace shows:
   - active store profile
   - query understanding
   - safe image hints
   - retrieval source statuses
   - ranking reasons
   - policy/security decisions
6. Benchmarks are recorded and match the claims in the deck.

