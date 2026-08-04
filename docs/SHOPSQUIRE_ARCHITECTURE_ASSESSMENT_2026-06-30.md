# ShopSquire — Architecture Assessment: Duplication, Latency, CacheRAG, Scatter-Gather, Interaction Memory

**Date:** 2026-06-30
**Method:** Three parallel read-only code explorations + direct verification of the headline claims (agents can be wrong about mechanism — the cache claim below was corrected on verification).

---

## 1. CacheRAG / CAG context caching — what it actually is

**It is a response-TEXT cache, not a RAG-context cache.** `semantic_cache.py` + the inline cache in `recommend.py:3714-3862` cache the **LLM narration text only**, keyed by an embedding of `query | budget_max | use_case | top_3_skus`. A hit (cosine distance < 0.12, TTL 4h) returns the cached prose from the summarization helper — it does **not** short-circuit `suggest()`.

- **CORRECTED (agent overstated):** procurement fields (`sourcing_intent`, `order_group`, `fulfillment_case`, `fulfillment_options`) are computed **fresh every request** by `run_fulfillment_stage` and are **NOT** lost on a cache hit. The sourcing card stays correct.
- **Orphaned flags:** `CAG_CONTEXT_ENABLED`, `DYNAMIC_CONTEXT_PROVIDER_ENABLED`, `GRAPH_RAG_ENABLED` are defined in `config.py` but **never read** anywhere in `src/app` — config without implementation. Either wire or remove (dead config is a misleading signal).
- **`session:{uid}:recent_retrieval`** (RAG retrieval metadata, 600s TTL) is **not** consulted on the cache-hit path — it's separate from the response cache.

### The real (smaller) cache issue
The cache fingerprint omits **`order_quantity`**, and matching is by embedding similarity — so *"50 gaming laptops"* can reuse *"gaming laptop"*'s cached **narration prose** (no sourcing mention) even though the structured sourcing card is shown correctly. **Result: prose↔card mismatch, not data loss.**
**Fix (cheap):** add a procurement marker to the fingerprint, e.g. `str(constraints.get("order_quantity") or "")` + `payload.get("sourcing_intent",{}).get("mode","")`, so bulk/sourcing turns don't reuse non-sourcing narration.

---

## 2. Scatter-gather — live vs scaffold

- **`recommend_pipeline.py` (the async scatter-gather):** real `asyncio.gather` of 6 legs (DB keyword, vector, caption-RAG, fraud, inventory, conditional CV) with 8s per-leg timeouts + RRF merge. **But it is SHADOW-ONLY** — `RECOMMEND_PIPELINE_V2` defaults OFF; when on it runs in a background thread and results are **not merged into the response** (`recommend.py:~4350`). The **live** retrieval is still the monolith. So scatter-gather is *proven but dormant*.
- **`draft.py:gather_evidence` (procurement RFQ evidence):** runs **SEQUENTIALLY** (hippograph · market-intel · inventory · benchmark · supplier-history), each best-effort with exception swallow. It's bounded (sync, no network hangs) but **not** parallel — a latency point only if any source gets slow. Low priority.

---

## 3. Interaction recording for NLP/LLM/narration

**Well-built 4-layer Redis session memory** (`memory.py`): `summary` (rolling checkpoint), `kv_state` (constraints, shortlist, **nqe_asked_ids/answered_fields**), `recent_retrieval` (RAG, 10min), `structured_state` (recent_messages + NQE history), `agent_steps`, `product_memory_bank`. TTL 1 day.

- **NQE context loss (old BUG-1) is FIXED** — asked/answered state loads from Redis at turn start (`recommend.py:3174`), with a fatigue window + contradiction reset.
- **Narration is 3-stage:** deterministic ranking + per-pick `why` → **async LLM prose handoff** (`llm_summary_job_id`, polled) → `recommend_message_decorator` (security/budget/confidence/honesty prefixes). Preamble grounded in last ~8 messages + image CV signals.
- **Feedback capture** (`human_feedback.py`): cart-add → `recommendation_accepted`, returns → negative; idempotent; **default-OFF** (`HUMAN_FEEDBACK_CAPTURE_ENABLED`). Turning this ON (carefully) is what feeds learning.

