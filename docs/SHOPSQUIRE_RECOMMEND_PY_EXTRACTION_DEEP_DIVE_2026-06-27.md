# `recommend.py` Extraction — Deep Dive, Connection Map & Plan
**2026-06-27** · the biggest spaghetti-risk in the codebase, mapped before a single line moves.

---

## 0. Executive summary
- `src/app/routers/recommend.py` is **12,028 lines**, 118 top-level functions, 10 endpoints.
- **`suggest()` is a SINGLE function spanning lines 4216→11336 — ~7,120 lines.** That is the monster. Everything else in the file is helper functions (lines 1–4215) or small endpoints (11336+).
- **27 `recommend_*` stage modules are ALREADY extracted** (`recommend_ranking`, `recommend_nqe_stage`, `recommend_fulfillment_stage`, `recommend_intelligence_stage`, `recommend_post_pipeline`, …) **and a carrier object exists** — `services/suggest_context.py::SuggestContext` (`@dataclass`). So the *pattern* is proven; the work is **finishing the migration**, not inventing it.
- The reason `suggest()` is still 7k lines despite all that: the **orchestration core** (security gating, NQE/persona/budget, the grounding/multimodal/CV ladder, ranking) is still inline and **threads shared mutable state** (`payload`, `constraints`, `results`, `kv`, `flags`, `trace_id`) across the whole function. The spaghetti **is** that shared mutable state + ordering coupling + 18 interleaved early-returns + ~182 silent swallows.

**The single most valuable move: migrate the remaining inline blocks of `suggest()` into stages that read/write `SuggestContext`, one block per commit, each guarded by a response-parity test.**

---

## 1. The map — `suggest()` internals (line ranges, current state)

| Lines | Section | Status | Phase |
|---|---|---|---|
| 4216–4302 | entry: args, flags, trace setup | inline | — |
| 4303–4485 | `RECOMMEND_PIPELINE_V2` shadow (non-blocking) | inline (shadow) | — |
| **4486–4831** | **Inventory intent fast-path** (early-exit branch) | **inline** | EXPLORE |
| 4832–4901 | Parallel security analysis (launch) | inline | EXPLORE |
| **4902–5828** | **Join security + Policy Gate + Feature stripping** (~930 ln) | **inline** | EXPLORE/guard |
| 5829–5931 | Buyer persona + budget fitness + budget tier/warranty | inline (calls helpers) | EXPLORE |
| 5932–6005 | Session slot accumulation (NQE-answered fields ↔ Redis) | inline | EXPLORE |
| **6006–6613** | **ShopperIntent extraction + slot merge** (~600 ln) | **inline** | EXPLORE |
| 6614–6757 | Use-Case Advisor enrich + Game/Software requirements | inline (calls helpers) | EXPLORE |
| 6758–6931 | Product Identity Agent (image → identity) | inline | EXPLORE |
| **6932–9404** | **Grounding ladder / multimodal anchoring / CV security-gate** (~2,470 ln) | **inline — THE BIG ONE** | EVALUATE |
| 9405–9421 | Ranking adjustments (use-case, hard-constraint, stock penalty, identity boost, contrastive why) | inline (calls `recommend_ranking`/`product_ranking_agent`) | EVALUATE |
| 9422–10258 | Multimodal anchoring tail + assembly | inline | EVALUATE |
| 10259–10563 | **Intelligence stage** (`run_intelligence_stage`) | ✅ extracted-call | PLAN |
| 10564–10578 | Recommendation finalizer (`recommend_response_finalizer`) | ✅ extracted-call | PLAN |
| 10579–11209 | **Fulfilment stage** (`run_fulfillment_stage`) + narration/decoration | ✅ extracted-call | PLAN/ACTION |
| 11210–11336 | Batch stock annotation + memory write-back + post-pipeline | ✅ mostly extracted-call | ACTION |

**Observation:** the back half (10259→11336, PLAN/ACTION) is already mostly extracted stage-calls. **The un-extracted bulk is the EXPLORE/EVALUATE middle (4486→9421, ~4,900 lines)** — and within it, the **grounding/multimodal ladder (6932–9404)** is ~half.

---

## 2. How it connects (the wiring)

**Inbound:** `main.py:43 from src.app.routers.recommend import router` → `@router.get("/suggest")` (4215) → `suggest()`. The chat router delegates here; the buyer app (`:5173`) and operator paths hit `/suggest`.

**Outbound (what `suggest()` calls):** 200+ services. The 27 already-extracted `recommend_*` stages, plus: `query_decomposer`, `nlp_search_agent`, `candidate_retriever`, `product_ranking_agent`, `fraud_scorer`, the security observer + policy gate, `use_case_advisor`, `product_identity_agent`, `grounding_ladder`, `availability_agent` (→ `inventory_source` → `commerce_catalog`), `market_intelligence_agent`, `ranking_nudge`, `recommend_fulfillment_stage` (→ the procurement subsystem), Redis session memory.

