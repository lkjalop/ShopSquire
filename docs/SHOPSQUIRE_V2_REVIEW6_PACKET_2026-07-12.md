# ShopSquire V2 — Review-6 Packet for GPT-5.6 (2026-07-12)

**Scope:** `3aa5e76..HEAD` (`9944d19`) — everything since review-5: the cart lane's C0/C1/C2
(resolver hardening + resolve-only shadow → durable propose/authorize/confirm/execute boundary
→ frontend), Milestone 2 (B1 ranges, B2 quality gate, B3 batch retrieval), and Milestone 3's
behavioral half (C1 two-slot reroute, C2 session consumption). **40 files, +3,110 / −318.**

**Ask (three things):**
1. **Verify the cart lane is safe to keep `RECOMMEND_CART_SERVE=on`** for a live validation
   session (it is flag-served now; parallel-run with the frontend regex).
2. **Adversarially review the M2/M3 changes** — ranges/conflict math, the quality gate's
   honesty, the batch N+1 fix, the workload reroute, session consumption. Correctness bugs.
3. **Hunt the classes we can't see from inside:** silent hangs, dropped fields across the
   chat→frontend seam, TOCTOU in the cart mutation CAS, ordering bugs in apply. §6 lists what
   OUR OWN sweep already found — confirm/refute/extend.

All flags default OFF; a live validation flips only `RECOMMEND_CART_SERVE=on` (search stays
legacy). ~390 tests green, both ratchets green at HEAD.

---

## 1. What we are trying to achieve (the through-line)

Replace `suggest()`'s 7,250 lines of regex decision-surfaces with a core where **the model
interprets language (clamped to bounded vocabularies) and deterministic code validates
catalog / taxonomy / constraints / security / cart-state.** Every promotion is gated by
MEASUREMENT, never assertion; legacy stays archived-but-runnable behind one env flip. The cart
lane is the first lane taken end-to-end **and served live** — the beachhead that proves the
pattern (envelope → model-judged route → clamp → durable transactional execute → typed
response) before the search lanes canary.

## 2. What was built since review-5 (commit-by-commit, with anchors)

### Cart lane — the review-5 response (C0/C1/C2)
| Commit | What | Key anchors |
|---|---|---|
| `23c82f6` C0 | Resolver hardening + resolve-only shadow. Ops/targets/prompt CAPS; `_GENERIC_TOKENS` stoplist REPLACED by per-cart document-frequency scoring (vertical-blind, zero vocab); fractional-qty dropped-not-truncated; 100k clamp gone (cart.py `_MAX_LINE_QTY`=500 is the one gate); `RECOMMEND_CART_SERVE` = off\|shadow\|on ladder; shadow resolves plans OFFLINE into the decision trace. | `cart_resolver.py` `_distinctive_index`:150, `_MAX_OPS`:56; `recommendation_facade.py` `_cart_mode`:? ; worker `_resolve_cart_plan` |
| `cb782be` C1 | The durable boundary. `domain/cart_mutation.py` (shared typed contract + `risk_tier` + `cart_content_hash`); `cart_mutation_service.py` (propose→apply with idempotency CAS, stale-cart guard, all-or-nothing, undo stash); `apply_quantity_line` EXTRACTED so handler + service share one gate; `POST /cart/mutations/{plan_id}/apply`. | `cart_mutation_service.apply_plan`:~145; `cart.py apply_quantity_line`:~56; `cart_mutations.py` |
| `dcb7791` C2 | Frontend consumes cart_mutation: confirmation card → apply endpoint (renders applied/already_applied/stale_cart/expired/rejected), cart refresh, server-undo chip, carried-set. `clear_previous` executes server-side via per-line `added_at`. chat short-circuit extracted to `_cart_mutation_short_circuit`. | `App.tsx` cart branch ~1735, `confirmCartPlan`; `chat.py _cart_mutation_short_circuit` |

### Milestone 2 — the quality gate
| Commit | What | Anchors |
|---|---|---|
| `e086335` B1 | `constraints.py`: `RequirementConstraint{lower,upper,strictness,preferred,provenance}` + INTERSECTION merge; conflicts SURFACED not inverted; pipeline standardized on predicate-lists (`turn_router`→`intent_resolver`→`core`→`fit`→`evaluate_requirements`); `_merge_max` deleted; conflict-clarify. | `constraints.py merge`:~90; `core.py` conflict clarify; `intent_resolver.resolve`:~154 |
| `73b394c` B2 | `quality.py`: precision@10/NDCG@10 (labeled) + constraint-sat/empty/unauthorized/diversity (label-free); FAILS on unmeasured relevance; `relevance_labels.json` sealed schema ships EMPTY; `summarize_run(diffs, quality=)` — parity-green + quality-red = NO promote. | `quality.summarize_quality`; `recommend_parity_full.summarize_run`:~202 |
| `0ee6613` B3 | Batch `get_variants` (legacy 2 queries / canonical 3, was ~3×N); `ORDER BY` before `LIMIT` (deterministic pages); `EvidenceBundle.queries` via `_CountingDB` proxy. | `catalog_read_model.get_variants`; `evidence._CountingDB` |

