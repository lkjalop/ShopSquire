# ShopSquire — Exact GPT-5.6 Assessment Brief (2026-07-14, supersedes REVIEW11 packet)

Five asks, each with exact file:line targets. Commits to review: `1d75c4e`→`8106056` (13 commits).
Legacy `recommend.py::suggest()` ships live; V2 `recommendation_core/` runs in shadow.

---

## PART A — Adversarial code review (verify these are correct, not just plausible)

### A1 · Money-path concurrency + idempotency middleware — HIGHEST severity
Files: `src/app/routers/payments.py`, `routers/orders.py`, `services/inventory_guard.py`,
`services/refund_requests.py`, `services/payment_ledger.py`, `security/idempotency.py`.
`SELECT..FOR UPDATE` appears nowhere; the lock primitive is `INSERT..ON CONFLICT DO NOTHING` +
conditional `UPDATE..WHERE status=:expected`. **Attack each:**
- `orders.py:445/474/508` cancel/return/update_status — `AND status=:expected` CAS + 503+rollback on
  commit-fail; inventory released *inside* the commit txn. Probe: concurrent cancel+mark-paid from
  `created` — can both win? Does 503-vs-409-vs-404 misclassify?
- `inventory_guard.py:106` `release_inventory_for_order` — CAS-claims the reservation before
  crediting stock; DB failures now PROPAGATE (were swallowed). Probe: two concurrent releases +
  reserve racing release → stock never inflated?
- `payments.py:148` create_intent (idempotency key now REQUIRED, 400 if absent) + `:261/:288`
  checkout (`checkout_attempt_id` or header REQUIRED; no time/price key material). Probe: any
  double-charge path left when a client omits the key?
- `refund_requests.py:59` refundable = `captured − max(approved, settled)` + `payment_ledger.py`
  `reserve_refund_slot` single-winner lock. Probe: two open requests → two approvals at different
  indices → **still a double refund?** (both the balance guard AND the slot lock must hold.)
- `security/idempotency.py` middleware (rewritten `7c835f2`): money-scoped 503
  (`_CRITICAL_PREFIXES`), never-release-after-a-completed-side-effect, bounded cache. Probe: the two
  "side-effect done, response unrecorded" edges — is re-execute truly impossible, and is the
  cross-process 409-in-progress bounded (no permanent stuck)? Is streaming-response buffering
  (line ~137) a problem for any keyed endpoint? Is money-scoping (`/api/v1/payments|orders|refunds|
  checkout|fulfillment`) complete — any money route outside those prefixes?
- `fulfillment_cases.py:959` budget-commitment TOCTOU is **documented, NOT fixed** (flag-off). Ask:
  acceptable, or must it get a category lock before the gate ships?

### A2 · Retrieval-scope fix (`440fc78`, `core.py` `_exec_retrieve`)
A capability query routing to `el-6-6` (Laptops) now augments candidates with the device host UNION
(`_capability_scope_nodes` → +`el-6-11-2` Gaming Laptops). Verify: (a) it does NOT over-retrieve for
non-host/accessory queries (guarded by `_is_workload_host_product` + `decision.requirements`);
(b) budget stays applied (real envelope, not the free floor env); (c) no double-count / relevance-
order corruption when merging sibling variants; (d) the broad-retry fallback still fires only on a
true empty.

