# ShopSquire — Agnostic-Core Deep Dive & Refactor Roadmap (2026-06-18)

Audience: ShopSquire eng + GPT-5.5 code review.
Scope: portability to other verticals, upsell, question decomposition, vision/cross-modal,
deterministic-vs-LLM boundary, CPU-vs-GPU economics, silent fails, and the ordered plan to
shrink/refactor `recommend.py` without scope creep.

Ground truth (measured 2026-06-18): 103 routers, 215 services, 125 security modules.
`recommend.py` = 14,661 lines; `suggest()` = ~7.7k of them. `orchestrator.py` = 4,009 lines,
241 `except`. **4,393 `except Exception:` blocks across `src/app`** (112 debug-hidden,
155 `return []`-in-except). Two store profiles wired through one loader: electronics + pharmacy.

---

## 0. TL;DR — are we going the right direction?

**Yes, the direction is right; the sequencing needs discipline.** The moat is correct:
*policy-bounded AI decisions with evidence + audit, on top of commodity commerce*. The
strangler-fig extraction (finalizer → checkout-handoff stage → StoreProfile slots) is the
correct mechanism and is working. What's missing is **breadth of wiring**: the profile schema
already defines the slots, but core modules still carry their own hardcoded copies of the
flavour. So we have an agnostic *spine* with electronics *bleed* in ~8 high-traffic modules.

The single most important framing: **there is no second vertical until the flavour that a
second vertical would have to fork is gone.** Pharmacy "passes" the loader test today, but it
would mis-behave the moment it hit `score_query_complexity` (scores on `rtx`/`240hz`),
`upsell_engine` (gaming peripherals), `cv_triage_basic` (off-topic gate keyed to electronics
tokens), or `query_decomposer._extract_hard_constraints` (refresh_hz/gpu/ram regex). These are
the real portability blockers — not `recommend.py`'s line count.

**No full re-architecture.** A rewrite throws away the moat (the audit trail, the security
agents, the bitemporal decision log) to fix a layering problem that strangler-fig already fixes
incrementally. Keep shipping; extract the spine.

---

## 1. Portability blockers — the flavour still in CORE (ranked by blast radius)

Each row is core *mechanism* contaminated with electronics *flavour*. The fix is identical
every time: read the values from `StoreProfile`, keep an inline `_FALLBACK` for parity, add the
module to the no-flavour lint once clean.

| # | File:line | Flavour in core | Why it blocks a 2nd vertical | Profile slot |
|---|---|---|---|---|
| P1 | `services/llm_provider.py:75-94` | `TECHNICAL_KEYWORDS` (rtx, vram, 240hz, dlss…), `_USE_CASE_HIGH` (gaming/cad…) | Model-tier routing mis-scores every non-electronics query → wrong model, wrong cost | `complexity_keywords` (new) |
| P2 | `services/query_decomposer.py:200-231` | `_extract_hard_constraints` (refresh_hz/gpu/ram/storage/esports regex) | Sub-question constraint extraction yields nothing for pharmacy/apparel | `spec_extractors` (new) |
| P3 | `services/upsell_engine.py:33-50` | `_USE_CASE_CROSS_SELL`, `_USE_CASE_RE` | Cross-sell suggests gaming mice for a pill order | `upsell_companions` (EXISTS, unwired) |
| P4 | `services/cv_triage_basic.py:115-236` | `_ELECTRONICS_TOKENS`, `_FOOD_PRODUCE_TOKENS`, `_PRODUCT_TYPE_MAP`, `DAMAGE_KEYWORDS` | "Off-topic image" gate flags a legit pharmacy photo; damage taxonomy is laptop-only | `cv_returns_pack` (EXISTS, unwired) |
| P5 | `flows/nqe.py` (corp gen 640-661, `_template_field_map` ~945) | Question templates phrased for laptops | Asks "gaming or office?" in a pharmacy | `nqe_question_templates` (partial) |
| P6 | `routers/recommend.py` (persona ~1741, brand-budget text ~5089-5147) | Persona vocab + brand-budget answer copy | English copy assumes laptops | `persona_vocab`, `budget_copy` (new) |

**Observation that matters:** P3 and P4 slots **already exist in the profile JSON** — the
schema got ahead of the wiring. Those two are pure "switch the module to read the slot" work
with zero schema design. Do them first; they're the cheapest proof that the pattern scales
beyond `recommend.py`.

---

## 2. Upsell — how it works, and its honest state

