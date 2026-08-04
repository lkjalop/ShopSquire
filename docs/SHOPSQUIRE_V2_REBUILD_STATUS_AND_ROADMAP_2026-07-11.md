# ShopSquire V2 Rebuild — Status + Updated Roadmap (2026-07-11)

**Plan of record:** `docs/SHOPSQUIRE_V2_GREENFIELD_ROADMAP_2026-07-10.md` (7089b9f). This document is the execution status one day in: Phases 0–3 of 6 are DONE, in seven commits, all verified live.

---

## 1. What we are trying to achieve, and WHY a new core

**The goal:** a commerce recommendation core where **the model decides and deterministic code verifies** — for ANY vertical (electronics, pharmacy, fashion, furniture), grounded on real catalog + taxonomy facts, behind the existing safety/gate/audit machinery.

**Why the old suggest() can't get there by patching:**
- `recommend.py` is 12,287 lines; `suggest()` alone is ~7,250 (4341–11591). Its real decisions are ~30 regex patterns; every paraphrase that misses adds another. Proven treadmill: the negated-"over" budget bug had to be fixed in **four** parser copies; turn-intent lives in two drifting copies.
- Its honesty was a hand-maintained NEGATIVE list (`off_catalog_classes`) — simultaneously too narrow (**sold 13 laptops to "do you sell forklifts?"** — never-listed categories aren't on the list) and too broad (**refused "a laptop with A100-like performance"** — the token A100 pattern-matched to servers). Both now recorded in the golden corpus as `known_wrong`.
- The platform's model-intelligence kept getting silently muted — 9 documented mute layers before this arc, and **3 more found this week** (cold-load timeout, GPU contention, a vision model resolving from `OLLAMA_SMALL_MODEL`). Rules didn't just replace the model; they hid its failures.
- The catalog itself was ungrounded: two catalog models (legacy `products` vs canonical variant tables, canonical **empty**), **zero** `category`/`product_type` values on all 114 live products, category behavior derived from SKU prefixes and name regex.

**Why greenfield-behind-a-contract rather than refactor-in-place:** suggest() still sequences its 37 extracted services through implicit line-order and shared mutable state — "extracted" never meant "decoupled." The strangler path spends months re-plumbing without changing who decides. Instead: freeze the `/suggest` contract, record how v1 actually behaves (the oracle), build a clean core on real ground truth, run it in **shadow**, promote on **measured** parity, keep legacy **archived-but-runnable behind one env flip**. The revert story is the same `shadow|fusion|primary` ladder already proven live for the retrieval leg (`RECOMMEND_RETRIEVAL_MODE`).

**The design rule (constant everywhere):** the model maps unbounded human language onto **bounded, real vocabularies** (taxonomy node handles, closed tool names, closed lanes); deterministic code validates existence, sellability, price, budget arithmetic, and authorization. The model proposes; it never publishes.

---

## 2. What has been DONE (commits 7089b9f → 82e9191)

| Phase | Commit | Delivered | Measured proof |
|---|---|---|---|
| Plan | `7089b9f` | Roadmap doc | — |
| P0 fixes | `c84d43f` | Off-catalog honesty moved to `_finalize_payload` (the universal choke — tail-only handler was bypassed by early returns); min-vs-recommended workload floors; negated-"over" budget cap | 4 off-catalog paraphrases honest; Cyberpunk 0→7 products + verdicts; "$1900 cap" max price $1899 across 32 products |
| **0 — Characterize** | `cbd6705` | Frozen `/suggest` contract + 27-turn golden corpus + full-response differ + recorder | Discovered `/suggest` is a **forked contract** (only 4 universal fields; inventory-fast-path/claims/policy shapes differ); 3 `known_wrong` bugs recorded & reproduced |
| **1 — T0 read-model** | `7078657` | `catalog_read_model.py`: one read API over both catalog stores, `legacy\|canonical\|dual`, coverage report, backfill | Canonical was EMPTY (114 vs 0) → backfilled to 114/114, 0 price drift; **89/114 stock drift found** = the named blocker for the canonical flip |
| **2 — T1 taxonomy** | `65aa0f9` | Vendored pinned Shopify taxonomy 2026-05 (14,606 nodes) + `taxonomy_registry.py`: tri-state `is_sold()`, clamped write-side, sold-taxonomy tables | 9/9 live probes: Laptops sell, **Computer Servers (A100) refusable as set-membership fact**, router/switch grain, forklift-class refusable, 3 verticals grounded |
| **3 — T2/T3 classify** | `82e9191` | Widened Shopify ingestion (options = variant axes, GTIN, tags, sale prices); `catalog_classifier.py` clamp pipeline; `onboard_catalog.py` CLI; `sells_within()` refusal gate | **114 products auto-classified: 41% lexical → 77% +crosswalk → 97.3% +model (98.2% true)**; sold set = 35 per-product nodes, bootstrap deleted; 12/12 refusal-gate probes |

**Also standing:** the flawed chat.py router wiring is stashed (labeled); `semantic_turn_router.py` + tests parked on disk as the Phase-4 seed (ungrounded until rewired on `sells_within()`); memory notes updated per phase.

---

## 3. The file ledger

### 3a. NEW files created this arc (all committed)
| File | Role |
|---|---|
| `src/app/contracts/suggest_contract.py` | Frozen empirical `/suggest` contract: UNIVERSAL_FIELDS (4), CORE_FIELDS (34, full-pipeline branch), KNOWN_FIELDS (~105), `response_shape()`, `validate_response()` |
| `src/app/services/recommend_parity_full.py` | Full-response differ: BLOCKER/MAJOR/MINOR/INFO ladder + Phase-5 promotion gates (`message_class` ≥98%, Jaccard ≥0.9, zero gate regressions) |
| `tests/characterization/record_suggest_corpus.py` (+ `batteries/starter_battery.json`, `summarize_corpus.py`) | Corpus recorder (per-run session isolation, narration + guard capture), 25-case battery with `known_wrong` ledger, assessment report |
| `tests/golden/suggest_corpus/` (27 turns) | THE ORACLE — v1 behavior pinned to c84d43f; V2 must match it except where `known_wrong` says otherwise |
| `src/app/services/catalog_read_model.py` | T0 facade: `VariantView`, `get_variant`/`search_variants`, `CATALOG_READ_MODEL=legacy\|canonical\|dual`, `coverage_report`, `backfill_canonical_from_legacy` |
| `data/taxonomy/shopify-2026-05/categories.txt` | Vendored PINNED Shopify Standard Product Taxonomy (MIT, 14,606 categories) |
| `src/app/services/taxonomy_registry.py` | T1 ground truth: node lookup/ancestry/search; `product_classification` + `sold_taxonomy` tables (write-clamped); tri-state `is_sold()`; **`sells_within()` = the refusal gate** |
| `src/app/services/catalog_classifier.py` | T3 clamp pipeline: crosswalk → coverage-weighted top-K (hint-seeded) → model picks FROM LIST → validate → fallback; `warmup()`; loud failures |
| `scripts/bootstrap_sold_taxonomy.py`, `scripts/onboard_catalog.py` | Demo grounding bootstrap (superseded, kept for new tenants); one-command onboarding: classify → approval file → approve → materialize |
| Tests: `test_recommend_parity_full.py`, `test_catalog_read_model.py`, `test_taxonomy_registry.py`, `test_catalog_classifier.py` | 52 unit tests pinning the new ground-truth layer |

### 3b. WIDENED (existing files edited)
- `src/app/services/shopify_catalog_adapter.py` — was title/SKU/price/inventory only; now vendor→brand, product_type→category, tags, **options as variant axes**, barcode→GTIN, images, description, compare_at→list/sale.
- `src/app/routers/recommend.py` — P0 only: off-catalog override in `_finalize_payload`, tail block deleted (suggest() *shrank*).
- `src/app/services/recommend_workload_stage.py`, `answer_quality.py` — P0 semantics fixes.

### 3c. Already EXTRACTED from recommend.py (the 37 `recommend_*` services — V2 reuses, does not rewrite)
Context: `suggest_context.py`, `recommend_context.py` · Intent/constraints: `recommend_intent_router`, `recommend_constraint_builder`, `recommend_budget_parsing/advisor/band`, `query_decomposer`, `intent_decomposer`, `multi_intent_planner`, `llm_planner` · Retrieval/rank: `recommend_retriever_stage` (the mode ladder), `recommend_ranking`, `recommend_candidate_classify`, `recommend_image_similarity_stage`, `recommend_grounding_stage` · Vision: `recommend_vision_stage`, `recommend_image_hints` · Fit: `recommend_workload_stage` · NQE: `recommend_nqe_stage/_helpers` · Response: `recommend_response_finalizer/shape`, `recommend_rightpanel_stage`, `recommend_clarify_payloads`, `recommend_message_decorator`, `recommend_justification` · Side effects: `recommend_memory_writeback`, `recommend_narration_stage/jobs`, `recommend_fulfillment_stage`, `recommend_escalation_stage`, `recommend_intelligence_stage`, `recommend_emphasis_stage`, `recommend_inventory_handoff_stage`, `recommend_post_pipeline`, `recommend_evidence`, `evidence_orchestrator` · **Seed: `recommend_pipeline.py` — the scatter-gather V2 skeleton, already shadow-wired with parity metrics; the Phase-4 core grows from it.**

### 3d. Still INLINE in suggest() — replaced by the V2 core, not extracted
The ~1,250-line candidate filter/rank cascade (~30 in-place rewrites) · the NQE/session-slot/persona/budget block (~560) · ~6 early-return payload builders (~670, the source of the contract forks) · inline product-identity/grounding · the brand/budget price-fallback ladder.

### 3e. RETIRED when Phase 5 promotes (not before)
`off_catalog_gate` regex + `off_catalog_classes` negative list (→ `sells_within()`) · chat `_classify_turn_intent` regex (→ regrounded router) · the chat→HTTP→/suggest internal hop (→ direct call) · per-surface category hacks (SKU-prefix/name-regex; → `product_classification`) · finally `suggest()` itself → `recommend_legacy.py`, frozen, git-tagged, runnable behind the flag ≥4 weeks.

---

## 3.5 EXECUTED (post-GPT-5.6 re-eval, commits d77de9b → eb15b28)

All nine findings verified in code, then fixed or resolved:
- `d77de9b` — tenant propagation; sold-set RECONCILIATION with retirement (manual grants preserved, live-proven: 2 stale grants retired); `grounding_status()` ERROR|EMPTY|GROUNDED; **executable known_wrong** (`expect_v2` assertions; summarize_run requires every expected fix); approval preselect removed (confidence ≠ correctness).
- `f667a53` — **attribute layer** (the named largest gap): data-driven defs for electronics/pharmacy/fashion, unit conversion, bounds (caught the live ram_gb=512 bug), unit-anchored name extraction with GB-ambiguity surfaced-never-assigned, tri-state `meets()`/`evaluate_requirements()`. Monitors 0→10/10 attributes from names alone; workload verdicts with zero legacy parsers.
- `fcc15a8` — **labeled holdout**: all 114 hand-labeled (3 catalog data-bugs recorded); honest scorecard replaced the 98% coverage claim. Raw baseline: **63.2% exact**.
- `c39b646` — alembic migration + DDL drift test. `6409505` — stock SoR decision (inventory_level = target SoR; provenance + freshness on every stock read; no cross-copying).
- `eb15b28` — classifier v2, measured: crosswalk-as-prior (+ subtree refinement, ≥0.75 override outside) then earn-specificity clamp (child picks must cite evidence, else snap to parent). **63.2% → 74.6% exact / 85.1% lenient.** The one shared `_plural_expand` (its inline copy snapped Dresses to Clothing same-day — the drift class, caught by the holdout). Remaining classifier ledger: SSD/HDD sibling override, PHM lexical junk, 2 zero-token abstentions → cure = embedding candidates (nomic-embed-text installed; candidate-generator contract designed for the swap).

## 4. What REMAINS

### Phase 4 — `recommendation_core/` (the brain, 3–5 sessions)
Work breakdown, in build order:
1. **Envelope + adapter** (1 session): `recommendation_core/envelope.py` — the typed turn envelope + ONE unified response envelope; `legacy_adapter.py` emulating the four recorded contract forks so existing consumers see no change. Contract tests against `suggest_contract`.
2. **Evidence + fit stages** (1 session): tenant-scoped retrieval via `catalog_read_model`, taxonomy grounding via `sells_within`/`grounding_status` (degrade on ERROR — never recommend-as-healthy), attribute/workload fit via `evaluate_requirements`. Reuses proven leaf services; NOT grown from recommend_pipeline (bounded fan-out reused as utility only; its fraud fail-open fixed on import).
3. **The bounded brain** (1–2 sessions): `turn_router.py` (semantic router regrounded: model maps language → taxonomy handles from candidate top-K, `sells_within()==False` is the only refusal; VL-model-chain fixed) + `plan.py` (model proposes over the closed tool vocabulary; validator; deterministic default). Never-empty recovery answer.
4. **Wiring** (0.5 session): chat calls the core in-process (HTTP hop dies); `/suggest` dispatches under `RECOMMEND_CORE_MODE` (default off).
5. **Acceptance** (0.5 session): the 3 known_wrongs pass their `expect_v2` assertions AND `summarize_run` shows zero BLOCKERs on the 24 parity cases — the harness already exists and is tested.
New package `src/app/services/recommendation_core/`:
- `core.py` — grows out of `recommend_pipeline.py`: scatter (read-model search / vector / fraud / inventory / CV) → merge → conditional deepening → assemble. Explicit ordered stages over one typed context; emits the Phase-0 contract + side effects through the existing extracted stages. Never-empty recovery answer (kills the valorant silent-zero).
- `turn_router.py` — `semantic_turn_router` regrounded: model maps language → taxonomy node handles chosen from candidate top-K; **deterministic `sells_within()` decides refusal** (False = refuse; None = never refuse); primary lane + sub-intents; fix the VL model chain.
- `plan.py` — model proposes a plan over a CLOSED tool vocabulary (retrieve/filter/compare/fit/clarify/handoff/off-catalog-honesty); clamp → guard → deterministic default (`llm_planner._validate_plan` generalized).
- Wiring: chat calls the core in-process (HTTP hop dies); `/suggest` dispatches under `RECOMMEND_CORE_MODE`.
- **Acceptance = the 3 corpus known_wrongs fixed** (forklift refuses honestly, A100-spec laptop sells, valorant gets closest-match honesty) **while the differ shows no BLOCKER against the oracle elsewhere.**

### Phase 5 — shadow → canary → primary (ongoing)
`RECOMMEND_CORE_MODE=off|shadow|canary:<pct>|primary`; sampled async shadow with the full-response differ; promotion gates from `recommend_parity_full.summarize_run`; legacy archived-runnable. Revert = one env flip at every step.

### Known open items (tracked, deliberately not this arc)
Stock system-of-record decision (89-SKU drift) before `CATALOG_READ_MODEL=canonical` · 2 unclassifiable PHM products · `hb-1-9-6` crosswalk-coarseness class (merchant declarations cover it) · alembic migrations for the new tables (in-service DDL today, per catalog_entities precedent) · pre-existing silent-except gate failures in recommend.py/hippograph (Tier-A backlog) · contract-fork unify-or-honor decision lands with Phase 4.

---

## 5. The safeguard (unchanged, restated)
Nothing user-facing changes until `RECOMMEND_CORE_MODE` leaves `off`. The oracle corpus + differ make every promotion a measured decision; the legacy path stays warm and one env flip away through the entire arc. Autonomy constraints stand: sandbox transport, autonomous RFQ off, human-only send, no .env model-config edits.

---

## 6. FOR GPT-5.6 SOL — independent verification, claim by claim

Every claim above is checkable without trusting this document:

| Claim | Verify with |
|---|---|
| Seven commits, nothing else touched | `git log --stat 7089b9f..82e9191` |
| The oracle records real v1 behavior | Read any `tests/golden/suggest_corpus/*.json` (request → full response → narration outcome incl. guard rejections → contract violations, pinned to git SHA in `meta`); `python tests/characterization/summarize_corpus.py` |
| The 3 known_wrong bugs are real & reproduced | `offcatalog_never_listed.json` (13 products for a forklift question), `spec_not_formfactor.json` (A100-spec laptop refused), `workload_valorant_fps.json` (0 products, null message) — each recorded twice with identical outcomes |
| Differ gates are strict where it matters | `tests/services/test_recommend_parity_full.py` — off-catalog flip = BLOCKER, dropped refusal = BLOCKER; `summarize_run` implements the ≥98%/≥0.9/zero-BLOCKER promotion gates |
| Catalog convergence is measured, not asserted | `python -c` on `catalog_read_model.coverage_report` — 114/114 overlap, 0 price drift, **89 stock drift**, read-failures counted explicitly (a broken adapter cannot score zero drift) |
| Taxonomy grounding is deterministic | `python scripts/bootstrap_sold_taxonomy.py` (probes embedded); `tests/services/test_taxonomy_registry.py` incl. whole-file handle-hierarchy drift test |
| 98.2% classification accuracy | `python scripts/onboard_catalog.py report` (112 approved: 60 crosswalk / 50 model / 2 human-correction); the approval artifact `tmp/approvals_demo.json`; re-run the sweep yourself: `classify --out tmp/recheck.json` |
| 52 new unit tests, all green | `python -m pytest tests/services/test_recommend_parity_full.py tests/services/test_catalog_read_model.py tests/services/test_taxonomy_registry.py tests/services/test_catalog_classifier.py tests/services/test_shopify_catalog_adapter.py -q` |
| suggest() SHRANK this arc | `git show c84d43f -- src/app/routers/recommend.py` (tail off-catalog block deleted; universal choke gained 20 lines, net −24 within suggest()) |

**Honest failure disclosures for your review** (found by our own instrumentation, all now loud):
1. Three consecutive muted-model incidents in the classifier's first live runs — cold-load timeout swallowed to `""`, GPU-contention warmup failure, and `OLLAMA_SMALL_MODEL` resolving a VISION model via `load_dotenv`. The 10th–12th mute layers, in brand-new code. Fixes: `warmup()` with WARM/UNAVAILABLE printed, per-failure logging, model chain restricted to `CLASSIFIER_MODEL`-or-certified-default. The parked `semantic_turn_router` still has the VL-chain bug (fix scheduled at its Phase-4 rewire).
2. The first coverage_report could not distinguish "no drift" from "canonical unreadable" (the silent-swallow class, in the tool built to detect it). Fixed: `read_failure_count`.
3. My first lexical scorer let "Laptop Power Cords" outrank "Laptops" (uncovered leaf tokens + depth bonus) and "dress" never matched "Dresses" (`+s`-only pluralization). Both fixed and pinned by tests; the 41%→77%→97% ladder quantifies each fix.

## 7. Questions we want adjudicated (ranked by how much they shape Phase 4)

1. **Contract forks — unify or honor?** Phase 0 proved `/suggest` returns ≥4 distinct top-level shapes (full-pipeline / inventory-fast-path / claims / policy-FAQ). V2 options: (a) emit one unified shape + adapter-shims for old consumers, (b) reproduce the forks branch-for-branch, (c) unify internally but keep fork emulation until chat/frontend migrate. We lean (c). Your call?
2. **Refusal semantics — any hole in `sells_within()`?** Refuse only on explicit False (subtree-overlap, tri-state, None never refuses). Adversarial cases welcome — e.g., a sold ACCESSORY leaf (Laptop Bags) making a parent query ("do you sell computers?") non-refusable via an unrelated sibling path, or attribute-level refusals (sold category, unsold variant-axis value) which this design pushes to retrieval-empty + honesty prose instead of refusal.
3. **Crosswalk precedence created a sold-set gap class**: merchant's coarse "laptop" crosswalks all 45 SKUs to el-6-6, so el-6-11-2 (Gaming Laptops) needed a manual merchant_declaration or gaming-laptop queries would refuse. Should crosswalk defer to the model when the model's pick is a DESCENDANT-adjacent finer node, or is data-side declaration (current choice) the right fix?
4. **Phase-4 core seed**: grow from the already-shadow-wired `recommend_pipeline.py` + reuse the 37 extracted stages (our plan), or a cleaner from-scratch orchestrator that imports fewer legacy assumptions? What's the riskiest legacy assumption we'd inherit?
5. **Is known_wrong-as-acceptance sound?** V2 must fix the 3 recorded bugs while showing zero BLOCKER divergence elsewhere. Is a 27-turn corpus enough for the Phase-4 gate, or should corpus expansion (image lane, true multi-turn cart/chat flows, adversarial security probes) be a Phase-4 entry requirement rather than a parallel task?
6. **Stock system-of-record** (89/114 drift): decide before Phase 4 wires availability, or defer to the canonical flip since V2 reads the facade either way?
7. **Anything premature?** You corrected us once (ungrounded router). Same question, one level up: what in Phases 0–3 would you have sequenced differently, and what's the largest unexamined assumption in the Phase-4 plan?
