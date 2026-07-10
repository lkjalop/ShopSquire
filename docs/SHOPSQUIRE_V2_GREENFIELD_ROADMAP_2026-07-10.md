# ShopSquire V2 Greenfield Roadmap — recommend.py / suggest() rebuild with a live revert path
**Date:** 2026-07-10 · **Status:** APPROVED DIRECTION (hybrid: greenfield core behind frozen contract, legacy as shadow oracle) · **Inputs:** GPT-5.6 Sol dependency map + corrected T0–T8 taxonomy epic; comprehensive deep-dive `docs/SHOPSQUIRE_COMPREHENSIVE_DEEPDIVE_2026-07-10.md`

---

## 0. Strategy in one paragraph

Build the new recommendation **core** as a fresh in-process package (`recommendation_core/`) on top of a **unified catalog read-model (T0)** and a **grounded sold-taxonomy (T1)**, behind the **frozen `/suggest` contract**. Run it **in shadow** beside the legacy `suggest()` with a full-response differ, promote **shadow → canary → primary** on measured parity, and keep legacy **archived-but-runnable** behind one env flip for instant revert. This is not a new invention: the exact ladder already exists in this repo and is live-proven for the retrieval leg (`RECOMMEND_RETRIEVAL_MODE=shadow|fusion|primary`). V2 extends that discipline from "candidates" to "the whole response."

**The design rule (GPT-5.6, adopted verbatim):** *the model maps unbounded merchant/shopper language to bounded taxonomy candidates; deterministic code validates the node, attributes, merchant approval, and sellability.* The model never invents a SKU, a price, a policy, or an authorization.

---

## 1. Ground truth — what already exists (the reuse map)

### 1a. The safeguard machinery — ALREADY BUILT AND PROVEN
| Asset | File | Role in V2 |
|---|---|---|
| Scatter-gather V2 skeleton | `src/app/services/recommend_pipeline.py` (346 ln) | **The seed of the new core.** 4-stage scatter-gather (parallel DB/vector/fraud/inventory/CV → RRF merge → conditional deepening → NQE/summarize/assemble), per-leg timeout budgets, already shadow-wired. Promote it into `recommendation_core/`, don't duplicate it. |
| Mode ladder | `src/app/services/recommend_retriever_stage.py` | `RECOMMEND_RETRIEVAL_MODE=shadow\|fusion\|primary`, default shadow, promotion gated on live parity. **This is the revert pattern V2 copies for the full response.** |
| Parity measurement | `src/app/services/recommend_retrieval_metrics.py` | Extend the pattern to a full-response differ (Phase 0). |
| Frozen live batteries | `tests/acceptance/test_swap_rate_battery.py`, golden matrix (14), paraphrase battery | Seed corpus for characterization recording. |

### 1b. Extracted stages (reused AS-IS by the new core)
All already out of suggest(); suggest() still owns their **sequencing + mutable state** — that inversion of control is what V2 changes.