### A3 · Cart-ambiguity gate (`8106056`, `cart_resolver.py`)
The shopper-ambiguity gate asks-not-guesses when the query matches multiple cart lines without a
distinctive token. Verify: (a) no FALSE asks on a single-line cart or a uniquely-named brand;
(b) `q_tokens` distinctiveness is computed correctly (document-frequency); (c) relative quantities
("add 5 more") still resolve via model arithmetic; (d) the `keep_only` misclassification ("make the
Lenovo 15" → dropped the number) — is a deterministic "clear number + one target → set_quantity"
guard warranted (#2b), or is it acceptable model variance?

### A4 · Fail-closed + config + injection (`4c012c2`, `f10faf5`, `e2bef61`)
6 fail-closed flips, DPA enforcement, injection-marker unification. Probe for OVER-blocking: ABAC
malformed-allowlist deny (`auth.py:261`) locking out a fat-fingered config; `events.py:46`
DB-error→5xx retry storm; DPA `check_transfer` requiring declared `data_categories` (undeclared-PII
bypass); the unified injection regex (`security/injection_patterns.py`) — attack strings that slip
all 3 surfaces, or false positives on real shopping queries.

---

## PART B — Known-unfixed items to ASSESS (from the 6-auditor deep dive, still open)

- **Silent hangs (SSE, connection-leak class):** `routers/escalation_room.py:879` (+913, +1848),
  `routers/decisions.py:934`, `routers/decision_trace_events.py:260` — `await q.get()` inside
  `while True` with NO timeout → coroutine parks forever on client disconnect. Also
  `services/async_safe.py:25`, `services/orchestrator.py:24` — `pool.submit(asyncio.run,…).result()`
  no timeout. Verify still present; recommend `asyncio.wait_for(..., heartbeat)`.
- **Middleware streaming buffer** (P2, left): `security/idempotency.py` drains `body_iterator` into
  memory for any keyed request.
- **Tech debt / regression risk:** `recommend.py` = 12,312-line LIVE monolith; 11 files >2k lines
  (`admin.py` 4169, `support_complaints.py` 3990, `orchestrator.py` 3958, …); the **parity oracle is
  DISABLED** (`tests/test_recommend.py` xfail L143/L519, engine-aliasing) — must re-enable before any
  legacy delete; 37 legacy-only `recommend_*` shim services.
- **Inventory reservation leak:** failed-payment webhook marks order failed but never releases the
  reservation; no TTL sweep → phantom stockout (`payments.py` webhook + `inventory_guard`).

---

## PART C — What EXACTLY is stopping production grade

**Two independent tracks — don't conflate:**

**(1) Real store (money/safety) — essentially closed, needs CI proof:**
- Run the **full-repo pytest in CI with Postgres** (the money-race chaos suite now gates via
  `TEST_POSTGRES_URL` — commit `f68cb43`). Local run times out on model-backed tests; CI is the gate.
- The A1 adversarial review must find no CONFIRMED money defect.
- Optional-before-real-money: budget-gate category lock (A1 last bullet), inventory-reservation TTL.

**(2) V2 promotion — blocked on ONE thing: labels.**
- `recommendation_core/quality.py`: gate = `ndcg_at_10_min=0.60`, `labeled_coverage_min=0.30`.
  **`relevance_labels.json` is EMPTY → labeled_coverage=0 → the gate honestly FAILS.** NDCG/precision
  are *uncomputable* without labels. Intrinsic metrics are green (0 unauthorized, 0 empty-expected,
  ~80% constraint-sat, 3/3 known-wrongs) — but promotion cannot proceed on intrinsics alone.

**(3) Archive `recommend.py` (later) — blocked on:** non-canary lanes (cart/procurement/support/
policy/inventory/image) fall through to legacy → extract or shim first; parity oracle disabled;
chat→HTTP loopback hop (`chat.py:1855`).

---

## PART D — The LABELING task for GPT-5.6 (exact — this UNBLOCKS track 2)

**GPT-5.6 is a VALID independent judge:** the "never let the model judge itself" rule (README) is
about the *evaluated* model (qwen3:14b, the router). GPT-5.6 is a different model → it can grade the
slate. Best practice: GPT-5.6 as one annotator, a human as the second for the **test** split.

**Exact task:**
1. **Corpus:** `tests/golden/suggest_corpus/` — every recorded corpus turn, keyed `<case_id>:<turn>`
   (e.g. `budget_band:0`, `explain_followup:1`). The stateful replay measures each TURN; a follow-up
   turn's relevant set differs from turn 0's.
2. For each case: run the query against the **demo catalog** and grade the **CANDIDATE SLATE** (the
   retrievable set for that query — NOT only what V2 showed; an unlabeled shown SKU counts as NOT
   relevant). Grades: **2 = highly relevant, 1 = acceptable, 0 = explicitly irrelevant.**
3. Write into `tests/golden/relevance_labels.json` in the schema the loader ACTUALLY reads
   (`quality.py:58` reads `entry.get("labels")` — CORRECTED, my earlier `{case:turn:{sku:grade}}` was
   wrong): `"cases": {"<case_id>:<turn>": {"labels": {"<SKU>": <grade>, …}}, …}`, set `"labeled_by"`,
   populate `"split": {"dev": [...keys...], "test": [...keys...]}`. **PREREQUISITE (GPT-5.6):** the
   evaluator currently AGGREGATES all labeled rows (`quality.py:232`) and does NOT enforce the
   dev/test split — fix the loader to honor an explicit `dev`|sealed-`test` split BEFORE mass
   labeling, and store catalog-snapshot hash + taxonomy version + annotators for reproducibility.
   **Discipline:** never train on the test split; GPT-5.6 may produce dev/weak labels, but the sealed
   test labels require human review.
4. **Target:** `labeled_coverage ≥ 0.30` to open the gate; higher is better. Grade honestly — the
   gate is designed to FAIL until real labels exist, so partial/low-effort labels just move the
   failure, they don't unblock promotion.
5. Human second-pass on the **test** split before it gates a canary flip (inter-annotator agreement).

---

## PART E — Next steps, ordered (why this order)
1. **GPT-5.6: PART A adversarial review** — money code is the highest blast radius; scrutinize before
   more is built on it.
2. **GPT-5.6: PART D relevance labeling** — the single promotion blocker; GPT-5.6 unblocks it now
   (human second-pass later).
3. **Share the shadow-replay OUTPUT** (the diagnosed rows / `tmp/quality_diagnosis.json`) so the 6
   gate divergences can be adjudicated — currently blocked, not in the repo.
4. **CI: full-repo pytest green with Postgres** (track-1 proof).
5. Then: #2b cart guard (optional), Phase-2 archive prereqs (extract non-canary lanes, re-enable the
   parity oracle, kill the loopback hop), canary ladder.

**State:** ~13 hardening/fix commits this arc, ~140 tests + ~35 new regression tests green.
Real-store money/safety: closed pending CI + A1 review. V2 promotion: one gate (labels).
