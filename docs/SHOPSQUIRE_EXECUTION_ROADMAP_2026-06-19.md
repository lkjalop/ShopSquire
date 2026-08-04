# ShopSquire — Execution Roadmap (2026-06-19): latency · split · agnostic · wiring

Concrete, buildable plan. Every task lists **files+lines**, **what to wire**, **tests**, **order**,
**risk**. Supersedes the loose next-steps in `SHOPSQUIRE_ROADMAP_CANONICAL_2026-06-18.md` for
*execution detail*; that doc remains the strategy/phase reference.

## Verified current state (2026-06-19)

- `recommend.py` = **13,492 lines** (from 14,588 at session start; 15 commits, suite green throughout).
- Extracted services: `recommend_utils`, `recommend_budget_advisor`, `recommend_nqe_stage`,
  `recommend_vision_stage`, `recommend_image_hints`, `checkout_handoff`, `safe_stage`.
- Reliability: `safe_stage` wrapper + AST silent-except **ratchet** (`tests/test_no_silent_except_in_core.py`,
  recommend.py baseline **226**, ratchet down only).
- Determinism: autouse cache resets (`tests/conftest.py`) + `make test-determinism`; ASUS class closed
  (cache stamp + grounding flavour excised).
- Profiles exist: `config/store_profiles/electronics.json`, `…/pharmacy.json`.

---

## The ordered plan (ROI × safety)

### T1 — Latency benchmark harness (do first; everything after is measured)
- **Why:** "latency claims backed by spans" — no change ships without a before/after number.
- **Files:** new `scripts/bench_recommend.py` (drive `/api/v1/recommend/suggest` N× over fixed
  queries, read `timing_breakdown` from the response, print p50/p95 per stage:
  `guard_ms, security_analysis_ms, nlp_ms, catalog_profile_ms, summary_ms, route_total_ms` +
  a derived `trace_write_ms`). Optionally `make bench`.
- **Wire:** nothing in prod; reads existing `timing_breakdown` ([recommend.py:11435](../src/app/routers/recommend.py)).
- **Tests:** `tests/test_bench_smoke.py` — asserts the harness parses a response and emits stage p50s.
- **Risk:** none (read-only).

### T2 — Trace-write batching (the #1 latency win)
- **Why:** `log_trace_event(durable=True)` does a full `with db_session(): INSERT` per call
  ([decision_log.py:774](../src/app/services/decision_log.py)); recommend.py calls it **110×**
  (15–40 fire/request) → tens of sync DB round-trips on the hot path.
- **Files:** `src/app/services/decision_log.py` (add batch buffer + flush, near the existing
  `_cache_trace_event` :156 / `get_cached_trace_events` :167); `src/app/routers/recommend.py`
  (begin batch at route start ~`route_t0` :5342, flush at response assembly ~:11435).
- **Wire (mechanism already exists — reuse it):**
  - Add `begin_trace_batch(trace_id)` / `flush_trace_batch(trace_id)` keyed by `trace_id` (ContextVar
    or dict). While a batch is active, `log_trace_event(durable=True)` **appends to the buffer**
    (still calls `_cache_trace_event` so live readers/SSE are unaffected) instead of an immediate
    INSERT. `flush_trace_batch` does ONE `executemany` into `decision_trace_events`.
  - Keep the **decision record** (`log_decision`) durable-immediate; only the high-volume
    `log_trace_event` stream batches.
  - Fall back to current per-event behaviour if no batch is active (other call sites unchanged).
- **Tests:**
  - `tests/services/test_trace_batch.py` — N buffered events → 1 bulk insert; **event count + payloads
    identical** to unbatched (parity); `get_cached_trace_events` still returns them mid-request;
    flush is idempotent; an insert failure doesn't lose the in-process cache.
  - extend `tests/test_recommend.py` — assert a known query still emits its key trace events
    (security_scan, image_feature_gate, grounding_ladder) after batching.
- **Risk:** low–med (audit path). Parity test is the guard. **Biggest latency win, no behaviour change.**

### T3 — Non-blocking / skippable narration (the #2 latency win)
- **Why:** `_summarize_results` ([recommend.py:4243](../src/app/routers/recommend.py)) runs **inline**
  in `StageTimer("summary_ms")` ([:11868](../src/app/routers/recommend.py)) on `qwen3:14b` — seconds.
- **Files:** `recommend.py` (call site :11868–11872; deterministic fallback
  `_deterministic_assistant_message`, now in `recommend_budget_advisor`); the SSE/job path that
  already yields `llm_summary_job_id`.
