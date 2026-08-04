# Core Extraction & Portability Roadmap — deep dive (2026-06-20)

**Goal**: turn `recommend.py` from a 12,176-line monolith into a thin orchestrator (<5k, ideally
<4k) over a **portable, vertical-agnostic recommend engine**, where the only per-vertical surface
is `config/store_profiles/*.json`.

This document: (1) verified current state, (2) the phase-extraction map with line math, (3) **5
new things to add** to make excision + agnosticism faster/safer, (4) **file consolidation** for
portability, (5) iterative test strategy, (6) **adversarial critique** of this very plan.

---

## 1. Verified current state

- `recommend.py`: **12,176 lines, 115 functions**. `suggest()` alone = **7,433 lines (61%)**.
  Peak was **14,748** (2026-06-18); ~2,573 removed (~17%).
- Decomposition so far: **15 `recommend_*` service modules** (~5,400 lines), **16 lint-enforced
  core modules**, **47 adapter slots** per StoreProfile, **SuggestContext carries all 7 hidden
  dicts** (constraints, timing_breakdown, image_context, kv_out, structured_state_out, nlp,
  fraud_summary).
- Engine modules (vertical-blind): category_router (292), product_taxonomy (178),
  product_identity_agent (472), query_decomposer (434), recommend_persona (147),
  recommend_ranking (299), recommend_candidate_classify (190), recommend_utils (274),
  use_case_advisor (652), product_classifier (207).
- Guardrails: golden contract test (5 shapes), no-flavour lint, silent-except ratchet.

**The blocker is gone**: SuggestContext threads the shared state, so phases can finally be lifted.

---

## 2. The phase-extraction map (how to reach <5k)

`suggest()` (L4066–L11498) decomposes into these phases (seams verified from section markers +
the 19 early-returns):

| # | Stage module | suggest() span (approx) | ~lines | ctx fields touched | risk |
|---|---|---|---|---|---|
| S1 | `stages/security.py` (gate, parallel security analysis, fraud, rate-limit) | L4446–L5316 | ~700 | image_context, analysis, guard, fraud_summary, timing | LOW (write-mostly; 4 early-returns) |
| S2 | `stages/constraints.py` (NLP, constraints build, persona, budget tier, slot accumulation, use-case advisor, game/SW enrich) | L5470–L6644 | ~1,200 | nlp, constraints, kv, structured_state | **HIGH** (constraints mutation core) |
| S3 | `stages/identity.py` (product identity agent + grounding ladder) | L6645–L6888 | ~250 | image_context, constraints | LOW |
| S4 | `stages/nqe.py` (open-ended early-return + post-retrieval; merge with recommend_nqe_stage) | L7464–L7600 + L10180+ | ~400 | constraints, nlp, kv, structured_state | MED (2 early-returns; builder already shared) |
| S5 | `stages/retriever.py` (candidate retrieval + price/brand/Windows DB fallbacks) | L7686–L9300 | ~1,600 | constraints, results, candidates | MED (8 early-returns, complex fallbacks) |
| S6 | `stages/ranking.py` (stock penalty + rerank + use-case adj) | L9309–L9590 | ~300 | constraints, results, nlp | LOW |
| S7 | `stages/memory.py` (episodic memory + kv_out/structured_state_out writeback) | L9592–L9640 + L11133–L11230 | ~300 | kv_out, structured_state_out, constraints | LOW (write-mostly) |
| S8 | `stages/narration.py` (price summary, payload assembly, finalize; extend recommend_narration_stage) | L10153–L11498 | ~1,400 | results, constraints, fraud_summary, all outputs | MED (the frontend contract surface) |

**Line math:** S1–S8 remove **~6,150 lines** from `suggest()` → it shrinks 7,433 → **~1,300**
(pure orchestration + the early-return wiring). → **recommend.py ≈ 6,000**.

Then move the big standalone helpers into their owning stages (`_summarize_results` 373 →
narration; `_fast_path_catalog_recommendation` 493 → a fast_path stage; `_build_context_preamble`
129, `_resolve_nqe_product_category` 105, `_top_up_image_results` 101, `_infer_use_case_from_query_text`
101 → constraints/nqe) = **~1,800–2,500 lines** → **recommend.py ≈ 3,500–4,200**. ✅ **<5k, → <4k.**

