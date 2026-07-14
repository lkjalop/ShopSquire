# ShopSquire — Comprehensive Test Plan + Roadmap (2026-07-14)

Consolidates where we are, **what still needs testing** (with the real gaps flagged), and a
**sequenced roadmap** from here to production-grade + the V2 cutover. Owner tags: **[ME]** = agent
can do it, **[USER]** = needs you (labels, judgment), **[CAL]** = calendar/soak-clock bound.

---

## 0. State snapshot

- **Test suite:** 849 files / 4,410 test functions. This session added ~20 regression tests; all
  targeted suites green.
- **V2 core:** built, soak-validated (39/40, zero poison classes), instrumented (99.9% of latency =
  the model call). Runs in **shadow** — serves 0% of live traffic.
- **Legacy `recommend.py` (12,312 ln) + `suggest()`:** what ships live. Retirement = R11, blocked
  (see §2 Phase 2).
- **Prod-hardening (this session, 10 commits):** all real-store blockers CLOSED — money-path
  concurrency (7 races), 6 fail-opens→closed, DB timeout, audit-log-in-prod, DPA enforcement,
  injection dedup, off-catalog gate, dead-code cleanup.
- **Track A** (auth/payment/fraud fail-open): confirmed REMEDIATED.
- **2026-07-14b increment (reviewed + verified green):** hardened the money P0s further — idempotency
  keys now REQUIRED (checkout_attempt_id, no time-window key), atomic order+inventory release (503 on
  commit-fail), refund balance guard (captured − max(approved,settled)), method+path-scoped
  fingerprinted idempotency middleware, **PG threaded concurrency tests** (the flagged gap), sold-
  taxonomy materialization, honest evaluator language. 4 P1 / 2 P2 review findings → Phase 1. Replay
  surfaced V2-core defects (ranking, narration arbitration, 6 divergences) → Phase 1.5.

---

## 1. WHAT NEEDS TO BE TESTED — the matrix

Legend: ✅ done · ◐ partial · ✗ missing (gap)

### 1A · Money-path concurrency — **the biggest test gap**
The 7 race fixes (`1d75c4e`) have **deterministic guard tests only** — no test drives *actual
concurrent load* at the same order/refund/checkout. A CAS that looks right can still race.

| What | State | Needed |
|---|---|---|
| Order-state CAS (cancel/return/update) | ◐ deterministic guard | ✗ **[ME]** N threads cancel+mark-paid the same order → exactly one wins, no paid→cancelled |
| Inventory release CAS | ◐ guard (double-release→single-credit) | ✗ **[ME]** N concurrent releases + reserve racing release → stock never inflated |
| Checkout idempotency | ◐ | ✗ **[ME]** N parallel `checkout_initiate` (same cart, no header) → 1 order, 1 intent; bucket-boundary probe |
| Refund request/approve slot-lock | ◐ | ✗ **[ME]** N parallel approves of 1 request → 1 approval; 2-requests→2-approvals chain closed |
| IdempotencyMiddleware | ◐ | ✗ **[ME]** N parallel same-key POSTs → 1 executes, rest replay/409; DB-down path |
| Stripe/Afterpay provider key | ✅ unit | — |

**Action:** one `tests/chaos/test_money_concurrency_load.py` using threads on a shared SQLite/PG,
asserting the invariant after each storm. Model this on `tests/chaos/test_backpressure_concurrency.py`.

### 1B · Fail-closed & security
| What | State | Needed |
|---|---|---|
| 6 fail-closed flips | ✅ 3 new regression tests | ◐ **[ME]** over-block probes: ABAC lockout UX, events→5xx retry-storm, TLS send-exception |
| Injection dedup (3 surfaces unified) | ✅ corpus green | ◐ **[ME/GPT]** expand adversarial corpus; confirm no surface narrowed |
| DPA enforcement | ✅ 4 tests | ◐ **[ME]** undeclared-PII bypass (caller omits data_categories) |
| Secret-scan→block | ✅ | — |

### 1C · Config / compliance
| What | State | Needed |
|---|---|---|
| Audit-log default-on in prod | ✅ | ◐ **[ME]** assert ON when `APP_ENV=production` + env unset (prod-sim test) |
| DPA gate | ✅ | **[USER]** actually sign the DPA → set `signed_dpa=True` (process, not code) |