- **Wire:**
  - **Skip-when-confident:** if `_deterministic_assistant_message` returns a confident answer
    (budget/brand verdict present), set `assistant_message` from it and **do not call the LLM**
    (gate behind `NARRATION_LLM_SKIP_WHEN_DETERMINISTIC=1`).
  - **Async-when-needed:** return ranked `results` immediately; enqueue the LLM summary under
    `llm_summary_job_id`; client streams it via the existing SSE/poll endpoint. Flag
    `NARRATION_ASYNC=1`, default off until the frontend consumes the job.
- **Tests:** `tests/test_recommend.py` — with skip flag on + a budget query, response has a non-empty
  `assistant_message`, `summary_ms` ≈ 0, and no LLM call (monkeypatch the provider to assert
  not-called); with async flag on, `results` present + `llm_summary_job_id` set.
- **Risk:** med (UX/contract change) — flag-gated, default off.

### T4 — Cheapen per-request DB work
- **Files:** `grounding_ladder.py` (`_catalog_stamp` COUNT(*) — I added it); the stock/catalog reads in
  `recommend.py` fast-path (~:890–1031) and price fallback (~:9440–9800).
- **Wire:** cache the catalog stamp for a few seconds (or `MAX(updated_at)` served by an index);
  batch stock annotation into one `IN (:skus)` query; fan out the **independent** sequential stages
  (`guard ∥ nlp ∥ catalog_profile`) via a small `ThreadPoolExecutor` (route is sync/threadpool, safe).
- **Tests:** `tests/services/test_grounding_ladder.py` — stamp cache hit avoids a 2nd COUNT within TTL;
  determinism gate still green (autouse reset already covers brands cache).
- **Risk:** med (parallelism) — keep fan-out to provably independent stages only.

### T5 — V2 shadow decision
- **Why:** `RECOMMEND_PIPELINE_V2=1` shadow runs scatter-gather then discards (compute-and-discard).
- **Files:** `src/app/services/recommend_pipeline.py`, `candidate_retriever.py` (RRF), the V2 branch in
  `recommend.py` (`RECOMMEND_PIPELINE_V2`).
- **Wire:** decide per env: **off** for latency-sensitive prod, OR real RRF fusion with a parity metric
  logged (not discarded). Add a `v2_shadow_divergence` trace metric if kept as shadow.
- **Tests:** `tests/test_recommend.py` — V2 off = monolith path unchanged; V2 fusion = parity metric emitted.
- **Risk:** med.

### T6 — Continue the split: inline VISION ORCHESTRATION → recommend_vision_stage (P2 main)
- **Why:** the pure vision decisions are extracted; the big inline block remains in `suggest()`.
- **Files:** `recommend.py` image ingest (~:5532–5770), image feature gate (~:5852–5912), product
  identity (~:8040–8140), grounding call (~:8222–8270), catalog relevance gating. Target
  `services/recommend_vision_stage.py`.
- **Wire:** extend `RecommendStageState` (from `recommend_nqe_stage`) with vision fields
  (`image_context, image_cv_signals, image_feature_allowlist, strict_image_brand_hint,
  catalog_relevance`); `run_vision_stage(state, hooks) -> state`; re-export; convert its silent
  excepts to `safe_stage` as you go (ratchet recommend.py **down**).
- **Tests:** `tests/services/test_recommend_vision_stage.py` (characterization on the moved block);
  full `tests/test_recommend.py` green incl. the ASUS/Apple ordering; ratchet lowered.
- **Risk:** **high** (most coupled) — do as a dedicated pass, one cohesive sub-block per commit.

### T7 — Agnostic core, slot-by-slot (see table) + the pharmacy proof test
- **Risk:** low per slot (proven pattern). The **pharmacy characterization test is the deliverable
  that makes "agnostic" true.**

### T8 — Supplier-comms port + mandatory gate (correctness gap)
- **Why:** reorder creates a PO row but supplier *send* isn't behind one gate.
- **Files:** new `src/app/ports/supplier_comms.py` (`SupplierCommunicationPort`); send capability
  `playbook_action_adapters.py:91`; domain guard `supplier_domain_guard.py:105`; gate
  `execution_gate.decide(...)` :80 (**action `supplier_contact` already in `CONSEQUENTIAL_ACTIONS`
  :33** — wiring only); inventory `inventory_agent.py:974`.
- **Wire:** every supplier send → `execution_gate.decide("supplier_contact", …)` → domain/governance
  check → **draft-first** unless approved; trace event chains query → inventory state → PO → approval
  → send. Human approval for new supplier / changed bank / changed domain / high-value PO.
- **Tests:** `tests/test_supplier_comms_gate.py` — send blocked without `decide` pass; untrusted domain
  quarantined; draft-first default; approval unlocks; trace chain present.
- **Risk:** med (consequential path) — draft-first keeps it safe for demo.