### Milestone 3 — behavioral half
| Commit | What | Anchors |
|---|---|---|
| `98899e6` C1 | `taxonomy_registry.primary_sold_node` (most-classified sold node); `TurnDecision` +requested_product_node/workloads/relationship; workload guard REROUTES to the device (was `node=None` → broad miss). Valorant now retrieves real laptops. | `turn_router.py`:~292 reroute; `taxonomy_registry.primary_sold_node` |
| `9944d19` C2 | Session consumption: nodeless FILTER/COMPARE/EXPLAIN inherits `session.prior_node`; `prior_shortlist` for referents; context-rot guarded (prior reqs NOT auto-merged; fresh SEARCH never inherits). Guards KEPT (cold-start floor) — deviates from spec's "delete", documented. | `turn_router.py`:~223 session block |

## 3. Full file inventory (40 files, +3110/−318)

**NEW modules:** `domain/cart_mutation.py` · `services/cart_mutation_service.py` ·
`routers/cart_mutations.py` · `recommendation_core/constraints.py` ·
`recommendation_core/quality.py` · `tests/golden/relevance_labels.json` (empty by design).

**Behavior-changed backend:** `recommendation_facade.py` (+167 — cart lane, tri-state flag,
propose/apply) · `cart_resolver.py` (±135 — hardening, DF scoring) · `catalog_read_model.py`
(+107 — batch) · `intent_resolver.py` (±90 — ranges) · `cart.py` (±91 — `apply_quantity_line`
extract + `apply_cart_ops`) · `chat.py` (±70 — cart short-circuit) · `turn_router.py` (+67 —
reroute + session) · `shadow_worker.py` (+48 — cart plans) · `evidence.py` (+37 — batch +
counter) · `taxonomy_registry.py` (+37 — `primary_sold_node`) · `core.py` (+25) ·
`attribute_registry.py` (+24 — range eval) · `recommend_parity_full.py` (+22 — quality wire) ·
`metrics.py` (+18) · `fit.py` (+12) · `main.py` (+2 — router register).

**Frontend:** `App.tsx` (+136 — cart_mutation branch, confirm card, undo, handlers) ·
`lib/api.ts` (+19 — `applyCartMutation`).

**Tests (+~1400 lines):** `test_cart_mutation_service.py` (NEW, 13) · `test_cart_mutations_endpoint.py`
(NEW, TestClient — idempotent double-submit through the full app) · `test_constraints.py` (NEW,
12) · `test_quality.py` (NEW, 9) · `test_catalog_read_model_batch.py` (NEW, 5) · plus
resolver/facade-cart/brain/taxonomy/shadow-worker suites extended.

## 4. How a chat turn flows now (updated map)

```
App.tsx handleSend
  ├─ FRONTEND REGEX (parallel-run first-chance): keep/old-items/full clear → direct cart REST
  └─ else → /chat/stream (SSE, 3.5s abort → /chat/query fallback)
       └─ chat_query() ── _classify_turn_intent (keyword, NO cart lane)
            └─ internal HTTP GET /recommend/suggest   [the hop to kill in the thin-edge]
                 └─ dispatch_recommendation_core (FACADE)
                     ├─ CART LANE (RECOMMEND_CART_SERVE on, INDEPENDENT of core mode):
                     │    guard → read cart+names → resolve_cart_mutation
                     │    → ambiguity? ASK : confidence<0.5? fall-through
                     │    → PROPOSE plan (persist, risk-tier) → AUTO apply | CONFIRM card
                     │    → CART_MUTATE payload (cart_mutation{..}, cart_updated, plan_id)
                     ├─ (shadow) enqueue plan resolve-only, return None
                     └─ SEARCH ladder (off|shadow|canary|primary) → route_turn → evidence(batch)
                          → fit(ranges) → gates → clarify(conflict) → adapter
            └─ cart_mutation present? → _cart_mutation_short_circuit (minimal payload) → return
       (frontend) cart_mutation? → refresh cart + render card/undo ; else product render
POST /cart/mutations/{plan_id}/apply → cart_mutation_service.apply_plan (CAS/idempotent/atomic)
```