- **Context seams:** `suggest_context.py` (`SuggestContext` dataclass — request, image, guard, flags, catalog, constraints, kv write-back), `recommend_context.py`
- **Intent / constraints / budget:** `recommend_intent_router`, `recommend_constraint_builder`, `recommend_budget_parsing`, `recommend_budget_advisor`, `recommend_budget_band`, `query_decomposer` (CORE module), `intent_decomposer`, `multi_intent_planner`, `llm_planner` (the clamp pattern's origin)
- **Retrieval / ranking:** `recommend_retriever_stage`, `recommend_ranking`, `recommend_candidate_classify`, `recommend_image_similarity_stage`, `recommend_grounding_stage`
- **Vision:** `recommend_vision_stage`, `recommend_image_hints`
- **Workload/fit truth:** `recommend_workload_stage` (+ use_case_advisor, Steam floors)
- **NQE:** `recommend_nqe_stage`, `recommend_nqe_helpers`
- **Response assembly:** `recommend_response_finalizer`, `recommend_response_shape`, `recommend_rightpanel_stage`, `recommend_clarify_payloads`, `recommend_message_decorator`, `recommend_justification`, `answer_composer`
- **Side effects (the contract's hidden half):** `recommend_memory_writeback`, `recommend_narration_stage`, `recommend_narration_jobs`, `recommend_fulfillment_stage`, `recommend_escalation_stage`, `recommend_intelligence_stage`, `recommend_emphasis_stage`, `recommend_inventory_handoff_stage`, `recommend_post_pipeline`, `recommend_evidence`, `evidence_orchestrator`
- **Safety rails:** `answer_quality`, `off_catalog_gate`, `capability_registry`, numeric guard + provenance channel
- **Brain candidate (parked):** `semantic_turn_router.py` — UNWIRED and **ungrounded** (reads `capabilities.sells`, which no profile declares). Regrounded in Phase 4 on the T1 sold-taxonomy; until then it stays off.

### 1c. Still inline in suggest() (recommend.py 4341–11591, ~7,250 ln) — must be replaced, not extracted
- Candidate filter/rank cascade (~1,250 ln, ~30 in-place `candidates` rewrites)
- NQE / session-slot / persona / budget block (~560 ln)
- ~6 early-return payload builders (~670 ln)
- Product-identity + grounding inline logic
- Brand/budget price-fallback ladder
- `_finalize_payload` closure at :5045 (the universal choke every return passes through)

### 1d. The catalog split (T0 target)
| Model | Where | Who reads it |
|---|---|---|
| **Legacy** `products` table | `src/app/models/db.py:879` | suggest(), fulfillment — today's truth |
| **Canonical** product/variant/external_ref | `src/app/services/catalog_entities.py` | integration seam only |
| **Canonical** price_book_entry / inventory_level | `src/app/services/commerce_catalog.py` | integration seam only |
| Ingestion adapters | `shopify_catalog_adapter.py` (103 ln — title/SKU/price/inventory ONLY), `magento_catalog_adapter.py` | thin; T2 widens |

### 1e. The wiring boundary (what V2 must honor)
- **Entry:** `chat.py` builds an internal HTTP request to `/recommend/suggest` (~:1745) and executes it (~:1887). V2 kills this hop: chat calls the core **directly in-process**, behind a flag.
- **Contract:** the `/suggest` response shape **plus side effects** — decision-trace events, Redis session keys (`session:{uid}:summary|kv_state|recent_retrieval|agent_steps`), async narration jobs, security events, fulfillment cases, telemetry.
- **Stays untouched:** the other public endpoints on recommend.py (checkout_upsell :11591, narration poll :11795, product explanation :11806, telemetry :11885, feedback :11968, CF training :12073, NQE state :12093). Only suggest()'s core is replaced.

---

## 2. Do we need testing first? YES — Phase 0 is characterization, and it IS the safeguard

You cannot A/B against an oracle you never recorded. Before any V2 code:

1. **Freeze the contract as a schema** — today it exists only implicitly as whatever `_finalize_payload` emits.
2. **Record how v1 actually behaves** — request → response → side-effects, across the frozen batteries and real multi-turn scripts. This corpus is simultaneously: the A/B oracle, the regression net, and the revert proof ("v1 archived + corpus green = safe to restore").
3. **Map the interactions** — instrument one recording run to log *which stages fire in what order per lane*; that empirically-derived sequence map (not the 12,287-line source) is the spec V2's orchestrator implements.
4. **Tag the known-wrong** — corpus entries where v1 is buggy get `KNOWN_WRONG` + desired behavior, so V2 targets "match v1 *except where v1 was wrong*" instead of blind parity.

> **Ordering consequence:** the 3 uncommitted P0 fixes (off-catalog finalizer, min-vs-recommended, negated-over) must be **committed before recording** — otherwise the oracle enshrines the bugs. This resolves the parked housekeeping question: land them first, in their own commit, separate from the router experiment (which stays unwired).

---

## 3. The phases — exact files, wiring, exit criteria, revert story

### Phase 0 — Contract freeze + characterization (1–2 sessions)
**New files**
- `src/app/contracts/suggest_contract.py` — pydantic `SuggestResponse` (message/assistant_message, products/results, right_panel, off_catalog, clarify payloads, trace_id, summary_pending, llm_summary_job_id, fulfillment refs…), derived by instrumenting real responses, not by reading code.
- `tests/characterization/record_suggest_corpus.py` — record-replay recorder: runs the frozen batteries + multi-turn scripts against live suggest(), persists `{request, response, side_effects}` snapshots.
- `tests/golden/suggest_corpus/*.json` — ~100–200 recorded turns incl. multi-turn sessions (the paraphrase batteries, swap-rate battery, golden matrix, cart-mutation scripts, off-catalog probes).
- `src/app/services/recommend_parity_full.py` — full-response differ (extends the `recommend_retrieval_metrics` pattern): compares message-class, product-set Jaccard, off_catalog verdict, right_panel keys, trace event types, session write-back keys. Divergences bucketed by class.
- Side-effect inventory section in this doc (append after the instrumented run): every emitter suggest() fires, keyed by lane.

**Exit:** corpus recorded on P0-fixed v1; differ runs on any (v1,v2) payload pair; stage-order map per lane documented. **Revert story:** nothing changed in prod code paths.

### Phase 1 — T0: one catalog read-model (1–2 sessions)
**New files**
- `src/app/services/catalog_read_model.py` — the single facade V2 reads: `get_product()`, `get_variant()`, `search_variants(filters)`, `price()`, `availability()`, `attributes()` — vertical-blind, taxonomy-aware fields nullable until T1.
- Two adapters inside it: `_LegacyProductsAdapter` (products table — today's truth) and `_CanonicalAdapter` (`catalog_entities` + `commerce_catalog`).

**Wiring:** `CATALOG_READ_MODEL=legacy|canonical|dual` (dual = read both, diff, log — same shadow discipline). suggest() is NOT touched; only V2 reads the facade.
**Exit:** dual-mode diff clean on the demo catalog. **Revert:** flag back to `legacy`.

### Phase 2 — T1: grounded taxonomy registry (1–2 sessions)
**New files**
- `data/taxonomy/shopify-taxonomy-<pinned-release>.json` — vendored, pinned Shopify Standard Product Taxonomy release (MIT; quarterly upstream, we upgrade deliberately).
- `src/app/services/taxonomy_registry.py` — deterministic: node lookup, ancestors, attribute definitions (with ROLES: descriptive / variant_axis / regulatory / fit / offer), **`is_sold(node_id, tenant)`**.
- Tables (alembic): `taxonomy_node` (cache of pinned release), `product_classification` (variant_id → node_id, source, confidence, approved_by, ts), `sold_taxonomy` (materialized approved nodes per tenant).

**This is what regrounds the semantic router** — `is_sold()` replaces the nonexistent `capabilities.sells` field. Category×variant becomes taxonomy-node + variant_axis attributes: "GPU (server form-factor)" and "chair (ottoman)" are the same mechanism.
**Exit:** demo electronics catalog nodes present; `is_sold(laptop)=True`, `is_sold(rack server)=False` deterministically. **Revert:** registry unused by live paths until Phase 4.

### Phase 3 — T2+T3+T4: ingestion, auto-classification, approval (2–3 sessions)
- **Widen** `shopify_catalog_adapter.py`: ingest `product_type`, `vendor`, `tags`, `options` (variant axes!), barcodes/GTIN, metafields — today it drops all of them.
- **New** `src/app/services/catalog_classifier.py` — the clamp pipeline: existing category → crosswalk; else embed product → vector top-K taxonomy candidates → model picks a node **ID from the K** → deterministic validation (ID exists, leaf-appropriate, attribute sanity). The model can only choose among real nodes; it can never mint one.
- **New** `scripts/onboard_catalog.py` — one-command onboarding: ingest → classify → confidence report → approval file. This is the "auto-categorize any merchant's schema" vision, operationalized.
- Minimal approval surface (admin endpoint + JSON review file) → materialize `sold_taxonomy`.

**Exit:** demo catalog 100% classified, approval reviewed, `sold_taxonomy` live for the electronics tenant. **Revert:** classifications are data, not code paths.

### Phase 4 — the V2 core (3–5 sessions)
**New package** `src/app/services/recommendation_core/`
- `core.py` — `async recommend(ctx) -> SuggestResponse`. Grows out of `recommend_pipeline.py` (promoted into the package): scatter (read-model search, vector, fraud, inventory, CV) → gather/merge → conditional deepening → assemble. Explicit ordered stages over one typed context — **no hidden line-order dependencies.**
- `turn_router.py` — `semantic_turn_router` regrounded: model maps language → taxonomy node IDs (chosen from vector top-K candidates), **deterministic `is_sold()` decides membership**; primary lane + sub-intents (GPT-5.6 correction — no single-lane forcing). OFF_CATALOG becomes a taxonomy fact, not a model opinion.
- `plan.py` — the bounded brain: model proposes a plan over a **CLOSED tool vocabulary** (retrieve / filter / compare / fit / clarify / handoff / off-catalog-honesty), clamp → guard → deterministic default. `llm_planner._validate_plan` generalized. This is where scatter-gather + "agentic" lives — bounded, never free-form tool-calling.
- Stages reused as-is from §1b; side effects emitted through the existing extracted side-effect stages so the contract's hidden half is preserved.

**Wiring:** `chat.py` calls the core **directly** (kills the internal HTTP hop) behind `RECOMMEND_CORE_MODE`; `recommend.py` `/suggest` also dispatches to the core under the same flag so external callers are covered.
**Exit:** V2 answers the full golden corpus in shadow. **Revert:** flag off.

### Phase 5 — Shadow → canary → primary → archive (ongoing)
- `RECOMMEND_CORE_MODE=off|shadow|canary:<pct>|primary` — the proven ladder, now for the whole response. Shadow runs async + sampled (`RECOMMEND_CORE_SHADOW_SAMPLE`) to bound cost.
- Promotion gates (measured, per class): message-class match ≥98% on non-KNOWN_WRONG corpus; product-set Jaccard ≥0.9; **zero** security/gate regressions; guard-pass-rate ≥ v1; all KNOWN_WRONG entries now correct.
- On primary: v1 suggest() is **frozen (bugfix-only), git-tagged, kept importable and runnable behind the flag** for ≥4 weeks before any deletion. Archive ≠ delete.

---

## 4. Standing constraints (unchanged)
- `FULFILLMENT_SUPPLIER_TRANSPORT=sandbox`, `FULFILLMENT_AUTONOMOUS_RFQ=0`; autonomous supplier send stays OFF.
- No edits to the user's `.env` model config; no secrets in chat or docs.
- `SEMANTIC_ROUTER_MODE` stays off until Phase 4 regrounding.
- V1 goes bugfix-only freeze the day Phase 4 starts (two-system drift is the hybrid's main risk).

## 5. Sequencing summary
```
commit P0 fixes ─► Phase 0 (record oracle) ─► Phase 1 (T0 read-model)
      ─► Phase 2 (T1 taxonomy) ─► Phase 3 (T2–T4 classify+approve)
      ─► Phase 4 (V2 core, shadow) ─► Phase 5 (canary → primary → archive)
```
Each phase independently revertible; no phase touches live behavior until Phase 4's flag, and even then default = off.
