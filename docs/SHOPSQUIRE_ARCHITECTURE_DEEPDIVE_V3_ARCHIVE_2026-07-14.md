# ShopSquire — Architecture Deep-Dive: Retrieval Rearchitecture (V3) + Legacy Archive (Track A)

Grounded in a file:line map of the actual code (two exploration passes). Answers: *what are we trying
to improve, how will it work, and exactly what gets rearchitected / refactored / extracted / excised.*

---

## 0. What we're trying to improve (the thesis)

Two different liabilities, often conflated:

- **V3 (retrieval): demo-grade → catalog-grade.** V2's retrieval is correct but built for 114 products.
  It is **O(host-union nodes) sequential DB round-trips**, filters **budget + every fit predicate in
  Python** over fully-loaded rows, scrapes attributes (`ram_gb`) **from product titles with regex**,
  and has **no product vector index** on the hot path. None of that survives a 100k-SKU merchant. We
  are improving: **relevance quality** (ranked candidates, not a subtree scan) and **scale** (bounded
  round-trips, SQL pushdown, ANN).

- **Track A (archive): two engines → one.** `recommend.py` is a **12,312-line legacy engine that still
  ships live**, and — the structural trap — **the V2 facade is dispatched from *inside* `suggest()`**
  (`recommend.py:4524`), so `suggest()` is simultaneously the dispatcher and the fallback engine. We are
  improving **ownership and blast radius**: delete the monolith so there is one engine, one contract,
  one place a change can go wrong.

They connect: V3 makes the V2 engine *good enough* to own all product lanes; Track A *removes the
legacy engine* once it does. V3 is a prerequisite for the last mile of A.

---

## PART 1 — V3: Retrieval rearchitecture

### 1.1 How it works TODAY (mapped)

Per turn, `_exec_retrieve` (`core.py:895`) does:
1. **Node-subtree candidate SQL** (`evidence._skus_for_node`, `evidence.py:69`):
   `SELECT sku FROM product_classification WHERE tenant_id=:t AND (node_handle=:h OR node_handle LIKE :hp) ORDER BY sku LIMIT :lim`.
   **`node_handle` is NOT indexed** (only `UNIQUE(tenant_id, sku)` exists — `taxonomy_registry.py:178`) → an unindexed scan.
2. **Batch hydrate** the SKUs (`catalog_read_model.get_variants(db, skus)`) → 2-4 more queries; full rows into memory; `specs`/`attributes` are **JSON text parsed in Python** (`catalog_read_model.py:100`).
3. **Host-union fan-out** (`core.py:915`): for each declared sibling device node, **another full `gather_evidence` (3 round-trips)**, merged + deduped by SKU in a **Python set/list loop**. Worst case ≈ `3·(1+S) + 3` round-trips (S = host-family size), and the sibling queries aren't even counted in the trace.
4. **Budget filter in Python** (`evidence.py:133`) — a list-comprehension over loaded rows, even though `search_variants` supports SQL price clauses.
5. **Fit predicates in Python** (`attribute_registry.evaluate_requirements`, `attribute_registry.py:350`) — `gpu_vram_gb>=8` is a Python lambda over a per-variant dict; quantities like `ram_gb` are **regex-extracted from the title** (`attribute_registry.py:258`) because the specs are dirty ("`ram_gb=512` — storage stuffed into the RAM field", `attribute_registry.py:16`).
6. **Lexicographic rank in Python** (`ranking.py:40`) — fine; it's over a small already-loaded set.

### 1.2 The five scalability walls

| # | Wall | Root cause | Where |
|---|---|---|---|
| 1 | **O(S) round-trips** | retrieval fans out one full gather per host-family node | `core.py:915-932` |
| 2 | **In-memory merge/dedup** | union combined with a Python set, not a SQL union | `core.py:919-927` |
| 3 | **Python attribute filtering, no pushdown** | fit predicates are lambdas over loaded dicts | `attribute_registry.py:321-366` |
| 4 | **No product vector index** | retrieval is `node LIKE 'x-%'` subtree + `name LIKE '%q%'` fallback; ANN only at classify-time on NODES | `evidence.py:77`, `taxonomy_embedding_index.py` (nodes only) |
| 5 | **JSON specs, not typed columns** | can't index or range-filter `ram_gb` in SQL; regex-scrape from titles | `catalog_read_model.py:100`, `attribute_registry.py:258` |

### 1.3 The good news: the infra to fix this **already exists, unwired**

- **A product pgvector store exists**: `services/vector_store.py` `PgVectorStore` (a `vectors(id, embedding VECTOR(N), payload JSONB)` table + alembic `20260325_pgvector_hnsw_indexes`), plus `services/embeddings.py`, `embedding_pipeline.py`, `product_embedding_text.py`, `semantic_search.py`, `candidate_retriever.py`. These are **V1/`recommend_pipeline` lineage and NOT imported by `recommendation_core/`.** V3 is largely a **wiring + data** job, not a green-field build.

### 1.4 Target architecture (how it will work)