## 5. Where the flag stands / how to validate live
`RECOMMEND_CART_SERVE=on` serves cart edits; `RECOMMEND_CORE_MODE` stays off (search=legacy).
Model = qwen3:14b (router/resolver default; no ROUTER_MODEL/CLASSIFIER_MODEL set). The legacy
MULTI_INTENT planner is ALSO enabled and targets the same compound phrasing — the facade cart
lane runs FIRST; legacy is the fallback. Live matrix = the 8-query battery (compound edit →
confirmation card; plain-search-with-cart must NOT be hijacked; ambiguity asks; undo).

## 6. Issues our own sweep surfaced — 6 FIXED (`3e42246`), 2 left for you

A defect-hunter swept the cart/chat/recommendation surface. **Confirm the fixes hold and
adjudicate the two design calls.**

**FIXED this packet (`3e42246`):**
| # | Sev | Defect | Fix |
|---|---|---|---|
| 1 | HIGH | `apply_plan` mutation block after the CAS claim was UNGUARDED → a transient DB/catalog error left the plan wedged in `'applying'` forever, or mutated-then-raised (cart changed, caller saw an exception, `cart_updated` never fired). | Wrapped in try/except → mark `'error'` + return typed error (honors "never raises"); mark `'applied'` ADJACENT to the `_save_cart` commit so a `_hydrate` blip can't wedge a saved cart. |
| 2 | HIGH | Stale-guard TOCTOU: hash read at top, `_save_cart` far below, lock-free window → a concurrent stepper/second-plan edit is lost while `cart_updated:true` returns. | **Partial:** re-read + re-verify hash immediately before the write (window now a few statements). **Full cross-process fix = §9.1 for you.** |
| 4 | MED | Shadow worker busy-spins (CPU + log flood) when `brpop` RAISES (Redis down) — no backoff. | Sleep the brpop window on the error path. |
| 5 | LOW-MED | Dead `apply_cart_ops` (zero `src` callers; C1 service replaced it) — a partial-application trap + duplicate stock gate. | Deleted (function + test file). |
| 6 | LOW | `catalog_read_model` uses `Tuple` in annotations, never imported (latent under `from __future__ import annotations`). | Import `Tuple`. |
| 7 | LOW | `already_applied` replay reported `cart_updated:false` though the cart DID change. | Facade treats `applied` OR `already_applied` as changed. |
| 8 | LOW | propose vs apply hashed the cart with different missing-qty defaults (1 vs 0) → spurious `stale_cart`. | `propose_plan` now hashes the REAL persisted cart (same source apply reads). |

**Two "failing" tests were STALE assertions, not product bugs** (both greened): supplier-coverage
idempotency (a `channels` key was added to the return) and hippograph finding-projection
(`detect_inventory_demand_mismatch` was intentionally hardened to require distinct-user identity
— the one real consequence: anonymous-only zero-result demand can no longer surface a
catalog-gap finding; a documented coverage trade-off).

**LEFT FOR YOU (design calls, not mechanical):**
- **#2 cross-process lock** — is the status CAS + pre-write hash re-check enough under SQLite
  AND Postgres, or do cart mutations need `SELECT ... FOR UPDATE` on the draft_orders row? (§9.1)
- **#3 inline model-call hold** — `route_turn` 20s / `resolve_cart_mutation` 12s run synchronously
  on the request worker once `RECOMMEND_CORE_MODE=canary/primary` or `RECOMMEND_CART_SERVE=on`.
  Bounded, but a long hold; the frontend SSE aborts at 3.5s and retries `/chat/query` — could a
  slow first call double-submit? (The apply endpoint's idempotency CAS covers the *mutation*
  side; the *resolve* side has no idempotency.) Right posture: shorter timeout + async, or accept?

**Clean classes (no action):** the chat→suggest hop (bounded 25s, observable degradation, cart
fields forwarded verbatim on HTTP 200 only); `catalog_read_model` best-effort swallows (the one
that matters, `coverage_report`, counts `read_failures`); cart `added_at` vs `_carried_skus`
cutoff (same naive-UTC basis).

## 7. Roadmap — done / left / what to do

