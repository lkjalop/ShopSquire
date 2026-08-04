# Catalog-wide Multimodal RAG — Execution Plan (2026-06-15)

How to execute it **without adding to the spaghetti**, plus the silent-fails and
tech-debt the deep dive surfaced (some of which the feature should fix on the way).

---

## 1. Current state — the vector/embedding map (the spaghetti)

There are **three** independent vector systems today:

| Store | Module | Backing | Used by | Status |
|---|---|---|---|---|
| `product_embeddings` (pgvector, HNSW) | `repositories/embeddings.py` | Postgres pgvector + alembic HNSW index | `erp/sync.py`, health check | **production table** |
| `vectors` (pgvector, generic) | `services/vector_store.py` + `services/embedding_pipeline.py` (`EmbeddingPipeline`) | Postgres pgvector | almost nothing | **parallel scaffold** |
| FAISS in-memory (CLIP) | `services/visual_search.py` | SentenceTransformer + FAISS | `candidate_retriever.from_vector` | visual similarity |

Plus `semantic_search.py`, `faq_v2.py`, `embeddings.py` overlapping helpers, and the
`candidate_retriever` RRF + `recommend_pipeline` scatter-gather are **scaffolds not wired**
into the live recommend path (the monolith uses `RecommendationService.retrieve_candidates`).

**Two real bugs found in the deep dive:**
1. **Embedding-quality bug (silent):** `erp/sync.py:302` builds the product embedding from
   `embed_text_vector(r.sku)` — i.e. **the SKU code alone**, not name/specs/description. So the
   pgvector semantic search is low-signal today. (This is *why* the image+text path leaned so
   hard on embedding similarity earlier — the text embeddings are weak.)
2. **Three stores, no single source of truth** for "what text represents a product" or "which
   index retrieval uses." Adding a 4th caption store would compound this.

---

## 2. Design principle — reuse, don't add a 4th store

Multimodal RAG = "ground each image into NL text, embed it, retrieve over it." The cleanest
realization on THIS codebase:

> **One canonical `product_embedding_text(product)` = name + brand + key specs + VLM caption,
> embedded into the EXISTING `product_embeddings` table.**

Consequences:
- The VLM caption (visual semantics) rides the **existing** pgvector + HNSW + `_SEARCH_EMBED_SQL`
  retrieval. No new table, no new retrieval path.
- It **fixes the SKU-only bug** in the same change (rich text instead of SKU).
- It is provider-agnostic and SQLite-safe (Postgres-only write already guarded).
- The VLM caption is generated through the **vision cache shipped today**, so re-indexing is cheap.

This is the same "extend the one mechanism, don't add a special case" discipline used for the
Authorization Engine (one gate, not a 6th policy layer) and the vision cache (one cache, both
call sites).

---

## 3. Execution steps (incremental, each independently shippable + testable)

**Step A — one source of truth for embedding text.**
- New `services/product_embedding_text.py::build_embedding_text(product, caption=None) -> str`.
- Pure, unit-testable: `f"{name}. {brand} {category}. {specs_str}. {caption}"`.
- Replace `erp/sync.py`'s `embed_text_vector(r.sku)` with `build_embedding_text(r)` — **fixes the
  SKU-only bug immediately**, even before captions exist.

**Step B — offline VLM captioner (cached).**
- New `services/product_captioner.py::caption_product(image_bytes) -> str`, reusing
  `cv_provider.get_labels_and_text(mode="visual_search")` (already vision-cached) →
  schema-constrained short caption ("Black 16-inch MSI gaming laptop, RGB keyboard, thin bezels").
- **Schema-constrained** output (guaranteed string) → no silent parse failures.

**Step C — batch (re)index script.**
- Extend the existing `scripts/build_visual_index.py` (already present) with a
  `--captions` mode: for each product → `caption_product(image)` (cached) → `build_embedding_text`
  → `upsert_product_embeddings`. Idempotent; safe to re-run; logs counts + failures (metric).
- Pre-warms the vision cache for the catalog as a side effect (demo win).

**Step D — confirm/wire retrieval.**
- `repositories/embeddings._SEARCH_EMBED_SQL` already does cosine over `product_embeddings`.
  Verify it's invoked by the live recommend path; if not, add it as a retrieval source. Prefer
  finishing `candidate_retriever` as the single RRF path (DB-keyword + pgvector-caption +
  CLIP-visual) and wiring it behind a flag, validated **shadow vs monolith** (same discipline as
  the authz cutover) — rather than threading a 3rd source into the monolith.

**Step E — RRF the three sources.**
- `candidate_retriever.merge_rrf(db_hits, caption_hits, clip_hits)` — it already supports N
  sources. Caption-RAG becomes one ranked input, not a replacement.

---

## 4. Spaghetti / silent-fails / tech-debt addressed on the way

- **FIX (Step A):** SKU-only embedding → rich text. Direct quality win, removes a silent weakness.
- **CONSOLIDATE:** make `product_embeddings` the one product vector store; mark the generic
  `vectors`/`EmbeddingPipeline` path as FAQ/doc-only (or migrate it), and document FAISS-CLIP as
  the visual-only index. Net: 3 ad-hoc stores → 1 product store + 1 visual + 1 doc, each with a
  stated purpose (no 4th).
- **OBSERVABILITY:** add metrics to the silent `except: return []` paths (`from_vector`,
  visual_search unavailable, embedding upsert no-op on SQLite, caption failures) — reuse the
  `record_*` metric pattern. A weak/empty index should show up, not hide.
- **DECIDE the scaffolds:** either finish-wiring or delete `recommend_pipeline` /
  `candidate_retriever` — don't leave two parallel "future" retrieval paths next to the monolith.
- **SCHEMA-CONSTRAINED captions** (Step B) — no free-text JSON parsing.

---

## 5. Testing (iterative, green-gated)

1. `build_embedding_text` — pure unit tests (name/specs/caption composition, missing fields).
2. `product_captioner` — cache hit on repeat (reuses vision_cache test pattern), schema-valid output, fail-open empty string on vision outage.
3. Batch script — dry-run on a few SKUs, assert `product_embeddings` rows written (Postgres) / clean no-op (SQLite).
4. Retrieval quality — golden set: "black leather jacket asymmetric zipper"-style queries return the right SKUs; assert caption-RAG lifts recall vs SKU-only baseline.
5. **Parity/shadow** — run caption-RRF beside the monolith, compare top-k overlap + budget/category adherence (reuse today's text-vs-image harness) before cutover.
6. Full regression on `tests/test_recommend.py` + the vision-cache suite.

## 6. Rollout / risk

- Postgres + pgvector required for the write path (SQLite no-ops cleanly — dev safe).
- Re-index is offline + idempotent; cached so cheap. Ship behind a flag; shadow → cutover.
- Worst case (index empty/stale): retrieval falls back to DB-keyword + CLIP (fail-open).

## 7. Recommended first move
**Step A** — fix the SKU-only embedding bug with `build_embedding_text` (small, pure, tested,
immediate quality win, and the foundation everything else builds on). Then B+C (captioner +
batch), then D+E (wire + RRF) behind a shadow flag.
