# V2 — Next Roadmap: file:line build spec (2026-07-12, HEAD 6ad857e)

What's LEFT after review-6, in dependency order, each item with **WIRE** (exact edit points) and
**TEST** (what proves it). Anchors verified against HEAD. Flags stay off; search core stays legacy
until P1 measurement + labels exist.

Legend: ✅ done · ⬜ left. All P0 gate any canary or unsupervised `RECOMMEND_CART_SERVE=on`.

---

## P0 — safety + the promotion gate (before ANY canary / unsupervised cart-on)

### P0.1 ✅ Quality gate requires measurement (done, `7936c97`)
`recommend_parity_full.summarize_run` now splits `diagnostic_pass` vs `gates_pass` (needs
`quality_evaluated`). Nothing more here.

### P0.2 ⬜ One-transaction cart mutation + versioned CAS (review-6 #2/#3/#4) — the big one
**Goal:** plan-claim, cart-read, cart-write, plan-complete all commit atomically; a concurrent
stepper/second-plan can't lose-write; a crash can't wedge or mutate-then-lie across connections.

- **SCHEMA:** [db/schema.sql:33-40](db/schema.sql#L33-L40) `draft_orders` — add `version INTEGER NOT NULL DEFAULT 0`.
  Also add it to the in-code DDL path used by tests ([models/db.py](src/app/models/db.py) `_ensure_minimal_sqlite_tables`).
- **CART INTERNALS (accept an injected session):** [cart.py:76](src/app/routers/cart.py#L76) `_get_or_create_cart`,
  [cart.py:95](src/app/routers/cart.py#L95) `_save_cart` — add an optional `db=None` param; when
  passed, use it instead of opening a new `db_session()` ([models/db.py:1046](src/app/models/db.py#L1046)).
  `_save_cart` becomes a **versioned CAS**: `UPDATE draft_orders SET line_items=:i, version=version+1,
  updated_at=CURRENT_TIMESTAMP WHERE id=:id AND version=:expected` → return `rowcount`; 0 = stale.
- **SERVICE (one transaction):** [cart_mutation_service.apply_plan](src/app/services/cart_mutation_service.py#L150)
  — open ONE `with db_session() as db:` spanning the status CAS ([:181](src/app/services/cart_mutation_service.py#L181)),
  the read, `apply_quantity_line`, the versioned `_save_cart(db, …, expected_version)`, and
  `_finish(db, …)` ([:135](src/app/services/cart_mutation_service.py#L135) — also take `db`). On
  Postgres, `SELECT … FOR UPDATE` the cart row after the status claim; on SQLite, the connection's
  `BEGIN IMMEDIATE` + the version CAS is the guard. The pre-write re-read ([:283-289](src/app/services/cart_mutation_service.py#L283))
  becomes the CAS `expected_version` (delete the hash re-check once versioned). `propose_plan`
  ([:70](src/app/services/cart_mutation_service.py#L70)) stores `cart_version` alongside `cart_hash`.
- **UNDO after commit (#4):** move `_stash_undo` ([:262](src/app/services/cart_mutation_service.py#L262))
  to AFTER the versioned save returns rowcount==1 — never stash for a save that didn't happen.
- **TEST** (`tests/test_cart_mutation_service.py`): (a) version bumps on apply; (b) two `apply_plan`
  on the same cart where a stepper `set_item_quantity` lands between propose and apply → the plan
  returns `stale_cart`, the stepper's edit survives (the lost-write case, currently only mitigated);
  (c) simulate a mid-transaction raise → cart unchanged AND plan not stuck `applying` (one txn rolls
  back atomically); (d) undo key absent when the save was a no-op/stale.

### P0.3 ⬜ Tenant / principal ownership (review-6 #5)
**Goal:** tenant comes from the authenticated request, not the client body; cart identity is
`(tenant_id, uid)`; a caller can't apply against another tenant's plan/cart.

- **ENDPOINT:** [cart_mutations.py:21-29](src/app/routers/cart_mutations.py#L21) — remove
  `tenant_id` from `ApplyPayload`; derive it from the auth/session context the router already has
  (same source `require_role` uses). Same for `get_mutation` ([:41](src/app/routers/cart_mutations.py#L41)).
- **FRONTEND:** [api.ts `applyCartMutation`](frontend/src/lib/api.ts) — drop the hardcoded
  `tenantId='default'`; the backend derives it. (Prevents the "plan under non-default tenant is
  rejected because the client always sends default" break.)
- **CART IDENTITY (bigger, platform):** [cart.py `_get_or_create_cart`:76](src/app/routers/cart.py#L76)
  keys on `customer_id` only — the tenant-scoped `(tenant_id, uid)` cart is scheduled platform debt;
  for now, the plan artifact is already tenant-keyed, so the endpoint/derivation fix closes the
  client-controlled-tenant hole. Document the residual.
- **TEST** (`tests/test_cart_mutations_endpoint.py`): a plan proposed under tenant A cannot be
  applied by a request authenticated as tenant B (403); the body can no longer set tenant.

### P0.4 ⬜ Plan-table migration (review-6 #6)
**Goal:** stop runtime `CREATE TABLE IF NOT EXISTS` ([cart_mutation_service.py:49](src/app/services/cart_mutation_service.py#L49))
being the only definition.
- **WIRE:** new `alembic/versions/20260713_cart_mutation_plans.py` (pattern:
  [alembic/versions/20260711_taxonomy_grounding.py](alembic/versions/20260711_taxonomy_grounding.py)).
  Table + indexes `(tenant_id, uid, status)`, `expires_at`, `trace_id`. Add a cleanup job that
  deletes `status IN ('applied','stale_cart','expired','error')` older than N days; redact/expire
  the stored `query` per retention. Keep `_ensure_plans_table` for the sqlite test path only.
- **TEST:** `tests/test_cart_mutation_plans_migration.py` (pattern
  [tests/test_taxonomy_*_migration.py]) — the migration file parses + creates the table + indexes.

### P0.5 ⬜ SSE idle/total deadline + shared idempotency (review-6 #11)
**Goal:** the stream can't hang forever; a slow first turn can't double-*resolve*.
- **WIRE:** [App.tsx `tryStreamChat` ~1610](frontend/src/App.tsx#L1610) — the `setTimeout(()=>ctl.abort(),3500)`
  is cleared in the `finally` right after `fetch()` resolves (headers arrive on the instant
  `thinking` event), so the `while(true){ reader.read() }` loop below has NO deadline. Add: (1) a
  per-read idle timeout (race `reader.read()` against a timer, abort on idle); (2) a total-turn
  deadline; (3) heartbeat handling if the server emits keepalives. Generate ONE idempotency key per
  send and pass it to BOTH `/chat/stream` and the `/chat/query` fallback (header), so the fallback
  can't run a second *resolve/serve* while the first is in flight.
- **BACKEND:** `chat_stream` / `chat_query` read the idempotency key; the cart path already has
  apply-side idempotency (the plan CAS) — extend a short-TTL resolve-side guard keyed on it.
- **TEST:** frontend vitest (idle abort fires; total deadline fires); backend — two requests with
  the same idempotency key don't double-serve.

---

## P1 — make the measurement REAL (so V2 can be PROVEN before canary)

### P1.1 ⬜ Serialize the full typed envelope into shadow jobs (review-6 #7)
**Goal:** the shadow diff sees the SAME input serving does.
- **WIRE:** [facade `_enqueue_shadow`:90](src/app/services/recommendation_facade.py#L90) — the job
  is `{query, uid, tenant_id, trace_id[, cart]}`; it DROPS budget/session/image/role/qty. Serialize
  `envelope.to_dict()` (add a `TurnEnvelope.to_dict()`/`from_dict()` to
  [envelope.py](src/app/services/recommendation_core/envelope.py)) with a `schema_version`. The
  worker ([worker:103](src/app/workers/recommendation_shadow_worker.py#L103)) rebuilds via
  `TurnEnvelope.from_dict(job["envelope"])` instead of `from_suggest_params(query, uid, tenant)`.
- **TEST:** `tests/services/test_recommendation_shadow_worker.py` — a job carrying budget+session
  rebuilds an envelope with those fields; round-trip `to_dict/from_dict` equality.

### P1.2 ⬜ Richer redacted V1 projection + CALL quality.py in the worker/replay (review-6 #8/#9) — THE headline
**Goal:** quality.py stops being test-only; the census stops printing `quality: null`.
- **WIRE (V1 baseline):** [worker `_v1_products_from_trace`:30](src/app/workers/recommendation_shadow_worker.py#L30)
  reconstructs SKU/name only and fabricates `assistant_message:"v1"` ([:119](src/app/workers/recommendation_shadow_worker.py#L119)).
  Persist a redacted full served-response projection at serve time (message_class, clarify, panel,
  gates, fit) into the decision trace, and load THAT here — OR explicitly relabel this worker as
  product-membership diagnostics (not full A/B).
- **WIRE (quality):** [worker `process_job`:88](src/app/workers/recommendation_shadow_worker.py#L88)
  — after building `v2 = to_legacy(core)`, call
  `quality.evaluate_case_quality(case_meta, v2, labels)` and accumulate; the drain `run()` aggregates
  `quality.summarize_quality(rows)`. In offline replay ([shadow_replay.py:68](tests/characterization/shadow_replay.py#L68))
  compute NDCG/precision where case IDs + labels exist, and pass `quality=` into
  `recommend_parity_full.summarize_run` so `gates_pass` is real.
- **TEST:** worker test asserts a `quality` block in the run stats; replay `--facade-mode` +
  labels yields a non-null quality and a `gates_pass` that flips with the labeled set.

### P1.3 ⬜ Stateful multi-turn replay + consume prior_shortlist (review-6 #10/#17)
**Goal:** M3-C2 session behavior appears in the A/B evidence; "the first one" becomes operational.
- **WIRE (replay):** [shadow_replay.py:68-70](tests/characterization/shadow_replay.py#L68) — it
  builds a FRESH envelope per turn (declared stateless). Add a `--stateful` mode that, after each
  turn, extracts `{prior_node, shortlist_skus, constraints, ts}` from the response and injects it as
  `session=` on the next turn's envelope (mirror
  [postflight.write_session](src/app/services/recommendation_postflight.py#L42) → facade
  `_read_session_slice`).
- **WIRE (consume):** add a referent stage that reads `decision.prior_shortlist`
  ([turn_router.py:237](src/app/services/recommendation_core/turn_router.py#L237)) — for a
  COMPARE/EXPLAIN turn, map "the first/second/last one" onto those SKUs and seed retrieval/answer.
- **TEST:** a 2-turn replay case — turn 1 shortlists; turn 2 "why is the first one better" resolves
  to turn-1 SKU 0; turn 2 "only the 16GB ones" inherits turn-1 node (already unit-tested, now proven
  in replay).

---

## P2 — smarter model, then cut over

### P2.1 ⬜ Store-profile capability host nodes for reroute (review-6 #15)
**Goal:** a workload reroute can't land on an accessory category.
- **WIRE:** replace [taxonomy_registry.primary_sold_node:378](src/app/services/taxonomy_registry.py#L378)
  as the reroute target ([turn_router.py:~300](src/app/services/recommendation_core/turn_router.py#L300))
  with a store-profile slot: `profile_slot("capability_host_nodes")`
  ([store_profile.py:117](src/app/platform/store_profile.py#L117)) → `{run_on: [<node handles>]}`.
  The model picks the relationship; deterministic policy picks a device only from the allowed hosts
  (fall back to `primary_sold_node` when the slot is absent — vertical-blind default).
- **TEST:** brain test — a merchant profile whose most-classified node is an accessory still reroutes
  "play valorant" to a declared host laptop node, not the accessory.

### P2.2 ⬜ Continuation evidence for session inheritance (review-6 #16)
**Goal:** don't inherit prior context on a MIS-classified fresh turn.
- **WIRE:** [turn_router.py:223-233](src/app/services/recommendation_core/turn_router.py#L223) —
  add `refers_to_prior: bool` + confidence to the model's bounded output; inherit only when
  `refers_to_prior` AND session age is fresh, not on lane alone. Prompt gains one line; clamp it.
- **TEST:** a fresh SEARCH mis-tagged FILTER with `refers_to_prior=false` does NOT inherit; a true
  continuation does.

### P2.3 ⬜ Wire `preferred` into ranking (review-6 #20)
- **WIRE:** ranking stage ([ranking.py](src/app/services/recommendation_core/ranking.py)) reads
  `constraint.preferred` (from `core.extras.intent.constraints`) as a soft nearness boost, clamped
  into `[lower, upper]`. Update the [constraints.py](src/app/services/recommendation_core/constraints.py)
  comment once true.
- **TEST:** two in-range products, one nearer `preferred` → ranked first; out-of-range unaffected.

### P2.4 ⬜ Seal relevance labels + rerun A/B (human + replay)
- Fill [tests/golden/relevance_labels.json](tests/golden/relevance_labels.json) (dev/test split);
  rerun `shadow_replay --facade-mode --stateful` with quality → the FIRST real `gates_pass`.

### P2.5 ⬜ chat.py thin-edge (review-6 #12) — the left/right rearchitecture
**Goal:** kill the double intent-classifier + the internal HTTP hop + the per-carted-turn extra
resolver call.
- **WIRE:** [chat.py `_classify_turn_intent`:303](src/app/routers/chat.py#L303) DELETED; the internal
  GET `/recommend/suggest` hop ([chat.py:~1747](src/app/routers/chat.py#L1747)) becomes an in-process
  call to `dispatch_recommendation_core`; `turn_router` becomes the single intent authority and
  returns lane + cart proposal in ONE model call (fold `resolve_cart_mutation` into the router
  output so a carted search turn doesn't pay two model calls). `chat.py` shrinks to auth + image
  preprocessing + build ONE `TurnEnvelope`.
- **TEST:** integration — a cart turn and a search turn both resolve in one model call; no HTTP hop;
  `_classify_turn_intent` gone from the ratchet's flavour count.

### P2.6 ⬜ Cutover: canary:1 → ramp → primary → archive `suggest()`
Only after P0 + P1 gates pass and labels are sealed. `RECOMMEND_CORE_MODE=canary:1` on text lanes →
measured ramp → primary → `suggest()` → `recommend_legacy.py` frozen ≥4wk.

---

## Effort + sequence
| Block | Items | Effort | Gates |
|---|---|---|---|
| **P0** | txn CAS · tenant · migration · SSE | 3–4 sessions | unblocks unsupervised cart-on |
| **P1** | full envelope · quality-in-replay · stateful replay | 2–3 sessions | unblocks a REAL `gates_pass` |
| **P2** | host nodes · continuation · preferred · labels · thin-edge | 3–4 sessions | unblocks search canary |
| **cutover** | canary→primary→archive | calendar (weeks) | the finish line |

## Re-verify battery (run at each block exit)
Full `tests/services/` + `test_cart_*` + `test_constraints/test_quality` + both ratchets (~390) ·
frontend `tsc`+vitest · **P0 exit:** txn race/rollback tests + tenant-mismatch 403 · **P1 exit:**
worker emits quality; replay `gates_pass` flips with labels · **P2 exit:** reroute-to-host,
continuation-evidence, preferred-ranking; thin-edge one-call · **cutover:** live acceptance 3/3 at
each ramp step.