**Extraction sequence (lowest-risk first):**
0. **Reader-migration sweep** — repoint `suggest()`'s reads of the 7 locals to `ctx.*` (mechanical, no behaviour change; do per-field, golden-test each).
1. S7 memory → 2. S1 security → 3. S6 ranking → 4. S3 identity → 5. S8 narration → 6. S5 retriever → 7. S4 nqe → 8. **S2 constraints last** (riskiest).

Each step: lift the phase into a `def run_X_stage(ctx) -> ctx`, replace the inline block with the
call, run golden + full regression + ratchet, commit. ~10–12 commits.

---

## 3. Five things to ADD (make excision + agnosticism faster & safer)

### A1. A uniform **Stage protocol + pipeline runner**
`Stage = Callable[[SuggestContext], SuggestContext]`. A `run_pipeline(stages, ctx)` that wraps each
stage in `safe_stage` (trace-visible partial failure), times it into `ctx.timing_breakdown`, and
honours an **early-return protocol** (`ctx.halt: bool` + `ctx.response: dict` — a stage sets them,
the runner stops and returns). This turns the 19 scattered `return _with_trace(...)` into one
explicit, testable control mechanism and makes every stage independently unit-testable.
*New file:* `recommend/pipeline.py`. *Risk:* the early-return protocol is the crux — see Critique #2.

### A2. A **Profile JSON Schema + load-time validator (CI gate)**
A formal `config/store_profiles/_schema.json` describing all 47 slots (types, required-ness).
`get_store_profile()` validates on load (dev/CI strict, prod warn). A new vertical becomes a
**fill-in-the-blanks** exercise with instant feedback, and a typo'd slot fails fast instead of
silently degrading. *New:* `_schema.json` + `tests/test_store_profile_schema.py`.

### A3. A **profile parity linter**
Assert every profile (electronics/pharmacy/fashion/…) defines the same **required** slot set (the
~20 that gate a working vertical: manufacturers, product_type_rules, persona_patterns,
ranking_rules, spec_extraction_rules, nqe_question_packs, …). This kills the exact failure mode
Phase 2A fixed — a half-working second vertical that silently misses a slot. *New:*
`tests/test_profile_parity.py` (parametrized over all profiles × required slots).

### A4. A **ctx-access static analyzer** (extraction de-risker)
A dev script that parses `suggest()` and reports, per candidate phase span, which `ctx.*` /
local-dict fields are **read vs written**. This *mechanically derives safe stage boundaries* and
flags hidden coupling (a field written in S5 but read in S2 = a reorder hazard) BEFORE you lift the
code. *New:* `scripts/ctx_access_map.py`. Pure static analysis, no runtime.

### A5. A **per-stage characterization (record/replay) harness**
Instrument a few real runs to capture each stage's `(ctx_in → ctx_out)` as fixtures; replay them as
byte-parity tests on every extraction. Converts "did I break it?" into a mechanical diff and covers
the **14 early-return paths the 5-shape golden test misses**. *New:* `scripts/record_stage_io.py` +
`tests/stages/test_stage_characterization.py`.

> Net: A1 makes extraction *mechanical*, A4+A5 make it *safe*, A2+A3 make a *new vertical* a
> validated config exercise. Build A4+A5 **before** S2/S5 (the high-risk lifts).

---

## 4. File consolidation for portability

Today the engine is ~21 files scattered in `services/`. For a liftable core, group by role into a
`recommend/` package; the ONLY per-vertical surface stays `config/store_profiles/*.json`:

```
src/app/recommend/
  context.py              ← suggest_context.py
  pipeline.py             ← NEW (A1) + recommend_pipeline.py
  stages/                 ← S1..S8 (extracted)
    security.py  constraints.py  identity.py  nqe.py
    retriever.py  ranking.py  memory.py  narration.py
  engine/                 ← vertical-blind primitives (already agnostic)
    persona.py  ranking_rules.py  candidate_classify.py  budget.py (advisor+parsing)
    category_router.py  product_taxonomy.py  product_identity.py
    query_decomposer.py  use_case_advisor.py  product_classifier.py  utils.py
  adapters/  → (pointer doc) config/store_profiles/*.json
src/app/platform/         ← store_profile*.py, tenant_registry.py (the selector; stays)
```

**Portable unit** = `recommend/` + `platform/store_profile*` + `config/store_profiles/` + the
StoreProfile contract. To embed in another app you copy those three.