**The shared mutable carrier (the heart of the coupling):** these locals are built early and mutated for thousands of lines:
- `payload` — the response dict (results, assistant_message, availability, fulfillment_case, market_*, security flags…).
- `constraints` — the parsed query plan (budget, order_quantity, use_case, hard_constraints, exclusions, availability_intent…).
- `results` — the ranked product list (re-sorted/penalised/boosted by many blocks).
- `kv` / Redis session state — NQE asked/answered, shortlist, summary.
- `flags`, `trace_id`, `uid`/`uid_hash`, `simulate`.

`SuggestContext` (`suggest_context.py`) is the **intended** carrier for exactly these. Today `suggest()` uses raw locals and only some stages take the context. **Finishing the carrier adoption is the spine of the extraction.**

**4-phase mapping (the orchestrator's EXPLORE→EVALUATE→PLAN→ACTION):** EXPLORE ≈ 4486–6931 (intent, security, persona/budget, NQE, identity), EVALUATE ≈ 6932–9421 (grounding/multimodal + ranking), PLAN ≈ 9422–10578 (intelligence + finalizer), ACTION ≈ 10579–11336 (fulfilment + narration + memory + post-pipeline).

---

## 3. Why it's spaghetti (name the failure modes before touching it)

1. **Shared mutable state across 7k lines.** `payload`/`constraints`/`results` are read and written by dozens of blocks. A change anywhere can be clobbered later. This is the #1 regression source.
2. **Ordering dependencies.** Block B reads a key block A wrote (e.g. ranking reads `constraints['use_case']` set by the Use-Case Advisor; grounding reads security signals set in the join block). Extraction that reorders → silent behaviour change.
3. **18 interleaved early-returns.** Fast-paths `return` mid-function (inventory intent, abstain, off-topic image, zero-result). Extracting code that straddles a fast-path is where bugs hide.
4. **~182 silent swallows.** 301 `except:` lines, only 8 `record_partial_failure` — so a stage can fail and vanish (the class that hid the ASUS grounding bug). The no-silent-except ratchet baselines `recommend.py` at **190** and only ratchets DOWN.
5. **Closure-captured locals.** Nested helpers inside `suggest()` capture its locals — they must move WITH their state or break.
6. **Two code paths (V2 shadow).** `RECOMMEND_PIPELINE_V2` runs a shadow pipeline; parity drift between inline and V2 is a latent trap.

---

## 4. The extraction strategy (incremental, parity-gated)

**Principle:** one inline block → one `recommend_<x>_stage.py` per commit, each taking/returning `SuggestContext` (or its explicit slice), behind a **response-parity test**. Never bulk-move. Each commit stays green and behaviour-identical.

**The seam:** a stage is `def run(ctx: SuggestContext) -> None` (mutates ctx in place) — exactly the established `IntelligenceStageState`/`run_intelligence_stage` shape. Convert `suggest()`'s raw locals into a populated `SuggestContext` at the top FIRST (a no-op refactor, parity-tested), so every subsequent extraction just moves a block that already reads/writes `ctx`.

**Per-extraction recipe:**
1. Identify the block's exact **inputs** (which ctx fields it reads) and **outputs** (which it writes) + any early-return.
2. Move it verbatim into `recommend_<x>_stage.run(ctx)`; replace the inline block with the call.
3. Convert each silent `except: pass` in the moved block to `record_partial_failure(...)` (lower the ratchet baseline — the observability win rides along).
4. Add a stage unit test + run the parity harness. Commit only when byte-identical.

---

## 5. What to extract FIRST — and the ranked queue

**FIRST (prove the harness, lowest risk): the Inventory intent fast-path (4486–4831, ~346 ln).** It's an **early-exit branch** with clean boundaries (reads `query`/`constraints`, either returns an inventory answer or falls through). Fast-paths are the safest first extraction — minimal shared-state threading. Home: `recommend_intent_router.py` (already exists). *Value:* establishes the `SuggestContext` adoption + the parity harness on a contained block.

**SECOND: Security join + Policy Gate + Feature stripping (4902–5828, ~930 ln).** High value (security-critical, currently inline) and moderately bounded (consumes the security verdict, produces the feature allowlist + payload security flags). *Value:* isolates the security-gating decision so it can be tested adversarially in one place.

**THIRD (the big risk-reducer): the Grounding ladder / multimodal / CV security-gate (6932–9404, ~2,470 ln).** The single largest chunk and the one most coupled to image state + security signals + `results`. Do it AFTER the harness is proven and the context is fully adopted, and split it into sub-stages (identity-grounding · multimodal-anchoring · CV-quarantine). *Value:* removes ~35% of `suggest()` and quarantines the anti-hallucination logic that's caused the most subtle bugs.

**THEN:** ShopperIntent/NQE-slot block (5932–6613), persona/budget glue (5829–5931 → `recommend_persona`/`recommend_budget_advisor` already exist as homes), ranking adjustments (9405–9421 → `recommend_ranking`).

> Rationale for the order: a **fast-path** first to build the parity harness cheaply; **security** second because it's high-value and self-contained; the **grounding monster** third because it's the biggest payoff but needs the harness + full context adoption to be safe.

---

## 6. What to test (the parity harness is the enabler — build it before extracting)

1. **Golden-query response-parity corpus** (the critical artifact). 15–20 representative `/suggest` calls covering each branch: plain product query; budget query; bulk B2B ("10 laptops"); image upload (in-domain + off-topic + steg/QR attack); availability ("do you have X?"); compound/multi-intent; zero-result; follow-up/NQE; abstain. For each, snapshot the **full response payload** (normalise out `trace_id`/timestamps/latencies). **Assert byte-identical before vs after each extraction.** This catches ordering + clobber regressions that unit tests miss.
2. **Per-stage unit tests** — each extracted stage tested in isolation with a `SuggestContext` fixture (inputs → asserted outputs), like the existing `recommend_*_stage` tests.
3. **The two ratchets** — `test_no_flavour_in_core` (every extracted stage is agnostic) and `test_no_silent_except_in_core` (extraction must LOWER `recommend.py`'s 190 baseline, never raise it).
4. **Security/grounding regression tests** — re-run the adversarial-image + grounding corpus (the ASUS-grounding and steg/QR cases) after the security and grounding extractions specifically.
5. **Import-time guard** — `suggest()`'s heavy module import is ~6.9s (measured); ensure extraction doesn't add new import-time cost on the hot path (lazy-import inside stages, as the codebase already does).

---

## 7. Regressions / silent hangs / debt to watch

**Regressions:**
- **State read-before-write reordering** — the #1 risk. The parity harness is the defence.
- **Early-return straddles** — moving code across one of the 18 fast-paths drops or duplicates a return.
- **Silent-except masking** — a moved block that swallows now hides its failure elsewhere; convert to `record_partial_failure`.
- **Closure capture** — nested helpers that read `suggest()` locals; move them with their state.
- **V2 shadow drift** — keep the inline and `RECOMMEND_PIPELINE_V2` paths in parity, or the cutover later inherits a discrepancy.
- **Mutable-default aliasing** — `constraints`/`payload` passed by reference; a stage that mutates a shared sub-dict it shouldn't.

**Silent hangs / blocking (audit each extracted stage):**
- The **parallel security join** (4902) — bounded? a hung security task blocks the response.
- **LLM planner / vision calls** in the EXPLORE middle — must carry timeouts (the codebase has `run_async_safe`; use it for any async-from-sync, and bounded `httpx`/LLM timeouts).
- Any `asyncio.run` introduced into the request path — route through `run_async_safe`.

**Tech debt that rides along (convert as you extract, don't do separately):** the ~182 silent swallows → traced failures; the V2 shadow → either promote or delete once stages reach parity; the 18 fast-paths → a single typed `IntentRouter` decision instead of scattered early-returns.

---

## 8. Business impact of the extraction (why it's worth the risk)

1. **Regression blast-radius ↓.** Today *every* feature (NLP, inventory, ranking, security, narration, fulfilment) lands near one 7k-line route, so a change to one silently breaks another — this is the recurring credibility bug this session kept hitting. Stages with clear inputs/outputs **decouple the failure domains**.
2. **Feature velocity ↑.** A new signal/stage becomes a new small module + one call, not surgery inside a 7k-line function. New hires can own a stage without reading the whole monster.
3. **Testability ↑ (the big one).** A 7,120-line function **cannot be unit-tested**; its branches are only reachable through the full route. Extracted stages get fast, deterministic unit tests — turning "hope it didn't regress" into "proven per stage."
4. **Observability ↑.** Each extraction converts silent swallows to traced `record_partial_failure` — the decision trace stops lying about partial failures (directly improves the defensibility story the demo sells).
5. **Unlocks the V2 pipeline cutover.** Once the inline stages match the `recommend_pipeline` scatter-gather stage-for-stage, `RECOMMEND_PIPELINE_V2` can flip from shadow to primary with confidence — the async, parallel, faster path.
6. **Performance headroom.** Stage boundaries make it possible to parallelise EXPLORE (security ∥ NLP ∥ vision) and cache EVALUATE — currently impossible to reason about inside one function.

**Bottom line:** the first extraction (the inventory fast-path + the parity harness) is ~1 focused session and buys the **harness** that makes every later extraction safe. The grounding-ladder extraction (third) is where the bulk of the risk-reduction lands. None of it should be bulk-done; the value is in the **parity-gated, one-stage-per-commit discipline.**

---

## 9. Concrete first move (next session)
1. Build the **golden-query parity harness** (`tests/parity/test_suggest_response_parity.py`) capturing the current `/suggest` payloads for the 15–20 corpus queries.
2. Populate a `SuggestContext` at the top of `suggest()` from the existing locals — **no behaviour change**, parity-green (this is the spine every later extraction rides).
3. Extract the **Inventory intent fast-path** (4486–4831) into `recommend_intent_router.run_inventory_fastpath(ctx)`; replace inline; convert its swallows to `record_partial_failure`; lower the ratchet baseline; parity-green; commit.
4. Repeat for security (4902–5828), then the grounding ladder (6932–9404) split into sub-stages.