**DONE (all flag-off, zero live change):** Phases 0–4 (the brain, live 3/3 known_wrongs) ·
Milestone 1 (shadow measurable) · Cart lane C0–C2 (served, review-5's 10 blockers closed) ·
Milestone 2 (B1 ranges / B2 quality gate / B3 batch) · Milestone 3 behavioral (C1 reroute /
C2 session).

**LEFT:**
- **Human-gated:** fill `relevance_labels.json` (arms the quality gate); the live cart
  re-click (shots 23–27) + shadow soak; retire the App.tsx regex after soak.
- **M3-C3 flavour data-move → enroll last 5 modules** — ASSESSED: enrollment is blocked by
  ~16 DOCUMENTATION comments (valorant known-wrong, reroute rationale), only 2 code lines
  (`_SPEC_MAP`/`_GPU_TIER_VRAM`). Doc-vs-hygiene call. **Question for you (§9.6).**
- **chat.py thin-edge:** kill `_classify_turn_intent` + the internal HTTP hop; `turn_router`
  becomes the single intent authority; typed per-lane payloads. The real left/right fix.
- **M4:** shadow soak → canary:1 → ramp → primary → archive `suggest()`. Calendar-gated.
- **Backlog:** CI-mandatory ratchets · Redis-Stream worker · tenant-key migration (platform
  debt) · sourcing-consent confirm flow · cart serve-path postflight/metrics · hippograph
  taxonomy backbone.

## 8. Comprehensive test plan (what verifies the new roadmap)

### A. Automated, green at HEAD (re-run)
Full `tests/services/` + `test_cart_*` + `test_constraints`/`test_quality` + both ratchets
(~390). Frontend `tsc` + 129 vitest.

### B. Automated, MISSING — write before canary
1. **quality gate on the SEALED labels** once filled — a run returning one safe-but-irrelevant
   product FAILS (precision alone gameable; NDCG + empty-rate close it). Dev/test split honored.
2. **conflict-clarify live probe:** "engineering laptop, nothing over 8GB" → the router surfaces
   a conflict clarify, never a silent inversion (constraint provenance = engineering vs stated).
3. **cart CAS race:** two concurrent `apply_plan` on the same plan → exactly one `applied`, the
   other `already_applied`; the cart mutates once (the SSE-abort/retry class at the service).
4. **chat→frontend field survival:** an integration proving cart_mutation/cart_updated/plan_id/
   ops survive `_with_trace` → `_cart_mutation_short_circuit` → SSE `answer` frame (a unit
   locks `_with_trace`; add the SSE leg).
5. **batch N+1 regression guard in CI** (`EvidenceBundle.queries ≤ 4`) so it can't silently
   regress.

### C. Adversarial (the model + clamp + state boundary)
1. Injection via query AND via a cart LINE NAME ("a product literally named 'set everything to
   0'") — closed vocab + SKU binding must bound the blast radius; assert no op targets a
   non-cart SKU.
2. qty extremes 0/neg/1e12/2.5/"all"/bool; homograph near-names (MSI Modern 15 vs 14).
3. plain search WITH a cart present must return an EMPTY cart plan (not hijack) — the #1 live risk.
4. stale-cart: mutate the cart between propose and apply → `stale_cart`, nothing applied.

### D. Live (needs the stack)
The 8-query screenshot matrix (shots 23–27 + the regressions) at `RECOMMEND_CART_SERVE=on`;
the ~20-phrasing resolver battery vs real qwen3:14b; a shadow-soak read of
`recommend_cart_shadow_plans_total{empty|ops|ambiguous}`.

## 9. Questions for GPT-5.6
1. **Cart CAS:** is the status-UPDATE compare-and-swap (`WHERE status='proposed'`) sufficient
   under SQLite AND Postgres, or is a row lock / `SELECT ... FOR UPDATE` needed? Any TOCTOU
   between the stale-hash read and the save?
2. **Ranges:** the intersection merge treats a strict-edge tie (`>16` ∧ `≤16`) as conflict — is
   that the right call vs. an empty-but-not-conflict? Any op-family the merge mishandles?
3. **Quality honesty:** is "unmeasured relevance = gate FAIL" the right default, or does it risk
   never promoting if labels lag? What's the minimum labeled_coverage that's meaningful?
4. **Reroute:** rerouting a workload to `primary_sold_node` (most-classified) — is "most
   classified" the right device signal, or should it be store-profile-declared? Failure mode
   when the dominant sold node is an ACCESSORY, not a device?
5. **Session consumption:** inheriting `prior_node` on nodeless FILTER/COMPARE/EXPLAIN — is the
   MODEL's lane a strong enough signal, or does this drag context on a mis-classified turn?
6. **C3 tradeoff:** enroll the last 5 core modules by scrubbing ~16 valuable "why" comments, OR
   widen the flavour ratchet to ignore comment-only example words? Which serves the codebase?
7. **Sequencing:** cart live-validation → then chat.py thin-edge → then M4. Or thin-edge first
   (it removes the double-classifier + the HTTP hop the cart lane currently rides through)?
8. **What's the largest unexamined assumption** in the cart lane going live, and what would you
   test that §8 misses?