### 🔑 The gap that matters: procurement is NOT in conversational memory
`sourcing_intent`/`order_group`/`fulfillment_case` are returned in the payload + stored durably in the DB, but **never written to session Redis**. So next turn, the LLM/NQE/narration have **no memory** the buyer just previewed a 15-unit sourcing request. Deferring *durable case creation* to cart-confirm is correct — but the **conversational continuity** gap is real: a buyer who previews sourcing then asks "can you do it cheaper?" gets a cold new search; the assistant can't say *"for your 15-laptop sourcing request, here's a cheaper split."*
**Fix (low-risk):** persist the lightweight `sourcing_intent` (lines + planned split, no supplier identity) into `kv_state` so narration/NQE can reference it next turn. No orphaned case — just memory. This is the missing half of the fluid-procurement model (and ties to the "my requests" / flake gaps in the consumer-behaviour map).

---

## 4. Duplication / tech debt / latency (concrete)

### Duplication (collapse into shared helpers)
1. **Redis client construction — 6 sites** (deps + 5 services + rq_queue). I just unified the *timeouts*; the construction should be one `redis_factory.create_redis_client()`.
2. **price↔cents conversion — 50+ sites** with inconsistent rounding (`/100.0` vs `int(.../100)` vs `round`). Same bug class as the BAG fix → one `cents_to_dollars`/`dollars_to_cents`.
3. **Feature-flag reading — 12+** (`decisions.py` loads flags 12× in one file); `_truthy` defined 3× → consolidate on `feature_flags.get_flags()`.
4. **DB try/except/logger blocks — 40+**, "best-effort" swallow 110+ → a `best_effort()` context manager.

### Latency
1. **🔴 N+1 in `order_split._find_sku_for_phrase`** *(my code)* — a full `SELECT … FROM products` scan **per parsed phrase**. "15 laptops + 10 monitors + 5 headsets" = 3 full scans. **Fix:** one batched query or a cached phrase→SKU map.
2. **`time.sleep()` in async endpoints** (`recommend.py:~4857`, `pricing.py:~50`) — chaos latency injection that **blocks the event loop**. **Fix:** `await asyncio.sleep()` (15 min).
3. **`suggest()` ~11.7k lines** — monolithic; every request runs all stages. Intent-based stage-skipping is the structural win (longer-term).
4. VLM product-identity (20–40s cold; already flag-gated + threaded), test-suite app-creation overhead.

### Tech debt
- Orphaned CAG/context flags (§1). "Not yet wired" scaffolds (`recommend_pipeline` shadow, `embeddings` pgvector scaffold, ragas stubs). Verify CV runtime deps in the Docker image (historical gap).

---

## Prioritized fix list

**Quick wins (low-risk, high-value) — do first:**
1. **Cache fingerprint** += `order_quantity` + `sourcing_intent.mode` — stop bulk reusing non-sourcing narration. (~30 min)
2. **`time.sleep` → `asyncio.sleep`** in the two async endpoints — event-loop correctness. (~15 min)
3. **N+1 in `_find_sku_for_phrase`** — batch the phrase→SKU resolution. (~1 hr) *(my code; my fix)*
4. **Persist `sourcing_intent` into `kv_state`** — conversational continuity for procurement. (~1 hr)

**Medium (refactor, schedule):**
5. `redis_factory` (collapse the 6 Redis sites). (~2 hr)
6. `price_conversion` helper (collapse 50+ sites). (~2 hr)
7. Feature-flag consolidation (`get_flags()` everywhere). (~2 hr)
8. Remove or wire the orphaned CAG/context flags. (~1 hr)

**Longer-term (architecture):**
9. `suggest()` stage-pipeline with intent-based skipping.
10. Decide on the shadow `recommend_pipeline` V2 — promote or remove.
11. Turn on `HUMAN_FEEDBACK_CAPTURE_ENABLED` (with monitoring) to feed learning.

**Highest leverage overall:** #1 + #4 (both procurement-memory/cache correctness from the *recent* changes), then #2 + #3 (correctness + my own N+1). The duplication refactors (#5-7) are real but lower-urgency hygiene.