Replace the node-subtree-scan + O(S) fan-out + Python-filter pipeline with a **three-stage bounded pipeline**:

```
query ─► (A) ANN candidate retrieval        [pgvector, ONE query, spans the device family]
          → top-K product ids by relevance
       ─► (B) SQL pushdown filter            [typed columns: sold-set ∩ budget ∩ hard reqs]
          → the K survivors, in SQL, indexed
       ─► (C) fit verdict + lexicographic rank [Python, but over K≈50, not the catalog]
          → the shelf
```

- **(A) Product ANN** (`vector_store` + `candidate_retriever`, wired into `_exec_retrieve`): one HNSW query returns the top-K relevant products **across the whole device family in a single round-trip** — this *excises* walls #1, #2, #4. The taxonomy sold-set becomes a *filter on the candidate payload*, not the retrieval mechanism.
- **(B) Typed attribute columns + SQL pushdown**: promote the dirty JSON `specs` into typed, indexed columns (`ram_gb`, `gpu_vram_gb`, `storage_gb`, `refresh_hz`, `price_cents`) during onboarding/enrichment, and push `budget ∩ hard-requirements ∩ sold-set` into the SQL `WHERE` — *excises* walls #3, #5. This is a **DATA prerequisite**: the onboarding classifier/enricher must populate clean typed attributes (today `ram_gb` is scraped from titles).
- **(C) Keep the Python lexicographic ranker** (`ranking.py`) — it's correct and cheap over K candidates; it stays.

### 1.5 What to rearchitect / refactor / extract / excise (V3)

- **Rearchitect:** `_exec_retrieve` (`core.py:895`) from "node-subtree gather ×S + Python filter" to "ANN → SQL-filter → rank". `evidence.gather_evidence` gains an ANN path.
- **Refactor:** `attribute_registry` fit predicates to consume **typed columns** when present (fall back to the JSON/regex path only for un-enriched rows during migration).
- **Extract/wire (not build):** `vector_store.PgVectorStore` + `candidate_retriever` + `embedding_pipeline` into the V2 core; add the product-embedding build to the onboarding pipeline (reuse the Ollama `nomic-embed-text` path already in `taxonomy_embedding_index`).
- **Excise:** the host-union Python merge (`core.py:915-932`), the Python budget list-comprehension (`evidence.py:133`), the regex-title attribute scraping (once typed columns land), and the dead `recommend_pipeline` V2-scatter-gather seed. Add the missing **`node_handle` index** regardless (cheap win for the fallback).

### 1.6 Phased V3 (each independently shippable, measured by the eval + the new latency gates)

1. **Data**: typed attribute columns + onboarding enrichment to populate them cleanly (+ `node_handle` index). *Unblocks SQL pushdown; no behavior change yet.*
2. **Pushdown**: budget + hard-requirements + sold-set into SQL. *Excises walls #3/#5; measure constraint-sat + latency.*
3. **ANN**: wire the product vector store; replace the node-subtree scan + host-union fan-out with one ANN query. *Excises walls #1/#2/#4; measure relevance (needs labels) + p95.*
4. **Tune** diversity/message-class (V4) once ANN changes the slate.

**Risk:** the DATA step (clean typed attributes) is the real work — the ANN/pushdown code exists. Relevance can only be *proven* with the relevance labels (Track E2, USER). So V3 is gated on labels for its quality claim, though the scale/latency wins are measurable without them.

---

## PART 2 — Track A: Legacy archive

### 2.1 The one structural fact that shapes everything

**The facade is dispatched from *inside* `suggest()`** — `recommend.py:4524`: `if _core_payload is not None: return _core_payload` *else fall through to the 7,000-line legacy body*. So `suggest()` is both the V2 dispatcher **and** the legacy engine. **Prerequisite step 0: hoist the dispatch out** — rename the body `_legacy_suggest()`, and make the route `guard → facade-first → _legacy_suggest() fallback`. Until this lands, `suggest()` cannot shrink or be deleted.

### 2.2 Lane-by-lane: what's extractable vs entangled (easiest → hardest)

| Lane | State | Action |
|---|---|---|
| **CART_MUTATE** | ✅ already fully V2 (`recommendation_facade.py:270/399`, `cart_mutation_service`) | nothing to do |
| **INVENTORY** | ✅ extracted services (`run_inventory_fastpath` `recommend_intent_router.py:364`, `evaluate_inventory_handoff`) | route-direct, delete the 2 inline call sites |
| **POLICY / FAQ** | 🟡 answer is a service (`policy_faq_answer`), ~30 lines inline payload (`recommend.py:7770`) | lift into a `recommend_policy_stage` |
| **PROCUREMENT / bulk** | 🟡 engine extracted (`recommend_fulfillment_stage`, `recommend.py:10834`) but wired as a decorating stage; full RFQ FSM in separate services | **keep legacy** (review-10 decision: advise-only V2 regresses RFQ); promote the stage to a *keeper* |
| **SUPPORT_CLAIM** | 🟠 ~150 lines inline card/playbook assembly (`recommend.py:8245-8400`) | extract `recommend_support_stage`, then add to `CANARY_LANES` |
| **IMAGE** | 🔴 `incoming_image_payload` threaded through ~20 conditionals + module-level quarantine (`recommend.py:1037-1480, 7435-7664`); facade **hard-refuses** image (`recommendation_facade.py:455`) | **rebuild in V2** (quarantine + CV + vision) — the one lane with no V2 impl |