`get_upsell_candidates()` ([upsell_engine.py:232](src/app/services/upsell_engine.py#L232)) runs
three signals, best-to-weakest:

1. **Co-purchase affinity** (`orders_items` self-join, [:81](src/app/services/upsell_engine.py#L81)) — *agnostic, deterministic, the real signal.* Works for any vertical with order history. Keep as core.
2. **Use-case category expansion** ([:145](src/app/services/upsell_engine.py#L145)) — **a documented silent fail.** The demo schema has no `category` column, so this SQL "usually returns nothing" (the code comment says so at :254). Electronics-flavoured *and* dead.
3. **Companion-type expansion** ([:197](src/app/services/upsell_engine.py#L197)) — uses `product_classifier` to map laptop → bag/monitor/audio. This is the path that actually fires. Agnostic-ish but the classifier carries fallback flavour.

**Verdict:** good bones (co-purchase is the right primitive), but the middle signal is dead
weight and the cross-sell map is hardcoded. Fix = remove the dead category path, move the
companion map to `upsell_companions` (slot exists), keep co-purchase as core. This is a ~1-hour
change and removes a whole class of "why is upsell empty" debugging.

**Cold-start gap:** co-purchase needs order history a new store won't have. The profile should
carry a `seed_companions` map (type→type) so day-one upsell works before any orders exist. The
companion-type path already approximates this; just make it profile-driven.

---

## 3. Question decomposition — "smarter sub-questions before the LLM"

Today there are **two unconnected deciders**:

- **`query_decomposer`** decides what to *extract* (`QueryPlan` → `SubQuestion[]`,
  [:125-174](src/app/services/query_decomposer.py#L125)). It splits compound queries
  ("is $1400 enough for uni *and* which is better, X or Y?") into atomic sub-questions and
  pulls hard constraints. The **splitting is agnostic and good**; the **constraint extraction is
  electronics regex** (P2).
- **`flows/nqe.py`** decides what to *ask next* (missing-slot → next question).

They don't share a model of "what do we know / what's missing / what to ask." That's the real
decomposition gap. The fix is a single **`QueryUnderstanding`** struct that both produce into
and read from:

```
QueryUnderstanding = {
  intent, use_cases[],                      # decomposer
  known_slots{}, missing_slots[],           # derived from spec_extractors (profile)
  sub_questions[],                          # decomposer (compound split)
  next_ask: NQEQuestion | None,             # NQE, chosen from missing_slots
  answer_without_products: bool
}
```

Then the LLM prompt is built from `QueryUnderstanding`, not raw text — it gets "user wants a
gaming laptop, knows budget=$1400, missing=[refresh_rate, portability], comparing=[4060,4070]"
instead of a sentence. **That** is what makes the LLM "smarter": you do the deterministic
decomposition first and hand it a filled-in form. The pieces exist; they're just not unified or
profile-driven. This is medium effort and high payoff, but it is **phase 2** — do not start it
until P1-P4 flavour excision lands, or you'll be unifying flavour you're about to move.

---

## 4. Vision — unrelated vs *adjacent* images (the real gap)

Current handling is **binary**: `image_relevance ∈ {relevant, off_topic}`, decided by whether
labels intersect `_ELECTRONICS_TOKENS` ([cv_triage_basic.py:133-146](src/app/services/cv_triage_basic.py#L133)).
This has two defects:

1. **Off-topic is keyed to a hardcoded electronics set** (P4) — non-portable.
2. **There is no "adjacent" state.** If a buyer uploads a laptop photo but asks about a *bag for
   it*, that's not off-topic and not "find me this laptop" — it's adjacent. Today it collapses
   to "relevant" and the image silently steers ranking toward laptops, fighting the text.

Proposed three-state model (profile-driven, agnostic):

| State | Definition | Action |
|---|---|---|
| `on_topic` | image product-type ∈ profile primary_types **and** consistent with text intent | image constrains ranking (anchor specs) |
| `adjacent` | image type ∈ store catalog but ≠ text intent type | image informs *context* (compatibility/companion), text drives ranking |
| `off_topic` | image type ∉ store catalog | warn, ignore image, rank on text only |

The classification input is the **same `_detect_product_type`** that exists — but the token
sets come from the profile, and the relationship (on/adjacent/off) is computed against
`profile.primary_types` + the decomposed text intent, not a frozenset. This directly answers
"image unrelated or adjacent to text" and is the highest-value vision change.

**Security invariant unchanged:** decoded QR/steg/OCR text is *data*, never instruction — it
informs the relevance decision but never reaches the ranking signal or the LLM prompt as a
directive. (Already the rule; keep it.)

---

## 5. Deterministic vs generic-LLM vs custom-LLM — the boundary

The platform's defensibility *is* this boundary. Get it explicit. Three lanes:

| Lane | Owns | Examples | Who can swap it |
|---|---|---|---|
| **Deterministic core** | anything consequential or auditable | policy `decide()`, fail-closed authority matrix, price/stock gates, fraud thresholds, candidate retrieval + RRF merge, the finalizer | **nobody** — this is the moat; same for every tenant |
| **Generic LLM (interpretation)** | language → structure, structure → language | intent parsing, summary copy, persona phrasing, NQE wording | ShopSquire (model choice via tier ladder) |
| **Custom / tenant LLM (BYO)** | tenant-specific taste & domain voice | a pharmacy's compliance-tone copy, a fashion brand's styling reasoning, owner's own fine-tune | the **store owner** |

Design rule: **the LLM proposes, the deterministic core disposes.** An LLM (generic or tenant's
own) may *infer* and *phrase*; it may never *decide* a refund, a price, a stock commit, or a
fraud disposition (David's rule). That means the BYO-LLM seam is safe to offer: a tenant can
plug their own model into the *interpretation* lane via a `LLMProvider` port without ever
touching the decision lane. Concretely:

- Make `llm_provider` an interface (`generate`, `score_complexity`, `embed`) with the current
  Ollama impl as the default adapter. A tenant supplies `OpenAIAdapter` / `BedrockAdapter` /
  their own endpoint. The **tier ladder + complexity scoring stay in core** (they're routing
  policy, not model internals) but read keywords from the profile (P1).
- The decision lane (`policy/execution_gate.py`, authority matrix) **never** calls a tenant
  model. Audit stays trustworthy regardless of whose LLM phrased the answer.

This is also the commercial story: "bring your own model and your own catalog; you cannot bring
your own policy bypass."

---

## 6. CPU vs GPU — push the cheap lane hard

Current tiers ([tier_ladder.json](config/ml/tier_ladder.json)):
nano (no LLM) → small `qwen3-vl:8b` → medium `qwen3:14b` → large/expert `qwen3.6:27b`.
Everything above nano implies a GPU host. The economics win is **maximising the share of
traffic that never needs a GPU**, and **separating the always-on cheap services from the
on-demand GPU pool**.

Two-pool architecture:

```
 CPU pool (always-on, cheap, horizontal)        GPU pool (autoscale 0..N, expensive)
 ───────────────────────────────────────         ──────────────────────────────────
 • retrieval (pgvector/HNSW, BM25, RRF)           • VLM image reasoning (small tier)
 • policy decide() + authority matrix             • 14B/27B text reasoning (med/large)
 • finalizer, price/stock gates                   • embedding backfill (batch, queue)
 • complexity scoring (it's regex!)               • thinking-mode chain-of-thought
 • upsell (SQL), fraud signals (mostly)
 • embedding LOOKUP (vectors precomputed)
 • NQE next-question (deterministic)
```

Levers, in order of ROI:

1. **Make nano-tier do more.** Today nano = score ≤2. A large fraction of commerce queries are
   filterable retrieval ("laptops under $1500 in stock") that need *zero* LLM — deterministic
   retrieval + the finalizer already produce a good answer. Route these to a **CPU
   answer-composer** (templated, profile-driven copy) instead of a model. Target: 50-70% of
   queries answered with no GPU call. This is the single biggest cost lever and it's mostly
   wiring `answer_composer` (already core, already flavour-free) onto the nano path.
2. **Embeddings: compute on GPU in batch, serve from CPU.** Query-time embedding of a short
   query is cheap on CPU (or precompute common ones). Keep `embedding_pipeline` as a queued GPU
   batch job; never block a request on GPU embedding.
3. **Small VLM only when an image is actually present and on/adjacent-topic** (§4). An off-topic
   image should *not* spend a VLM call — the relevance gate can run on CPU labels first.
4. **GPU pool scales to zero.** With (1) holding the floor, the GPU pool is bursty; run it as a
   separate autoscaling service (or serverless GPU) behind a queue, so idle cost ≈ 0.

Wiring: the seam is already there — `llm_provider` is the only thing that talks to Ollama. Put
the CPU/GPU decision in `_tier_for_score`: nano → CPU composer, small+ → GPU provider. Add a
`LLM_GPU_POOL_URL` distinct from `OLLAMA_URL` so the two pools are independently scalable.

---

## 7. Silent fails — the 4,393-handler problem

`except Exception:` appears **4,393×** in `src/app`; 112 hide the error at `debug` level; 155
`return []` from inside the handler. For a recommender this is the worst failure mode: a crash
in retrieval returns "no products found", indistinguishable from a genuine empty result. The
buyer sees a shrug; the logs (at INFO) say nothing.

This is not "add try/except discipline everywhere" — it's **three targeted rules**:

1. **Distinguish empty-by-data from empty-by-error.** Any `except: return []` on a retrieval/
   scoring path must instead return a sentinel that the response layer can surface as
   "degraded" (a `partial_failure` flag on the payload, already have `timings.scatter_timeouts`
   precedent). The buyer still gets a graceful answer; the *trace* records the failure.
2. **Promote the 112 `log.debug`-in-except on consequential paths to `log.warning` with the
   trace_id.** Debug-level in prod = invisible. One-line changes, huge observability gain.
3. **Add a "degraded response" counter** to metrics so silent degradation becomes a dashboard
   number, not a customer complaint.

Do **not** try to remove the 4,393 handlers — most are correct defensive boundaries. Triage to
the ~50-80 on the request-critical path (retrieval, ranking, finalizer, policy) and fix those.
A grep-based audit of `except` within `recommend.py`/`recommend_pipeline`/`candidate_retriever`/
`orchestrator` is the scoped target.

---

## 8. Do we need to re-architect? No — extract the spine.

A rewrite is the wrong call: it discards the moat (audit trail, security agents, bitemporal log)
to fix a *layering* problem. The right model is already in motion — make it explicit:

```
                         ┌─────────────────────────────────────────┐
   request ──▶  PORTS ──▶│  AGNOSTIC CORE (vertical-blind)          │──▶ AUDIT
                         │  retrieve · rank · decide() · finalize   │
                         │  complexity-route · NQE-mechanism        │
                         └──────────────┬──────────────────────────┘
                                        │ reads
                         ┌──────────────▼──────────────┐
                         │  STORE PROFILE (flavour)     │  electronics.json / pharmacy.json
                         │  brands · specs · use-cases  │
                         │  upsell · cv-pack · copy     │
                         └─────────────────────────────┘
   PORTS (swap per tenant, never touch core):
     CatalogPort · InventoryPort · LLMProvider · EmbeddingPort · LoyaltyPort · CDPPort · WarehousePort
```

- **Core** = the 9 lint-guarded modules + the stage pipeline we're extracting from `suggest()`.
- **Profile** = JSON, one per vertical, loaded by `platform/store_profile.py`.
- **Ports** = thin interfaces for everything external (catalog, inventory, LLM, embeddings,
  loyalty, CDP, warehouse). Loyalty (Everyday Rewards/Flybuys/Kroger/Nectar), CDP
  (Segment/mParticle), warehouse (Snowflake/Databricks/Athena) are **all just adapters behind
  ports** — they never change core. This is the answer to "external data without bleeding into
  core": a `LoyaltyPort.get_tier(customer)` returns a normalized struct; the adapter knows it's
  Flybuys; core only sees "tier=gold".

No new framework, no rewrite. The work is: finish flavour excision (P1-P6), keep extracting
`suggest()` stages, and formalize the existing external integrations as ports.

---

## 9. Shrinking `recommend.py` — the concrete path to < 7k

`suggest()` is 7.7k of the 14.6k. You cannot reach <7k by trimming; you reach it by
**decomposing `suggest()` into a stage pipeline behind `RecommendContext`** (pattern already
proven by the checkout-handoff extraction, commit `292a2b4`). Order leaves-first (no downstream
consumers = safest), each behind characterization parity + the stash-baseline regression check:

| Order | Stage (seam) | ~lines | Risk | Notes |
|---|---|---|---|---|
| ✅ done | checkout-handoff (13979) | 30 | low | proven the pattern |
| 1 | price-advisory / budget answer (5089-5147, 6164) | ~250 | low-med | pure text builder, profile copy (P6) |
| 2 | batch-stock annotation (7312) | ~120 | low | pure transform over results |
| 3 | persona humanization (5961) | ~180 | med | move vocab to profile (P6) first |
| 4 | use-case enrichment (8813) | ~200 | med | reads profile use_cases |
| 5 | product-identity (8957) | ~300 | med | already a service; inline glue only |
| 6 | grounding ladder (9154) | ~400 | high | anti-hallucination — most care |
| 7 | NQE slot-merge (8131-8273) | ~350 | high | touches Redis + the corp bug |

After stages 1-5: `suggest()` ≈ 6.3k, file ≈ 13k. After extracting the big standalone builders
(`_fast_path_catalog_recommendation` 493, `_summarize_results` 367, `_build_brand_budget_answer`
227) into services: file ≈ 11-12k, `suggest()` ≈ 5k. **The <7k target is the file's
orchestration spine once builders + stages are services.** This is mechanical, parity-tested,
and already de-risked.

---

## 10. The order of operations (no scope creep)

Strict sequence. Each phase is independently shippable and reversible. **Do not start a phase
before the prior one's lint/tests are green.**

**Phase A — finish flavour excision (unblocks verticals; cheapest).**
A1. Wire `upsell_companions` slot → `upsell_engine` (P3, slot exists). Delete dead category path.
A2. Wire `cv_returns_pack` slot → `cv_triage_basic` tokens (P4, slot exists).
A3. Add `complexity_keywords` slot → `llm_provider` (P1).
A4. Add `spec_extractors` slot → `query_decomposer._extract_hard_constraints` (P2).
A5. Each: inline `_FALLBACK` + parity test + add module to no-flavour lint.
→ Exit bar: pharmacy profile drives upsell, CV relevance, complexity, and spec extraction with
zero electronics literal in those four modules.

**Phase B — continue `suggest()` stage extraction (shrinks the monolith).**
B1-B5. Stages 1-5 from §9, leaves-first, parity + stash-baseline each.
→ Exit bar: `suggest()` < 6.5k, file < 13k, all stages flavour-clean.

**Phase C — vision 3-state + silent-fail triage (quality).**
C1. `on_topic/adjacent/off_topic` model (§4), profile-driven.
C2. Promote 112 debug-in-except on critical path to warning+trace_id; add `partial_failure` flag.
→ Exit bar: adjacent-image case handled; degraded responses are observable.

**Phase D — ports + BYO-LLM (commercial breadth).**
D1. `LLMProvider` port (Ollama default adapter); tier ladder stays core.
D2. CPU/GPU pool split in `_tier_for_score`; nano → CPU answer-composer.
D3. Loyalty/CDP/Warehouse ports (adapters only; core untouched).
→ Exit bar: a tenant can BYO model + plug a loyalty source without touching core.

**Phase E (deferred, only after A-D):** unify `QueryUnderstanding` (§3), `orchestrator.py`
decomposition, corp post-NQE drop fix.

**Scope-creep guard:** A and B in parallel are fine (different files). C depends on A2 (CV
profile). D depends on A3 (LLM keywords in profile). E depends on everything. Never pull an E
item forward to "while I'm in here" — that's exactly how the monolith formed.

---

## 11. Brief for GPT-5.5 review

Ask GPT-5.5 to pressure-test, with files in hand:

1. **Boundary correctness** — is the core/profile/port split in §8 the right cut? Specifically:
   should `complexity scoring` and the `tier ladder` be core (routing policy) or pushed to a
   port? (We argue core; challenge it.)
2. **`QueryUnderstanding` unification (§3)** — is one struct shared by decomposer + NQE the
   right design, or does it over-couple two concerns that should stay separate?
3. **Vision 3-state (§4)** — is `adjacent` worth the complexity, or is a confidence-weighted
   single signal simpler and sufficient?
4. **CPU/GPU split (§6)** — is "nano → CPU composer" achievable for 50-70% of traffic without
   tanking answer quality? What's the quality floor below which it backfires?
5. **Silent-fail triage (§7)** — is the `partial_failure` sentinel + critical-path-only fix the
   right scope, or is broader handler discipline warranted?
6. **Ordering (§10)** — does the A→E sequence have a hidden dependency that forces a reorder?
7. **Stage extraction risk (§9)** — flag any of stages 6-7 (grounding, NQE-merge) where
   characterization parity is insufficient and behavioural tests are mandatory.

Provide GPT-5.5: this doc, `platform/store_profile.py`, `config/store_profiles/*.json`,
`services/llm_provider.py`, `services/upsell_engine.py`, `services/cv_triage_basic.py`,
`services/query_decomposer.py`, `tests/test_no_flavour_in_core.py`, and the `suggest()` seam map
(§9 table). Ask for a yes/no on each numbered question plus the single highest-risk item.
