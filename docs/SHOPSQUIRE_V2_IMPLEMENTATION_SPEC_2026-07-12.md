# V2 Implementation Spec — exact wiring + tests, phase-ordered (2026-07-12)

The precise build spec for the reordered roadmap, with file:line anchors verified against
`3dfb5a0`. Companion to the analysis (`SHOPSQUIRE_V2_WORKLOAD_PERSONA_INTENT_ANALYSIS`) and the
review/clickthrough memory notes. **What we are trying to garner is stated per phase — the
"why", not just the "what".**

## What we are garnering (the through-line)

The rebuild's goal is a commerce brain where **the model interprets language and deterministic
code validates catalog/taxonomy/constraints/security** — replacing `suggest()`'s 7,250 lines of
regex. The live clickthrough proved the payoff is real: "do you sell forklifts?" returns *7
gaming laptops* on the shipping product; "valorant at 144fps" returns *0 products*. Both are
live bugs V2 fixes. But the clickthrough also proved V2 is **shadow-ready, not canary-ready** —
three gaps stand between "works in tests" and "safe on real traffic". Each phase closes one
class of gap and each is gated by MEASUREMENT, never by assertion.

---

## PHASE A — make measurement + safety real (unblocks everything)
**Garner:** the ability to SEE V2 vs V1 on real/replayed traffic without serving it, and the
guarantee that an un-onboarded tenant never gets silent garbage. You cannot tune quality you
cannot measure, and you cannot canary a path that fails open on empty data.

### A0 — Ungrounded-tenant guard (SMALL, do FIRST — clickthrough issue #1)
The core hard-depends on `product_classification`/`sold_taxonomy`; an empty tenant degrades
SILENTLY (no refusals, arbitrary text search, "nothing meets"). Today only `grounding=='error'`
is handled.
- **WIRE:** `core.py:44-46` handles `"error"`; add `"empty"` → return a degraded response that
  says "catalog not onboarded for this store" (new reason), OR let the facade fall to legacy.
  Preferred: `recommendation_facade.py:191` — extend the fall-through to
  `core.grounding in ("error","empty")` so an ungrounded tenant is served by legacy, never by a
  silently-degraded core. Add an `unclassified_active_count>0` check (already in
  `catalog_read_model.coverage_report`) as the onboarding-completeness signal.
- **TEST:** `test_recommend_core_dispatch.py` — a tenant with 0 sold_taxonomy rows → facade
  returns None (legacy serves); a grounded tenant → core serves. Unit: `core.py` with
  `grounding_status` monkeypatched to "empty".

### A1 — Shadow worker + Redis Stream (review-4 #4)
`recommendation_facade.py:81-91` enqueues to `shadow:core:queue` (a capped LIST) but NOTHING
drains it → shadow records without diffing.
- **WIRE:** new `src/app/workers/recommendation_shadow_worker.py`: BRPOP the queue → rebuild
  `TurnEnvelope` → `recommend_turn` → load the recorded/served V1 → `recommend_parity_full.
  evaluate_case` → persist metrics → dead-letter on repeated failure. Convert the list to a
  Redis **Stream** (`XADD`/`XREADGROUP`) for ack + retry + retention. Register in `celery_app.py`
  beat or a standalone worker.
- Also fix `recommendation_facade.py:145` job payload — currently only {query,uid,tenant,trace};
  add budget, image/security state, guard verdict, engine version so the diff is faithful.
- **TEST:** integration — enqueue N jobs, run worker, assert metrics rows + dead-letter on a
  poisoned job.

### A2 — Facade-mode replay (review-4 "not deployment-path faithful")
`shadow_replay.py` scores procurement/policy/inventory/claims lanes as V2 FAILURES, but the
facade sends those to legacy BY DESIGN (`recommendation_facade.py` CANARY_LANES at line 48).
- **WIRE:** add a `--facade-mode` to `shadow_replay.py` that, for non-CANARY lanes, records
  "delegated-to-legacy" as the INTENDED outcome (not a diff). Then the census reflects the real
  deployment path.
- **TEST:** replay with `--facade-mode` → the 10 BLOCKERs on delegated lanes reclassify as
  "intended".