### 2.3 The 38 `recommend_*` services: keepers vs delete-targets

- **5 KEEPERS** (imported outside the legacy cluster — survive the deletion): `recommend_parity_full` (V2 shadow worker), `recommend_narration_jobs` (V2 postflight), `recommend_context` (checkout_handoff), `recommend_budget_band` (catalog_scoring), `recommend_candidate_classify` (recommendations.py).
- **33 DELETE-TARGETS** (legacy-only): the stage modules (`recommend_*_stage`, `recommend_nqe_*`, `recommend_response_*`, `recommend_intent_router`, …) + the **dead `recommend_pipeline`** (superseded by `recommendation_core/`, safe delete now).

### 2.4 What to excise + the traps

- **Excise:** `suggest()`/`_legacy_suggest()`, the 33 legacy-only services, the chat→HTTP loopback (`chat.py:1855/1995`), and `recommend_pipeline` (dead now).
- **Relocate before file-delete:** the **9 sibling endpoints** living in `recommend.py` (`/checkout_upsell`, `/narration/{id}`, `/why_product`, `/interaction`, `/feedback`, `/cf/train`, `/nqe_slots`, `/nqe_feedback`, `/admin/nqe_feedback_summary`) — they die with the *file*, not the function.
- **Repoint ~40 tests** that import module internals (`_classify_turn_intent`, `_with_trace`, `_build_brand_budget_answer`, …).
- **Blast radius of deleting the endpoint:** 4 frontend callers (`ImageRecommendPanel.tsx`, storefront `App.jsx`, the widget, an e2e spec) + `chat.py` loopback + eval/scripts. The endpoint contract must hold until the frontend migrates.
- **The two entanglement risks:** (1) **IMAGE** has no V2 implementation → it *pins `recommend.py` alive* after every other lane migrates; (2) the **facade-inside-suggest** dispatch (step 0).

### 2.5 Clean archive order

1. **Hoist the dispatch** out of `suggest()` → `route = guard → facade → _legacy_suggest()`. *(mandatory prerequisite)*
2. **Kill the loopback** (`chat.py:1995` httpx → direct in-process call; contract is byte-identical).
3. **Route-direct the easy lanes**: INVENTORY + POLICY/FAQ; remove their inline returns.
4. **Extract SUPPORT_CLAIM** → `recommend_support_stage` → add to `CANARY_LANES`.
5. **Relocate the 9 sibling endpoints** to their own router.
6. **Keep PROCUREMENT on legacy**; promote `recommend_fulfillment_stage` to a keeper.
7. **Rebuild IMAGE in V2**; flip the facade's image-refuse (`recommendation_facade.py:455`).
8. **Canary→primary, soak green, then DELETE**: `suggest()`/`_legacy_suggest()` + 33 legacy-only services; keep the 5 keepers; repoint the ~40 tests.

---

## PART 3 — How V3 and A fit (the end-state)

**One engine.** After V3, the V2 core retrieves via **ANN → SQL-pushdown → rank** at catalog scale;
after A, `recommend.py` is gone and every product lane is V2-served, with a thin legacy shim only where
a deliberate decision keeps it (PROCUREMENT's RFQ). The dependency chain:

```
V3 data (typed attrs) ─► V3 pushdown ─► V3 ANN ──┐
                                                  ├─► V2 owns all product lanes at scale
labels (USER) ─► relevance proven ────────────────┘        │
                                                            ▼
              A: hoist dispatch ─► kill loopback ─► extract SUPPORT ─► rebuild IMAGE ─► canary ─► DELETE
```

**Sequencing & effort:**
- **V3**: DATA (typed attrs + enrichment) = the real work (L); pushdown (M); ANN wiring (M, code exists). Scale/latency measurable now; relevance gated on labels.
- **A**: dispatch-hoist (M, do FIRST) + loopback (M) + easy lanes (S) are safe now; SUPPORT (M) + IMAGE-rebuild (L) + canary (calendar) are the long pole; delete is the finale.

**What we're improving, in one line:** retrieval that *ranks by relevance and scales* (V3), and a *single owned engine* instead of a 12k-line dual-engine liability (A) — with the money/safety foundation (Track M) already closed underneath both.

---

## Appendix — the highest-leverage first moves
1. **[USER]** relevance labels — they gate V3's quality claim *and* the canary; nothing proves "better" without them.
2. **[ME] A step 0** (hoist the facade dispatch out of `suggest()`) — mandatory, unblocks every later archive step, low risk.
3. **[ME] V3 step 1** (typed attribute columns + enrichment + the `node_handle` index) — the data foundation both pushdown and honest fit rest on.