**Caveat (do this LAST):** moving 21 files = updating dozens of import sites + test imports. It is
pure churn with regression risk and **zero functional gain** until portability is actually needed.
Logical naming already gives 80% of the benefit. Recommendation: do consolidation **after**
extraction, as one mechanical `git mv` + import-rewrite pass with the suite as the net — or defer.

---

## 5. Iterative test strategy

- **Every commit**: `tests/test_recommend.py tests/services/ tests/test_no_flavour_in_core.py
  tests/test_no_silent_except_in_core.py tests/integration/test_recommend_contract_stability.py`
  — the ratchet MUST be in every run (it has caught regressions twice).
- **Per extraction**: parity grid (old inline vs new stage over representative inputs) + the
  characterization fixtures (A5) for the early-return paths.
- **Per new vertical**: the 3-vertical no-bleed suite + profile parity (A3) + schema (A2).
- **Latency**: `scripts/bench_recommend.py --url <live>` before/after any latency claim.

---

## 6. Adversarial critique (red-team this plan)

1. **"Is a second vertical actually coming?"** The agnostic demarcation only pays off if
   pharmacy/fashion ship. If not, it's gold-plating a monolith. → *Mitigation:* the demarcation
   ALSO improves testability/maintainability of electronics; but be honest that ~half the value is
   contingent on a 2nd vertical landing.
2. **Early-returns break the clean `ctx → ctx` model.** `suggest()` has **19 early returns**
   interleaved through phases; a stage that can terminate the request is not a pure transform. The
   pipeline runner's halt protocol (A1) must be EXACTLY right across all 19 — and the golden test
   only covers 5 shapes. This is where extraction regressions will hide. → *Mitigation:* A5
   characterization fixtures for every early-return path BEFORE S5/S2.
3. **SuggestContext is a god-object.** Threading one mutable bag re-creates shared-mutable-state
   behind a dataclass; stages can still stomp each other's fields. We may have *moved* the coupling,
   not removed it. → *Mitigation:* A4 access-map to prove which stage owns which field; longer term,
   per-stage typed inputs/outputs (not one bag).
4. **Characterization pins behaviour INCLUDING bugs.** Byte-parity extraction faithfully freezes
   latent bugs (the memory notes list several). Parity ≠ correctness. → *Accept consciously:*
   separate "extraction (parity)" commits from "behaviour fix" commits; never mix.
5. **The "agnostic core" still ships electronics inline.** `recommend_ranking` /`recommend_utils`
   keep the full electronics scorer/extractor as *fallback*. So the core is flavour-*defaulted*, not
   flavour-*free*. Claiming "agnostic" is overstated until electronics is ALSO just a profile with
   zero inline electronics. → *Decide:* either finish the migration (electronics → rules) or rename
   the claim to "adapter-driven with an electronics default."
6. **The real UX problem is untouched.** Latency: LLM narration is **4.5s p50 / 15s p95** — the
   actual user pain — while this whole effort reorganizes code. A critic says ship narration
   streaming/skip FIRST. → *Mitigation:* the demarcation doesn't block latency work; sequence a
   narration-streaming spike alongside.
7. **File consolidation is churn for marginal gain.** 21 file moves touch dozens of imports for no
   behaviour change; if portability isn't imminent it's not worth the regression surface. → covered
   in §4: defer or do last.

**Verdict from the critic:** the *extraction* (shrink the monolith) is unambiguously worth it —
maintainability + testability. The *agnostic* half is worth it **iff a 2nd vertical ships**, and is
currently *overstated* (electronics still inline). And **latency is the neglected real-user issue.**

---

## 7. Recommended sequence

1. **A4 (ctx access-map)** + **A5 (characterization harness)** — build the safety net for extraction (1–2 days).
2. **Reader-migration sweep** (point `suggest()` reads at `ctx.*`).
3. **S7→S1→S6→S3** (low-risk stages) — proves the pattern, ~4 commits, recommend.py ≈ 10k.
4. **A1 (pipeline runner)** once 3–4 stages exist and the early-return protocol is clear.
5. **S8→S5→S4→S2** (the big/risky lifts) — recommend.py → <5k.
6. **A2 + A3** (profile schema + parity) — lock the adapter surface; de-risk vertical #2.
7. **Helper sweep** → <4k. **File consolidation** (§4) last, or defer.
8. **Parallel track (not blocked by above):** narration latency (Critique #6) + finish electronics→profile (Critique #5) if "fully agnostic" is the goal.