### A3 — Real telemetry (review-4 #5)
`recommendation_postflight.py:83` imports `record_event` which DOES NOT EXIST → every call logs.
- **WIRE:** add `record_event(name, fields)` to `src/app/observability/metrics.py` (near the
  existing recommendation metrics ~:916), backed by Prometheus counters/histograms: latency,
  fallback_reason, lane, grounding_failure, empty_rate, session_write_success, model_timeout.
- **TEST:** `emit_telemetry` increments the metric (registry assertion), no longer falls to log.

### A4 — Green the ratchets (review-4 #7)
4 pre-existing legacy failures (recommend.py 186 silent vs 183 baseline; hippograph 0→1;
narration_stage `vram`; recommend.py flavour 19 vs 20). NOT V2 regressions but the suite is red.
- **WIRE:** convert the 3 drifted `recommend.py` swallows to `record_partial_failure` (reduce
  186→183) OR reconcile baselines honestly with dated notes; fix hippograph's 1 swallow; reword
  narration_stage's `vram`. Make `pytest tests/test_no_*_in_core.py` CI-mandatory.
- **TEST:** both ratchet files green.

---

## PHASE B — trustworthy quality (unblocks canary)
**Garner:** a promotion gate that measures whether V2's products are actually GOOD (relevant,
precise, authorized), not merely present. Today `gates_pass` (recommend_parity_full.py:241)
checks only BLOCKER=0 + message-class + known_wrongs — NOTHING about product quality. The
clickthrough proved why this matters: valorant "passes" 3/3 while returning "No product meets".

### B1 — constraints.py: ranges + provenance (review-4 Q1)
The `(op, threshold)` one-slot shape (`intent_resolver.py:71-107`) cannot hold a floor AND a
ceiling; my "incoming-wins" merge (`intent_resolver.py:107`) is a patch, not a model.
- **WIRE:** new `src/app/services/recommendation_core/constraints.py`:
  `RequirementConstraint(lower, upper, preferred, provenance:list)`. Merge by INTERSECTION —
  floor+floor→max, ceiling+ceiling→min, floor+ceiling→range, floor>ceiling→CONFLICT (needs
  clarify). Replace the `Dict[str,Tuple[str,float]]` in `intent_resolver.resolve` (:154),
  `turn_router` (clamp-3 ~:196-212), `fit.build_cards` (evaluate_requirements consumer), and
  `ranking.rank_key`. Surface conflict in `extras.intent` for the trace.
- **TEST:** `test_constraints.py` — floor+ceiling→range; floor>ceiling→conflict flag;
  'nothing over 8GB' + university floor 16 → conflict surfaced, not silent inversion.

### B2 — quality.py: the intrinsic gate (review-4 #1)
- **WIRE:** new `src/app/services/recommendation_core/quality.py`: over a LABELED corpus,
  compute precision@10, NDCG@10, constraint-satisfaction rate, diversity, empty-rate, and
  **unauthorized-product-rate** (any shown product not active/authorized/in-budget/in-category).
  Extend `recommend_parity_full.summarize_run` (:202) so `gates_pass` (:241) ALSO requires
  quality thresholds. Reuse `tests/golden/classification_labels.json` pattern for a sealed
  relevance-label set (dev vs test split — the eval must not train on the gate).
- **TEST:** `test_quality.py` on the labeled set; a run that returns one safe-but-irrelevant
  product FAILS (precision alone is gameable — must also hit recall/NDCG).

### B3 — batch retrieval + deterministic order (review-4 #6, clickthrough issue #2 partial)
`evidence.py:84-85` calls `get_variant` per SKU = N+1 (30×3≈90 queries/turn). Taxonomy path
(`_skus_for_node`) and canonical `search_variants` (`catalog_read_model.py:218`) have no
ORDER BY → arbitrary open-query results. (Legacy search at :158 IS price-ordered.)
- **WIRE:** add `catalog_read_model.get_variants(db, skus, tenant_id, mode)` — one query per
  table (variants+prices+stock via `WHERE sku IN (...)`), replace the loop at `evidence.py:84`.
  Add `ORDER BY` to `_skus_for_node` and the canonical search (:218). Record query-count in
  `EvidenceBundle`.
- **TEST:** `test_evidence` asserts query count is O(1) not O(N); deterministic order across runs.

---

## PHASE C — smarter model (the intelligence + multi-turn)
**Garner:** the model takes MORE responsibility (structured intent, not regex) and multi-turn
works — so we stop patching with census-specific rules and 'those'/'the first one' resolve.