### 1D · V2 core quality — **the promotion gap**
| What | State | Needed |
|---|---|---|
| Routing / lanes / extraction | ✅ soak 39/40 | — |
| Multi-turn stateful continuity | ✅ | — |
| Refusal / safety (off-catalog) | ✅ + gate | — |
| **Relevance labels** ("is the shown product good?") | ✗ **empty** (5 metadata keys, 0 labels) | **[USER]** grade a corpus (case_id:turn, 2 reviewers, candidate-pool grading). **This is the single blocker on promoting V2.** |
| Latency | ✅ measured (model-bound) | ◐ **[ME/USER]** pick a faster served router model → re-measure |

### 1E · Parity (legacy ≡ V2) — **archive gap**
| What | State | Needed |
|---|---|---|
| Contract/safety characterization | ◐ legacy endpoint characterization and V2 safety suites exist; labeled relevance is empty | ✗ **[ME+USER]** green V2 contract/safety, then add judged relevance; product-set parity remains diagnostic |
| Shadow differ | ◐ built, flag-off | ◐ **[ME]** wire refusal-verdict disagreement recording (off-catalog #1 reverse) |

### 1F · Integration / E2E / demo
| What | State | Needed |
|---|---|---|
| Checkout→paid→dispatch→shipped spine | ✅ | — |
| Procurement journey | ✅ 29 service tests | ◐ **[USER]** e2e playwright (needs browser) + bounded-autonomy demo |
| Hybrid demo (RECOMMEND_CORE_MODE=primary) | ◐ core→adapter proven | ✗ **[USER]** end-to-end through chat→/suggest + browser render of new fields |
| Off-catalog gate real-data loop | ✅ demo startup materializes approved nodes; deterministic cross-vertical guard runs without skipping | — |

### 1G · Load / performance
| What | State | Needed |
|---|---|---|
| Latency attribution | ✅ (route+intent = 99.9%) | — |
| Concurrent request load | ✗ (only chaos backpressure) | ✗ **[ME]** money-path load (1A) + a p95-under-load run |
| DB connect fail-slow | ✅ fixed (connect_timeout) | ◐ **[ME]** test: PG-down → fast fail not hang |

---

## 2. THE NEW ROADMAP — phased & gated

### Phase 0 — GPT-5.6 adversarial review *(now)* **[USER runs it]**
Packet: `docs/SHOPSQUIRE_V2_REVIEW11_PACKET_2026-07-14.md`. Gate: GPT-5.6's findings triaged; any
CONFIRMED money-path or fail-closed defect fixed before Phase 1. **~0.5 day to triage.**

### Phase 1 — Close the remaining prod-grade gaps **[ME]** *(~2 days)*
*(2026-07-14b increment did most of this: PG threaded races ✅, required idempotency keys ✅,
atomic order/inventory + 503 ✅, refund balance guard ✅, sold-taxonomy materialization ✅.)*
Remaining:
1. **Idempotency-middleware hardening** (NEW — from the increment review): (a) scope the
   store-unavailable **503 to money paths** vs. blocking *all* idempotent writes; (b) resolve the
   two "side-effect done, response unrecorded" edges — capture-fail→release→**re-execute** and
   commit-fail→**stuck 409-in-progress** (no TTL cleanup); (c) bound `self.cache` (LRU); (d) don't
   buffer streaming responses. → `idempotency.py`.
2. **CI must provision Postgres** so `test_money_concurrency_postgres.py` actually gates (it skips
   without `TEST_POSTGRES_URL` — the money-race fixes have no automated coverage otherwise).
3. **Full-repo pytest run** — the middleware touches every idempotent write; ~72 more green post-
   increment but not the 4,410.
4. Fail-closed **over-block probes** (§1B) + budget-commitment **category lock** (P0-1g) + DB-down
   **fast-fail test** (§1G).
**Gate:** real-store prod-grade — every money/safety fix proven under load AND the middleware edges
closed. This is the true "production grade for the real store" line.

### Phase 1.5 — V2 CORE quality defects (NEW, from the 2026-07-14b replay) **[ME]** *(~2-3 days)*
The increment's shadow replay surfaced real V2-core defects that gate promotion independent of labels:
1. **Requirement-ranking failures** — 24 `gpu_vram_gb` + 12 RAM mis-rankings. Retrieval/fit ordering
   bug at `recommendation_core/ranking.py` + `core.py`. **This is a V2 correctness defect, elevate it.**
2. **Mutation/search narration arbitration** — "make the laptop 15" reads partly as a 15-inch search
   while the cart planner correctly sets qty 15. Route validated cart ops exclusively through the cart
   lane (`chat.py`, `recommendation_facade.py`); suppress unrelated search narration.
3. **Adjudicate the 6 BLOCKER divergences** (accessory / compare / explain-followup / off-domain /
   off-catalog) — classify each: V2 defect | legacy known-wrong | expected contract change.
4. **Harden the evaluator** — per-case progress, model deadlines, timeout/error rows (the replay
   *looked* hung at 280s). `shadow_replay.py`.
**Gate:** zero unexplained V2-core ranking/gate failures; every divergence adjudicated.

### Phase 2 — Archive prerequisites for recommend.py **[ME]** *(~1 week)*
The blockers to deleting the 12,312-line legacy engine (none are "just flip the canary"):
1. **Extract non-canary lanes** (cart / support / policy / inventory / image) from recommend.py into
   standalone routers that outlive it. **Decide:** PROCUREMENT stays a thin legacy shim (advise-only
   V2 + mature RFQ) vs. built into V2.
2. **Complete the contract/safety characterization** (§1E); green the five canary lanes without requiring product-set identity with legacy.
3. **Kill the chat→HTTP loopback hop** → direct facade call.
**Gate:** recommend.py has no unique responsibility left except the 5 canary lanes; parity green.

### Phase 3 — V2 quality gate **[USER + ME]** *(USER-bound)*
1. **[USER]** Relevance labels (§1D) — the promotion blocker.
2. **[ME]** Freeze the contract on the typed StageResult shapes.
3. **[ME]** Minimal UI: render the capability banner + bulk menu first (the wow moments), then shelf.
4. **[USER]** Screenshot battery + hybrid demo end-to-end (§1F).
**Gate:** V2 measurably ≥ legacy on labeled relevance for the 5 lanes.

### Phase 4 — Canary ladder **[CAL]** *(~1-2 weeks wall-clock)*
`RECOMMEND_CORE_MODE`: shadow → canary:1 → 5 → 25 → 50 → primary(100). Per-lane auto-rollback on a
regression in: refusal-rate, empty-rate, p95 latency, label-quality, error-rate. Soak window at each
rung. **Gate:** 100% for a full soak window, zero regressions.

### Phase 5 — Retire the legacy engine **[ME]** *(~1 day, a dated delete)*
Delete recommend.py, suggest(), the loopback hop, and the 37 legacy-only `recommend_*` shims (find
non-legacy consumers first). Re-run the full suite. **Never "fixed" — a scheduled delete.**

### Cross-cutting (parallelizable)
- **Track A hardening** already done; keep the fail-closed regression tests in CI.
- **Off-catalog #1 reverse** — measured via the shadow differ in Phase 2/4, not a pre-fix.
- **Giant-file splits** (11 files >2k ln) — opportunistic, not gating.
- **Faster router model** — swap to cut the model-bound latency for the demo/prod (§1D).

---

## 3. Immediate next 3 actions (my recommendation, post-increment)
1. **[ME]** **Idempotency-middleware hardening** (Phase 1 #1) — the two side-effect/response edges +
   money-scoped 503 are the only P1 correctness gaps the increment introduced; close them + a
   targeted middleware test.
2. **[ME/USER]** **Wire Postgres into CI** so the money-race tests gate (Phase 1 #2) + run the
   **full-repo pytest** once (Phase 1 #3) — the middleware's reach warrants it.
3. **[ME]** **Requirement-ranking defect** (Phase 1.5 #1) — the 24 gpu_vram + 12 RAM replay failures
   are a real V2-core correctness bug and the most concrete promotion blocker after labels.
Then **[USER]** the GPT-5.6 review + relevance labels remain the two you-owned gates.

**One-line status:** prod-money correctness is closed and committed; the roadmap from here is
*prove-under-load → extract lanes + parity → USER labels + UI → canary → delete legacy* — most of the
calendar is your labels and the soak clock, not new code.
