# ShopSquire — Production-Readiness Deep Dive (2026-07-13)

**Method:** 6 parallel file:line-verified auditors over `src/app/` — fail-open/silent-swallow,
silent-hang/timeout, dedup/decision-drift, wiring/reachability, tech-debt/regression,
concurrency/data-integrity. Every finding below was confirmed by reading the actual line(s).

**One-paragraph verdict.** The previously-flagged *Track A* fail-open cluster (payment ledger,
fraud phash, ABAC reauth) is **remediated and now fails CLOSED** — confirmed independently by two
auditors. The V2 recommendation core is green (~430 tests) and honest by construction. But the
audit surfaced a **different, larger set of production blockers than the recommend-engine roadmap
tracked**: (1) a **concurrency/idempotency gap on the money paths** that can double-execute orders,
charges, and refunds; (2) a **canary-divergence risk** from ~11 duplicated decision surfaces
(legacy regex vs V2 model-judged); and (3) **production-config gaps** — the bitemporal-audit
differentiator is silently OFF in prod, and a data-residency compliance gate ships open. "Full
production grade" for the *real store* is ~1 focused week of P0 correctness work + config, and is
**separate** from the recommend-V2 canary calendar.

---

## GOOD NEWS — no longer blockers (verified)

- **Track A remediated (fail-CLOSED):** `services/payment_ledger.py:94` now `raise`s on write
  failure; `routers/fraud.py:99` degrades-to-review + clamps confidence on phash DB error;
  `security/auth.py` ABAC has explicit `return False` denies; Stripe webhook HMAC (`payments.py:412`),
  SSRF egress allowlist, ACL engine, autonomous-send, supplier-domain guard all fail closed.
  **The memory's "Track A URGENT" entry is now stale — update it.**
- **Timeouts are unusually disciplined:** dedicated `redis_factory` (0.5s connect / 2s op),
  env-tunable bounds, explicit "never brpop(0)" guards, bounded model/embedding/CV calls. Only two
  real gaps (below).
- **The atomic pattern exists in-repo:** inventory *reserve* uses correct CAS
  (`inventory_guard.py:96` `UPDATE … WHERE id AND stock>=:qty`, rowcount check); supplier send is
  `UNIQUE(tenant,key)` + atomic claim (`outbound_queue.py:98`). The fixes below are **propagating a
  known-good pattern**, not inventing one.
- **Routing wired:** 109/111 routers correctly `include_router`ed (the 2 exceptions below).
- **Migrations:** alembic chain is linear, single root — no multi-head drift.
- **V2 core:** 430 unit tests green, re-soak 39/40 (zero poison classes), never-empty-message
  invariant, decide-phase instrumented.

---

## P0 — MUST fix before real money / real traffic

### P0-1 · Concurrency & idempotency on money paths (7 confirmed races)
The single biggest gap. `SELECT … FOR UPDATE` appears **nowhere** in the codebase; several money
paths are check-then-act.

| # | file:line | issue | concurrent → wrong outcome |
|---|-----------|-------|----------------------------|
| a | `security/idempotency.py:57-99` | App-wide `IdempotencyMiddleware` is SELECT→process→INSERT with no atomic key reservation | Two POSTs same `Idempotency-Key` both miss SELECT → **both execute** → double side-effect. A *false* idempotency guarantee. |
| b | `routers/payments.py:277-293` | `checkout_initiate` creates the order (+reserves stock, +mints Stripe intent) **before** the idempotency check; with no client `Idempotency-Key` header each retry derives a fresh `co:{new_order_id}` key | Double-submit → **two orders + two PaymentIntents** → double reserve / double charge |
| c | `routers/orders.py:438,461,496` | State-machine UPDATEs (`cancel`/`return`/`update_status`) validate then `UPDATE … WHERE id` with **no `AND status=<expected>`** (TOCTOU) | Concurrent `cancel` + `mark paid` from `created` → **paid order silently cancelled** (or vice-versa). The webhook at `payments.py:443` does this correctly — these don't. |
| d | `routers/payments.py:148-191,42` | `create_intent` idempotency is opt-in (`_idempotent` returns True when key falsy); Stripe call passes no idempotency_key | `/intent` without the optional key → **two Stripe intents → double charge** |
| e | `services/inventory_guard.py:152-173` | `release_inventory_for_order` adds stock back with no `AND status='reserved'` guard | Two concurrent cancels → **stock added back twice → inventory inflated → oversell** |
| f | `services/refund_requests.py:51-65` + `routers/payments.py:551-564` | refund request/approve are check-then-act on the "one open request/approval" invariant | Concurrent double-approve → **two `refund_approved` rows** (demo/manual path has no provider key → double refund) |
| g | `routers/fulfillment_cases.py:961` | budget commitment TOCTOU (SUM other cases → check cap → grant) | Two operators, same category → **cumulative spend breaches cap**. Flag-gated + human-paced → lower reach. |

