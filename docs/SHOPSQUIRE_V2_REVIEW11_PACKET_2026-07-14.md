# ShopSquire — Review-11 Packet for GPT-5.6 (Prod-Hardening + Archive Plan, 2026-07-14)

Two asks for GPT-5.6:
1. **Adversarially review** the production-hardening arc (10 commits since the review-10 packet) —
   especially the money-path concurrency fixes, where a wrong CAS is a double-charge.
2. **Critique the plan to archive `recommend.py` / `suggest()`** — the 12,312-line legacy engine —
   and tell us what we're missing before we can delete it.

---

## PART 1 — What to review (commits `1476dc2`→`5950b80`)

### Context
- Legacy `recommend.py::suggest()` (`/api/v1/recommend/suggest`) is what **ships live**. The V2 core
  (`services/recommendation_core/`) runs in **shadow** (`RECOMMEND_CORE_MODE` unset → off). So every
  fix below is on the LIVE legacy/shared rails, not the dark V2 path.
- A 6-auditor deep dive (`docs/SHOPSQUIRE_PRODUCTION_READINESS_DEEPDIVE_2026-07-13.md`) found the
  previously-"URGENT" Track A fail-open cluster is REMEDIATED, but surfaced a new #1 blocker:
  money-path concurrency. This arc fixed it.

### The 7 things to adversarially verify (highest-severity first)

**A. Money-path concurrency — `1d75c4e` (verify each is actually race-safe, not just plausible).**
`SELECT..FOR UPDATE` appears nowhere; we used `INSERT..ON CONFLICT DO NOTHING` and conditional
`UPDATE..WHERE status=:expected` as the lock primitive. Attack each:
- `routers/orders.py` cancel/return/update_status — `UPDATE..AND status=:expected` + 409 on lost
  race + inventory released only on the win. **Probe:** concurrent cancel + mark-paid from `created`
  — can both still win? Does the 409-vs-404 split misclassify a deleted order?
- `services/inventory_guard.py::release_inventory_for_order` — CAS-claims the reservation
  (reserved→released) before crediting stock. **Probe:** two concurrent releases → is a double-credit
  truly impossible? What about reserve racing release?
- `routers/payments.py::checkout_initiate` — idempotency reserved BEFORE order/intent creation; key =
  header → order_id → **windowed** cart-signature (`sha256(uid+items+amt+cur | time//600)`).
  **Probe:** does the 10-min window let a genuine double-submit through at a bucket boundary? Does a
  failed checkout burn the key and block legitimate retry? Is the windowed key derivable/forgeable?
- `payments.py::create_intent` + `StripeClient.create_payment_intent(idempotency_key=)` — server dedup
  + provider key. **Probe:** the `if not key: return True` opt-in path — still a double-charge when no
  key supplied? Afterpay `/intent` got the same server guard — verify.
- `security/idempotency.py` IdempotencyMiddleware — atomic reserve-or-replay; DB error →
  process-WITHOUT-dedup (availability), request failure → release reservation. **Probe:** is
  "process without dedup on DB error" a hole for money endpoints? (Claim: no, they self-guard.) Does
  the in-flight 409 ever strand a client? Fingerprint-mismatch same-key behavior?
- `services/payment_ledger.py::reserve_refund_slot` + refund request/approve guards. Single-winner
  (order, count) lock riding the caller's txn (releases on rollback). **Probe:** two open requests →
  two approvals at different indices → **still a double refund?** (We guard both request and approve —
  verify the chain actually closes; the live-Stripe path also has a provider key.)
- `fulfillment_cases.py` budget-commitment TOCTOU — **documented, NOT fixed** (flag-off, needs a
  category lock). **Ask:** is documenting acceptable, or must it be fixed before the gate ships?

**B. Fail-closed flips — `4c012c2` (verify no over-block / availability regression).**
6 handlers that defaulted to ALLOW on an internal exception now fail closed:
`outbound_integrity` (secret-scan→BLOCK), `outbound_email_monitor` (→review), `auth._abac_tenant_allow`
(malformed allowlist→DENY), `compliance` TLS gate (decide-then-send), `events._idempotent`
(DB-error→raise→5xx→retry), `budget_gate` (bad-input→reject-when-cap). **Probe:** does ABAC-deny lock
everyone out on a fat-fingered config (intended)? Does events→5xx cause a webhook retry storm? Is the
TLS decide-then-send correct under an actual send exception?

**C. Prod config — `f10faf5`.** `DECISION_LOG_WRITES_ENABLED` now defaults ON in every env (was
dev-only → audit differentiator silently dark in prod). `data_residency.check_transfer` now ENFORCES
`signed_dpa` (cross-border + declared PII + unsigned → BLOCK). **Probe:** does default-on audit have a
perf/PII-compliance interaction with the still-unsigned DPA (P1-2)? Does the DPA gate rely on callers
declaring `data_categories` — an undeclared-PII bypass?

**D. Injection dedup — `e2bef61`.** 3 divergent guard regexes → one shared
`security/injection_patterns.py` (union, calibrated: ignore/disregard needs an instruction-context
word). **Probe:** attack strings that slip ALL three now? False positives on real shopping queries
("ignore the ones over $2000", "reset my password")? Did unifying NARROW any surface's coverage?