### T9 — Ops / hygiene (parallelizable, low risk)
- Activate visual search: `VISUAL_SEARCH_INDEX_ON_START=1` and/or schedule Celery
  `refresh_visual_search_index` ([model_ops_tasks.py:199](../src/app/tasks/model_ops_tasks.py)); close the
  **empty-index** observability gap (emit degraded when `is_available()` but index_size 0).
- `pip`/poetry add **pytest-randomly** → wire random-order into `make test-determinism` (expect it to
  surface more order-dependence repo-wide — triage then).
- `.gitignore` (or stop in-place rewrite of) `config/security/cv_playbooks.json` churn.
- **Owner decision:** canonical recommendation entry point among `recommend.py` /
  `services/recommendations.py` / `services/recommend_pipeline.py` (V2).
- Archive/commit the 4 untracked `docs/SHOPSQUIRE_*_2026-06-18.md`.

---

## Agnostic core — slot-by-slot (T7 detail)

| Module | Flavour to excise | → Profile slot | Test |
|---|---|---|---|
| `recommend_budget_advisor` | use-case/budget floors, gaming/office prose | `use_case_floors`, `budget_copy` | parity: inline == profile floors; pharmacy floors differ |
| `recommend_utils` | brand alias/display, spec tokens | `manufacturers` (exists), `spec_tokens` | parity: inline ⊆ profile union |
| `recommend_vision_stage` | supported-brand list | reuse `manufacturers` keys | parity: list == manufacturers keys |
| `upsell_engine` | gaming/university/office cross-sell map (`_USE_CASE_CROSS_SELL`) | `upsell_companions` (exists) | parity + **pharmacy companions actually fire** |

> **Upsell finding (CORRECTED after full read — upsell is largely already agnostic):**
> `recommend()` ([upsell_engine.py:248-289](../src/app/services/upsell_engine.py)) combines THREE
> signals: (1) **co-purchase affinity** (basket co-occurrence SQL) — agnostic by nature; (2) a
> **use-case** path (`_detect_use_case` + `_category_expansion_candidates` over `_USE_CASE_CROSS_SELL`)
> — *documented legacy* (comment line 254: "relies on p.category which the demo schema lacks, so
> usually empty — kept for stores that DO have a category column"); (3) **companion-TYPE expansion**
> (`_companion_type_candidates` → `product_classifier.companion_types_for` → profile
> `upsell_companions`, product_classifier.py:140) — **agnostic and profile-backed**. So the profile
> slot is NOT dead and pharmacy IS covered via path (3) (`medicine→[first_aid, device]` fires when the
> carted item classifies as `medicine`). The only remaining flavour is the LEGACY electronics
> use-case map (path 2), which is inert on the demo schema. **Work is small:** (a) a **pharmacy
> characterization test** proving path (3) fires cross-vertical (medicine→first_aid, no laptop leak) —
> this PROVES the agnostic claim; (b) optional cleanup — remove path (2) or profile-back
> `_USE_CASE_CROSS_SELL`/`_detect_use_case` so no electronics literal remains in core. Net: upsell is
> ~80% agnostic already; the deliverable is the proof test + clearing the legacy literal.
| `use_case_advisor` | electronics use-case map | `use_cases` (exists) | parity per use-case |

**Method per slot (proven on grounding vocab):** literal → profile slot → accessor with
**union/inline fallback** (parity-safe) → parity test → later drop fallback → add module to
`tests/test_no_flavour_in_core.py::_CORE_MODULES`.

**The proof (T7 capstone):** `tests/test_pharmacy_vertical.py` — load `pharmacy.json`, run a pharmacy
query, assert the response carries **zero** laptop/GPU/brand flavour (reuse `_FLAVOUR_RE` from the
no-flavour lint against the response + constraints). This is what makes "agnostic" verifiable.

---

## Definition of done (the bar)

- Full route suite green in **fixed and random** order (needs pytest-randomly, T9).
- Every recommendation: traceable inputs, policies, candidate sources, ranking reasons, confidence.
- Image inputs help ranking only via safe, provenance-tagged hints; suspicious images never block
  commerce unless policy requires; LLM makes **no** unsupported product claims (claim guard).
- Store flavour lives in profiles; `test_no_flavour_in_core` covers each extracted core module.
- V2 is real fusion or measurable shadow — not compute-and-discard.
- Latency claims backed by `timing_breakdown` spans (T1 harness); trace audit is batched, not 40 sync
  writes/request.
- A second vertical (pharmacy) passes its characterization test.

## Sequencing summary

```
T1 bench  → T2 trace-batch → T3 narration → T4 db/parallel   (latency, biggest wins first)
          → T5 V2 decision
          → T6 vision orchestration extraction (high-risk, dedicated)
          → T7 agnostic slot-by-slot + pharmacy proof
          → T8 supplier-comms gate
T9 ops/hygiene runs in parallel throughout (low risk).
```
