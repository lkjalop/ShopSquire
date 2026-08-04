# ShopSquire — Comprehensive Roadmap (2026-06-21)

Consolidates the latency/search/agnostic work + the independent review. **Correction to that
review:** the "dirty Tier 2 parity" tree is **already committed** — `47394ca` landed
`recommend.py` parity wiring + `recommend_retrieval_metrics.py` + its test together. Tree is clean.

## Where we are (verified)
- `recommend.py` ≈ 11,813 lines (grew slightly: async narration + V2 parity wiring added — capability up).
- **Latency SOLVED**: `RECOMMEND_NARRATION_MODE=skip` (instant deterministic, ~8.4× faster: p50
  5176→615ms) | `async` (instant + prose via job store + `GET /api/v1/recommend/narration/{job_id}`,
  recommend.py L11819) | `blocking` (default — **so the win only applies when skip/async is set**;
  config `feature_flags.json` still defaults blocking).
- **Tier 2 measurable**: V2 shadow now logs `recommend_pipeline_v2_parity` (overlap@k, budget
  adherence, latency) vs served results — still shadow-only, not customer-affecting.
- Core/adapter demarcation strong (profile selector/middleware; taxonomy, category, persona,
  brand-SQL, ranking/spec, identity, budget floors all profile-backed; 3 verticals + no-bleed tests).

### Honest stub/fallback list (still not production)
- V2 hybrid retrieval shadow-only (recommend.py L4169).
- Image→visually-similar NOT live (visual_search.search exists, L277).
- Async narration needs Redis to persist (no Redis → poll stays pending).
- Residual electronics fallbacks in `recommend_utils` (spec extraction), `recommend_ranking`
  (scorer), `use_case_advisor` (fit evaluator), `recommend_nqe_stage` (question text),
  `vision_reasoning` (VLM schema) — flavour-*defaulted*, not flavour-*free*.
- Supplier comms / external research / shipping / voice ASR-TTS = stub/deferred.

## Roadmap (ordered)

| # | Tier | Outcome | Risk |
|---|---|---|---|
| 1 | **Turn latency on for demo** | `RECOMMEND_NARRATION_MODE=skip`; re-bench live | trivial |
| 2 | **Tier 2 fusion** | parity logged (done) → `RECOMMEND_RETRIEVAL_MODE=shadow\|fusion\|primary` gated on parity data; extract `recommend_retriever_stage.py` | MED |
| 3 | **Safe internet search** (below) | guardrailed `ExternalProductResearchPort` as a labeled non-owned source | MED |
| 4 | **Image→visual-similar** | safe visual lane via visual_search + on_topic/adjacent/off_topic classifier; extract image/identity stage | MED |
| 5 | **VLM harden** | timeout/cancel/cache/prewarm; turn `PARALLEL_VISION_IDENTITY` on measured; join late | LOW |
| 6 | **Core/adapter hardening** | StoreProfile JSON schema + parity linter; remove the 5 residual electronics fallbacks → flavour-free | MED |
| 7 | **Shrink recommend.py** | extract retriever → narration → identity → ranking → security → constraints (last); <10k → <7k | MED→HIGH |
| 8 (deferred) | supplier ports, shipping, voice | bounded autonomy | — |

Rule (carried): **don't chase line count ahead of 1–4; never flip V2 primary without parity data;
external/web data is a labeled non-owned source, never owned inventory.**

---

## Safe internet search — concrete wiring (the asked-for detail)

**Principle:** external/web results are **never owned products**. They go in a **separate payload
field + a labeled source-status**, never into `results`/cart, unless mapped to a real catalog SKU.

### Files to CREATE
1. `src/app/ports/external_product_research.py` — the injectable boundary (Protocol):
   ```python
   class ExternalResearchFetcher(Protocol):
       # real impl = httpx-to-allowlist (networked env); tests = fake fetcher
       def fetch(self, scrubbed_query: str, *, allowlist: list[str], timeout_s: float) -> list[dict]: ...
   ```
2. `src/app/services/external_product_research_service.py` — the guardrailed core (CORE, vertical-blind):
   - `research(query, *, fetcher, allowlist, catalog_skus, enabled, redis=None) -> dict`
   - Enforced guardrails (each unit-tested):
     - **disabled by default** → `{"status":"disabled","items":[]}` when `enabled` is False.
     - **PII scrub before egress**: `scrubbed = scrub_pii(query)` (from `src.app.deps`, recommend.py L18).
     - **domain allowlist**: fetcher only receives `allowlist`; service drops any hit whose
       `source_domain` ∉ allowlist (defense in depth).
     - **cache + freshness**: optional Redis key `extres:{hash(scrubbed)}` (TTL), each item gets `fetched_ts`.
     - **SKU-gate**: map each hit's name/model against `catalog_skus` (name match); set
       `sku=<matched>` + `sold_here=True`, else `sku=None` + `sold_here=False` +
       `label="not sold by this store"`.
     - **data-not-instructions**: hit text only populates display fields (`title`,`snippet`); it is
       NEVER passed to an LLM as instructions or to any tool/policy.
   - Returns `{"status":..., "items":[...], "source_status": SourceStatus(source="external_research", ...).to_dict()}`.
3. `tests/services/test_external_product_research.py` — assert each guardrail with a fake fetcher
   (allowlist denial, PII scrubbed, SKU-gating + sold_here label, disabled-by-default, cache).

### Files to MODIFY (line-level integration)
- `config/feature_flags.json` (after L45): add `"EXTERNAL_RESEARCH_ENABLED": false` and
  `"EXTERNAL_RESEARCH_ALLOWLIST": ["example-allowed.com"]`.
- `src/app/routers/recommend.py`:
  - **Call site ~L10046–L10193** (after `results` finalized via `_top_up_image_results`, before the
    payload's `source_statuses` at L10193): when `flags["EXTERNAL_RESEARCH_ENABLED"]` AND the query
    warrants it (e.g. owned `results` is empty/low, or an explicit "search the web" intent), call:
    ```python
    _extres = research(query, fetcher=_get_external_fetcher(), allowlist=flags.get("EXTERNAL_RESEARCH_ALLOWLIST") or [],
                       catalog_skus=[r.get("sku") for r in results] + _catalog_skus(db, tenant_id), enabled=True, redis=redis)
    payload["external_research"] = _extres["items"]          # SEPARATE field, NOT results
    ```
  - **Labeled source**: append `_extres["source_status"]` to the payload `source_statuses`
    (built at L10193 via `_build_source_statuses`) — so the trace/admin shows it as its own source
    that can never silently merge with owned inventory.
  - **Never** add `external_research` items to `results`, cart, or checkout (cart endpoints require a
    real SKU; external items have `sku=None` → structurally un-cartable).
  - Optional: `log_trace_event("external_research", ...)` for the decision trace.

### Why this is safe by construction
- It's a *labeled, separate source* (own `source_status`) — `results` (owned inventory) is untouched.
- `sku=None` external items can't be carted/checked-out (those paths require a catalog SKU).
- PII is scrubbed before egress; only allowlisted domains are reachable; web text is display data,
  never instructions (no tool/policy path consumes it).
- Disabled by default (flag) + mock-first (injectable fetcher) → zero risk to merge, testable here.

---

## Demo readiness
**Electronics demo:** clean tree ✓ → set `RECOMMEND_NARRATION_MODE=skip`, prewarm vision/cache,
build visual index, run `scripts/bench_recommend.py --url <stack>`. Close.
**Production-grade:** still needs V2 cutover (parity-gated), visual similarity, supplier/inventory
action ports, shipping, and removal of the 5 residual electronics fallbacks.