**E. Off-catalog consistency gate — `5196e74`.** The refuse↔serve flip (legacy regex denylist vs V2
sold-set allowlist) is now a CI gate for the dangerous direction. **Probe:** is a name-probe against
the denylist an adequate proxy for the query-level flip? What divergence does it MISS?

**F. Structural — `5950b80`.** 2 orphaned admin routers wired, dead `semantic_turn_router` deleted.
Low-risk; sanity-check only.

---

## PART 2 — What's needed to ARCHIVE `recommend.py` / `suggest()`

**The goal:** delete the 12,312-line legacy engine + `suggest()` + the chat→HTTP loopback hop (R11).
**Why it can't happen yet — the real blockers (not just "flip the canary"):**

### Blocker 1 — the non-canary lanes have no home without recommend.py
`CANARY_LANES = {SEARCH, FILTER, COMPARE, EXPLAIN, OFF_CATALOG}`. Everything else —
**CART_MUTATE, PROCUREMENT, SUPPORT_CLAIM, POLICY_QUESTION, INVENTORY, image turns** — *falls through
to legacy*. Deleting recommend.py deletes their handler. So before archive, each must either:
- be served by V2 (PROCUREMENT deliberately is NOT — it's advise-only; legacy owns the mature RFQ), or
- be **extracted** into its own standalone router/service that outlives recommend.py.
This is the single biggest archive blocker and it's a decision, not just code: *which lanes move to
V2, which get extracted to a thin legacy shim?*

### Blocker 2 — contract/safety characterization is incomplete
V2 has never served a live buyer turn. `tests/test_recommend.py` is legacy endpoint
characterization, not a legacy-equals-V2 parity oracle; its two xfails do not disable V2 evaluation.
Promotion must use the V2 contract/safety suites plus labeled relevance and shadow replay. Get
it green (legacy≡V2 on the served lanes), before trusting the cutover.

### Blocker 3 — the chat loopback hop
`chat.py:1855` → internal HTTP `GET /api/v1/recommend/suggest`. If we delete the suggest endpoint,
chat breaks. Must first replace the hop with a direct in-process call to the V2 facade.

### Blocker 4 — USER labels (the quality bar)
`relevance_labels.json` (case_id:turn) is still empty. Without human relevance labels we can measure
routing/safety/latency (the synthetic soak does) but NOT "is the shown product actually good" — the
one thing that decides whether V2 is safe to promote.

### The archive SEQUENCE (proposed — ask GPT-5.6 to critique/reorder)
1. **Extract the non-canary lanes** (cart/support/policy/inventory) from recommend.py into standalone
   modules; keep PROCUREMENT on a thin legacy shim (advise-only V2 + legacy RFQ).
2. **Complete contract/safety characterization** on the 5 canary lanes; keep product-set parity as a diagnostic only.
3. **Kill the loopback hop** → direct facade call (Phase-4).
4. **USER labels** → freeze the contract → minimal UI on the typed StageResult shapes.
5. **Canary ladder:** shadow → 1% → 5% → 25% → 50% → 100%, per-lane gates + auto-rollback on a
   regression in refusal-rate / empty-rate / latency / label-quality.
6. **At 100% + a soak window with zero regressions:** delete recommend.py, suggest(), the loopback
   hop, and the 37 `recommend_*` shim services that only legacy uses. NEVER "fixed" — a dated delete.

### Questions for GPT-5.6 on the archive
- Is "extract non-canary lanes first" right, or should PROCUREMENT/cart move to V2 before archive?
- What's the correct **parity bar** and **rollback trigger** for each lane in the canary ladder?
- What breaks if we delete recommend.py's 37 re-exported `recommend_*` services — how to find the
  ones with non-legacy consumers?
- Is the windowed-idempotency-key (P0-1b) the right long-term design, or should checkout require a
  client key outright?

---

## PART 3 — What to test / do next (the two you flagged)

### Procurement journey (untouched, 29 service tests green)
Confirmed working on the legacy rail; the PROCUREMENT-stays-legacy decision stands. **To test before
any procurement change:** the e2e journey (`tests/e2e/test_procurement_journey_playwright.py` — needs
a browser) + the bounded-autonomy demo (`scripts/demo_bounded_autonomy.py`). **Ask GPT-5.6:** does the
V2-advises→legacy-executes bridge (bulk economics → legacy RFQ draft) need building before archive, or
can procurement stay a permanent legacy shim?

### Off-catalog #1 — the reverse direction (deferred)
The gate (`5196e74`) catches "legacy refuses a SOLD category." The reverse — "legacy SERVES an unsold
category V2 refuses" (forklifts) — is the intended allowlist-is-stricter behavior, deferred. **To do
in the canary ladder:** wire the shadow differ to record refusal-verdict disagreements on live
traffic, so the real divergence rate is measured before the flip (not just the synthetic gate). The
demo DB must materialize its approved sold nodes before startup so the gate's real-data loop runs.
The `aa-*`, `el-*`, `hb-*`, and `lb-*` prefixes are valid Shopify vertical roots, not namespace drift.

---

## Appendix — verification state
~120 existing tests + ~20 new regression tests green (money-concurrency, fail-closed, DPA-gate,
off-catalog, injection corpus). Consolidated final run: 39 pass / 1 skip. Clean tree at `5950b80`.