**Fix:** propagate the in-repo pattern — conditional `UPDATE … AND status=<expected>` (rowcount==1)
on the order state-machine + inventory release; atomic `INSERT … ON CONFLICT DO NOTHING` key
reservation *before* side effects in the middleware and checkout; pass Stripe `idempotency_key` on
every intent. **Effort: M (~2-3 days incl. concurrency tests).**

### P0-2 · Remaining fail-opens on secondary rails (7 confirmed)
Not the top money rails (those are fixed), but real:

| # | file:line | fail-open |
|---|-----------|-----------|
| a | `services/fulfillment/outbound_integrity.py:69` | **secret-DLP scan exception → `secret_hits=0` → gate returns `allow`** → a credential/API-key can egress to a supplier (worst of the set) |
| b | `security/idempotency.py:74` | idempotency DB lookup `except: pass` → reprocess (compounds P0-1a) |
| c | `security/auth.py:261` | malformed `ABAC_TENANT_ALLOWLIST_JSON` → `_abac_tenant_allow` returns True → cross-tenant allow |
| d | `security/compliance.py:60` | TLS-required payment gate wrapped in `try/except: pass` → plaintext proceeds if the 403 build throws |
| e | `services/outbound_email_monitor.py:97` | scan exception → `action="allow"` (observability blind spot) |
| f | `routers/events.py:46` | webhook `_idempotent` returns True on DB error → duplicate event processed |
| g | `services/fulfillment/budget_gate.py:54` | malformed spend coerced to 0 → budget under-counts |

**Fix:** flip each to fail-CLOSED (block/deny/raise) on the internal exception. Most are one-line.
**Effort: S-M (~1 day).**

### P0-3 · Postgres connect fail-slow (hot path)
`models/db.py:88` — `create_engine` sets `statement_timeout=30s` (query execution) but **no libpq
`connect_timeout`**. A down/wedged Postgres stalls the *connect* phase of every DB-touching request
(recommend reads `products`) until the OS TCP timeout (~20s+). **Fix:** add
`"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT_SEC","5"))` to `connect_args`. **Effort: S (5 min).**

---

## P1 — production configuration & compliance

### P1-1 · The audit differentiator is OFF in production
`config/feature_flags.json:25` ships `DECISION_LOG_WRITES_ENABLED:false`; `config.py:451`
force-flips it True **only when `APP_ENV` ≠ production**. So in a real prod deploy the bitemporal
decision-audit writes — the stated product differentiator — are **OFF** across `orchestrator.py:2600`,
`pricing.py:250`, `recommend.py:710`, and dev testing can never catch it. **Fix:** ship `true` or an
explicit prod env override. **Effort: S.**

### P1-2 · Data-residency compliance gate ships open
`policy/data_residency.py:118` — `signed_dpa=False  # TODO: execute DPA before prod PII`. PII
processing proceeds with the DPA unsigned. Process/legal gate, not code. **Effort: M (external).**

### P1-3 · Canary-divergence: reconcile the top duplicated decision surfaces
~11 duplicated decision surfaces (legacy regex vs V2 model-judged) will answer edge phrasings
differently — a user-visible risk *during the canary*. Reconcile the two that flip the most:
- **Off-catalog refusal (most likely flip):** legacy `off_catalog_gate.py:19` is a hand-authored
  regex **denylist**; V2 `taxonomy_registry.py:360` `sells_within` is a sold-set **allowlist** —
  opposite algorithms over different data. Same query flips "here are laptops" ↔ "we don't sell that".