### C1 — two-slot intent (review-4 Q2, clickthrough issue #2 full)
`turn_router.py` collapses product + workload into one node; the workload strip (:268-271) sets
`node=None`, losing the device category → valorant does a broad search ("nothing meets") while
'gaming laptop for valorant' works.
- **WIRE:** extend `TurnDecision` (:115) with `requested_product_node`, `workloads:list`,
  `relationship` (run_on|buy), `action`. The router prompt returns them; clamp each. Replace the
  `_WORKLOAD_RE` strip (:268) — a `run_on` workload REROUTES retrieval to the store's primary
  sold DEVICE node (needs a `taxonomy_registry.primary_sold_node(tenant)` helper = most-
  classified sold node, or a store-profile field), NOT None. Keep the regex only as a
  `router_fallback_reason`-tagged fallback.
  - **Quick win available now (~10 lines):** even before full two-slot, change `:271` from
    `node = None` to reroute to the primary sold device node → valorant → gaming laptops.
- **TEST:** 'play valorant' → routes to gaming laptops (not broad); 'buy valorant'→refusal;
  'case for laptop'→accessory; two-slot fields clamped.

### C2 — session consumption (review-4 #2)
`envelope.session` is WRITTEN (postflight) + READ (facade) + CARRIED (envelope) but CONSUMED
NOWHERE — dead wiring. `route_turn` (:179) and `resolve` (:154) ignore it.
- **WIRE:** `turn_router.route_turn` reads `envelope.session` for prior-subject: 'those'/'the
  first one'→prior shortlist SKUs; a bare filter fragment ('16GB or more')→prior node+
  constraints. This DELETES the FILTER-guard and sold-name-veto (census-specific proxies for
  exactly this).
- **TEST:** turn1 sets session; turn2 'why is the first one better' resolves against turn1's
  shortlist; the deleted guards' cases now handled by session.

### C3 — flavour data-move (review-4 Q3)
`intent_resolver._SPEC_MAP` (:35) + `_GPU_TIER_VRAM` (:44) hardcode `refresh_hz`/vram in core →
trips the no-flavour ratchet (5 modules can't enroll).
- **WIRE:** move the KB-key→attribute mapping into attribute-registry data
  (`{key, aliases:[refresh_hz_min], default_operator:">=", unit}`), have the KB use canonical
  attribute keys directly, GPU tiers → data-backed capability profiles. Then enroll
  intent_resolver/turn_router/core/fit/envelope in `test_no_flavour_in_core.py:_CORE_MODULES`.
- **TEST:** all 12 V2 modules in both ratchets, green.

---

## PHASE D — soak & ramp
**Garner:** confidence from real traffic before real exposure. shadow soak (0 queue loss, p95 in
budget, quality gate green) → `canary:1` on text-only CANARY_LANES → ramp → primary → archive
`suggest()` after 4wk. `RECOMMEND_CORE_MODE` stays `off` until A0+A1 land; `shadow` once A1's
consumer exists; `canary:1` only when B (quality) + C2 (session) + A3 (telemetry) + A4 (green
ratchets) are done — GPT-5.6's bar, confirmed.

---

## Reorder rationale
A0 (ungrounded guard) promoted to FIRST — it is small and the only SAFETY bug (silent
degradation) the clickthrough found. The C1 "quick win" (reroute instead of None) can land in
Phase A opportunistically since it is ~10 lines and demo-visible. Otherwise the A→B→C→D
dependency order holds: measure+safe → trustworthy quality → smarter model → soak.

## Test surfaces (consolidated)
- Unit: constraints range-merge, quality metrics, two-slot clamp, batch query-count, ungrounded guard.
- Integration (`tests/integration/test_recommend_core_dispatch.py`, NEW): tenant isolation, real
  persistence, guard block, image quarantine, degraded→legacy, ungrounded→legacy, session
  round-trip+CONSUME.
- Replay: `shadow_replay --facade-mode` (fallback = intended) + intrinsic quality (NDCG/precision).
- Ratchets: `test_no_flavour_in_core` + `test_no_silent_except_in_core` GREEN, CI-mandatory.
- Live: shadow-soak dashboards (fallback rate, p50/p95, query count, empty rate) BEFORE canary.
