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
| 95-test parity oracle | ✗ **disabled** (`test_recommend.py` xfail L143/L519, engine-aliasing) | ✗ **[ME]** re-enable, get legacy≡V2 green on the 5 canary lanes |
| Shadow differ | ◐ built, flag-off | ◐ **[ME]** wire refusal-verdict disagreement recording (off-catalog #1 reverse) |

### 1F · Integration / E2E / demo
| What | State | Needed |
|---|---|---|
| Checkout→paid→dispatch→shipped spine | ✅ | — |
| Procurement journey | ✅ 29 service tests | ◐ **[USER]** e2e playwright (needs browser) + bounded-autonomy demo |
| Hybrid demo (RECOMMEND_CORE_MODE=primary) | ◐ core→adapter proven | ✗ **[USER]** end-to-end through chat→/suggest + browser render of new fields |
| Off-catalog gate real-data loop | ◐ skips (aa-*/el-* namespace mismatch) | ✗ **[ME]** reconcile sold-set namespace so the loop runs |

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

### Phase 1 — Close the remaining prod-grade gaps **[ME]** *(~2-3 days)*
1. Money-path **concurrent-load tests** (§1A) — validate the 7 fixes under real threads.
2. Fail-closed **over-block probes** (§1B).
3. Budget-commitment **category lock** (P0-1g — the one documented, not fixed).
4. DB-down **fast-fail test** (§1G).
**Gate:** real-store prod-grade — every money/safety fix proven under load. This is the true
"production grade for the real store" line.

### Phase 2 — Archive prerequisites for recommend.py **[ME]** *(~1 week)*
The blockers to deleting the 12,312-line legacy engine (none are "just flip the canary"):
1. **Extract non-canary lanes** (cart / support / policy / inventory / image) from recommend.py into
   standalone routers that outlive it. **Decide:** PROCUREMENT stays a thin legacy shim (advise-only
   V2 + mature RFQ) vs. built into V2.
2. **Re-enable the parity oracle** (§1E); green legacy≡V2 on the 5 canary lanes.
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

## 3. Immediate next 3 actions (my recommendation)
1. **[USER]** Run the GPT-5.6 review (Phase 0) — get adversarial eyes on the money fixes before more is built on them.
2. **[ME]** Phase 1 #1 — the money-path concurrent-load tests (the biggest test gap; proves the fixes hold under real races).
3. **[ME]** Reconcile the `aa-*`/`el-*` sold-set namespace so the off-catalog gate's real-data loop runs (small, unblocks a skip) + re-enable the parity oracle (Phase 2 #2 — highest-leverage archive prerequisite).

**One-line status:** prod-money correctness is closed and committed; the roadmap from here is
*prove-under-load → extract lanes + parity → USER labels + UI → canary → delete legacy* — most of the
calendar is your labels and the soak clock, not new code.