- **Budget parsing (6 surfaces):** `budget_grammar.py:70` canonical + 5 legacy fallbacks
  (`nlp_search_agent`, `query_decomposer`, `chat.py:217`, `recommend_budget_parsing`,
  `recommendations`). Currently *masked* (all short-circuit to canonical) but one deleted call from
  resurrecting the negated-ceiling inversion ("nothing over $2k" → min) in four lanes.
- Also latent: 3 injection-guard regex lists (`commerce_request_guard` / `gates.py` /
  `product_claim_guard`) admit different attack strings; 4 quantity thresholds (25/500/1000/100k);
  3 use-case scorers with different deltas. **Effort: M-L; do the top 2 before canary.**

---

## P2 — structural / rollout (weeks, not days)

- **Dead / mis-wired code:** delete `services/semantic_turn_router.py` (superseded, imported by
  nothing); register or delete the 2 orphaned admin routers `case_cockpit.py` + `decision_time_travel.py`
  (currently 404); kill the `chat.py:1855` → `/api/v1/recommend/suggest` **loopback HTTP hop**
  (re-runs the whole middleware stack in-process).
- **Legacy→V2 cutover (the R11 arc):** `recommend.py` is a **12,312-line live monolith**; the V2
  replacement is gated off and only shadow-validated. The parity oracle meant to guard the flip is
  **disabled by test-harness engine-aliasing** (`test_recommend.py`) — re-enable it before deleting
  legacy. This cutover is itself the single biggest planned regression event.
- **9 subsystems built-but-dark** — decide ship/cut for each: V2 core (`RECOMMEND_CORE_MODE=off`),
  scatter-gather pipeline (`RECOMMEND_PIPELINE_V2=0`), canonical catalog read-model
  (`CATALOG_READ_MODEL=legacy`), market-intel (`HIPPOGRAPH_FEEDBACK_ENABLED=off`), external research
  (`EXTERNAL_RESEARCH_ENABLED=false`), LLM planner (`LLM_PLANNER_ENABLED=0`), visual search
  (`IMAGE_SIMILARITY_ENABLED=false`), decision-log writes (P1-1), shadow worker (never launched).
- **Giant-file cluster (11 files >2k lines):** admin.py (4,169), support_complaints.py (3,990),
  orchestrator.py (3,958), admin_email_security.py (3,244), merchant_dashboard.py (3,203),
  chat.py (2,910), email_security.py (2,771), decisions.py (2,595), main.py (2,443),
  recommendations.py (2,286) — review-blindspot / regression density.
- **Silent SSE hangs (connection leak, not event-loop block):** `escalation_room.py:879`,
  `decisions.py:934`, `decision_trace_events.py:260` do `await q.get()` in `while True` with no
  timeout → coroutine parks forever on client disconnect. Add `asyncio.wait_for(..., heartbeat)`.
- **Inventory reservation leak:** `payments.py` failed-payment webhook marks the order failed but
  never releases the reservation (`inventory_guard`), and there's no TTL sweep → phantom stockout.

---

## "What's needed for full production grade" — the gate

| Gate | Scope | Effort |
|------|-------|--------|
| **P0** money-path concurrency/idempotency (7 races) + 7 secondary fail-opens + db connect_timeout | real-store correctness/safety | **~1 focused week** |
| **P1** decision-log-in-prod + DPA + reconcile top-2 dedup surfaces | prod config + canary safety | ~2-3 days (+ legal) |
| **P2** dead-code cleanup, loopback-hop removal, legacy→V2 canary ladder, dark-flag decisions, file splits | rollout + maintainability | weeks (calendar-bound) |

**Bottom line.** Two tracks, don't conflate them. **(A) The real store** reaching production grade
is dominated by P0 (money concurrency + fail-open flips + one timeout) ≈ **one week of focused
correctness work**, most of it propagating patterns the codebase already implements correctly
elsewhere. **(B) The recommend-V2 rollout** is the canary ladder + monolith retirement, gated on
USER labels and soak-clock — weeks of calendar, little of it new code. The audit's surprise is that
the highest-severity work is now (A), not the recommend engine everyone's been building.
