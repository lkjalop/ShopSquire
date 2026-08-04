# ShopSquire — Test-Anchored Roadmap (2026-07-16)

*Post-verification of the uncommitted batch (money + image + eval clusters, working tree vs
`711777b`). Orchestration principle: **every item is a triple — {claim, RED test proving it's
needed, EXIT test proving it's done} + an owner.** No item is "ready" until an independent pass has
verified its premise (that pass is what corrected the latency #1 below). Diagnose ≠ fix: any latency
item carries a measurement that attributes the failure before a fix is named.*

**Owners:** `ME` = implementable by the agent · `USER` = your decision/action · `OPS` = machine config.

---

## Verification summary (three parallel adversarial passes — what's actually true)

- **Money — SOLID + 1 real risk.** Webhook inbox/outbox (leased CAS claims, event-id dedup,
  CAS-guarded transitions, wired drainer), failed-payment release (transactional + CAS-idempotent),
  refund workers (claim-token + provider idempotency-key reuse), paid-order cancel CAS, tenant-scoped
  idempotency — all verified correct. **RISK:** the at-least-once outbox appends to a *non-idempotent*
  ledger; `reconcile_refund` commits `refund_settled` *before* `settle_submitted_for_intent`, so a
  transient failure of step 2 re-appends on retry → **double-counts `settled_cents`/`captured_cents`**
  (ledger/reconciliation corruption, not a double payout — provider idempotency key backstops money).
- **Image — all 4 SOLID + 1 new finding.** Byte separation correct (steg/phash on RAW — *and it fixes
  a prior steg-on-sanitized-bytes bug*); recursive PII redaction + Luhn correct (spares order IDs);
  React object-as-child crash fixed + tested; `cv_provider` egress gap confirmed (fail-safe).
  **NEW:** the adversarial detector + QR/barcode decode now run on **downscaled** bytes — and QR
  decode feeds the `qr_external_url_detected → text_only` security wipe. A tiny malicious QR in a huge
  image could decode at full-res but be lost at 1280px → **fail-open erosion of a security control.**
- **Eval — claims real, but the report's #1 is MISDIAGNOSED.** Replay latency/p95/timeout/fallback
  instrumentation + gates are correct; labels are draft (8 cases, human-review-pending, 31.25%
  coverage). **CORRECTION:** "remove the loopback" can NOT fix p95 — the floor is the single ~7–12 s
  router *model* call (`core.py:123/131-133` says so; matches `1476dc2`: 99.9% model, harness ~17ms).
  The loopback is tens-of-ms overhead. The real p95 lever is the MODEL.

**Promotion verdict:** V2 correctly stays pre-canary — blocked by **measured latency**, not relevance
or safety. But three correctness items (below) should clear before promotion regardless.

---

## The roadmap (reordered, test-anchored)

### P0 — correctness/safety (clear before promotion)

**1. Money ledger idempotency** · owner `ME`
- Claim: at-least-once outbox + non-idempotent ledger append can double-count settlements.
- RED test: inject a transient failure of `settle_submitted_for_intent` (step 2) after the
  `refund_settled` append in `reconcile_refund`; assert on retry `settled_cents` is NOT doubled.
- EXIT: red test passes + outbox ledger appends are idempotent (`UNIQUE(event_id, kind)` or
  append+settle wrapped in one transaction). Also fix the migration's no-op backfill
  (`SET state='processed' WHERE state IS NULL` never matches — `server_default='pending'`).

**2. Image security-control bytes** · owner `ME`
- Claim: QR decode + adversarial detection run on downscaled bytes → a tiny high-res malicious QR /
  high-frequency perturbation can be attenuated and missed (fail-open on a security signal).
- RED test: a fixture QR that decodes at full-res but not at 1280px; assert `qr_external_url_detected`
  still fires (or the pipeline fails CLOSED on an undecodable-after-downscale QR).
- EXIT: QR/barcode decode + adversarial run on **raw/full-res** (like steg/phash), or a less-aggressive
  copy for those; red test green. (Also: fix the 413 message that says "image_too_large" for a pure
  decode failure — `reason:"decode"` should read as unreadable, not oversized.)

**3. `cv_provider` local-model egress allowlist** · owner `ME`
- Claim: `ensure_safe_outbound_url` blocks `localhost` always and `127.0.0.1` under prod defaults →
  local Ollama vision silently degrades to no-provider.
- RED test: with `OLLAMA_URL=http://localhost:11434` (and prod-default env), assert the vision
  provider is reachable.
- EXIT: an **explicit configured internal-service allowlist** (NOT a general private-network bypass)
  honors the local model endpoint; red test green; prod still blocks arbitrary private IPs.

### P1 — latency (the real canary blocker — diagnose before fixing)

**4. Latency attribution FIRST** · owner `ME`
- RED/measurement: a stage-timing probe over the replay that attributes p95 to {model call | retrieval
  | loopback | serialization}. EXIT: a report that numerically attributes the 13 s p95 (expected:
  model-dominated, per the code + `1476dc2`). *This step is mandatory before any latency fix — it is
  the step the original roadmap skipped.*

**5. Model latency — the real lever** · owner `USER` (decision) + `ME` (impl)
- USER decides the lane: (a) smaller/quantized router model, (b) cap `num_predict`, (c) commit to
  GPU + warm keep-alive, (d) relax the 8 s gate for the demo.
- EXIT: p95 < 8 s across **3 consecutive sealed replays** (the existing quality gate).

**6. Overhead cleanup (NOT a p95 fix)** · owner `ME`
- Remove the chat→`/suggest` httpx loopback (call the facade/handler directly — carefully, preserving
  the middleware/auth the hop re-runs and legacy-lane parity) + collapse the A/B budget-filtered vs
  budget-free scope double-fetch (`core.py:365/895`).
- EXIT: contract-stability + parity tests green (no behavior change); measured overhead reduction.
  Framed as cleanup/cold-start, explicitly not the p95 fix.

### P2 — quality oracle

**7. Human-review the 8 draft labels** · owner `USER`
- The labels ARE the relevance test oracle; NDCG/precision are meaningless until it's trusted.
- EXIT: 5 test + 3 dev cases reviewed, reviewer identity + disagreements recorded, `review_status`
  flipped off `independent_draft_requires_human_second_pass`.

### P3 — promotion (after P0–P2)

**8. Shadow soak → canary ladder.** 200–500 persona/procurement/image/cart turns, then
`shadow → 1% → 5% → 25%`. Gate: zero unauthorized products, zero money regressions, p95 < 8 s,
fallback < 1%. · owner `ME` + `USER` (canary go/no-go)
**9. Money staging proof.** Apply the migration in disposable PG CI; real Stripe test-mode webhook
redelivery / provider-crash tests; derive tenant identity from authenticated middleware, not raw
headers. · owner `ME`

### P4 — archive (last)

**10.** Dispatch-hoist → characterization net (xfail→strict) → **IMAGE V2 rebuild (critical path)** →
canary → dated deletion of `recommend.py` (12,349 ln) / `suggest()`. · owner `ME` + `USER` (labels/canary)

---

## What's needed from USER (the gates only you can clear)
1. **Model-latency decision** (item 5) — determines whether p95 can ever pass.
2. **Human-review the 8 labels** (item 7) — the quality oracle.
3. **Money risk-appetite** (item 1) — fix-before-anything, or acceptable-for-now?
4. **Ops:** `OLLAMA_MAX_LOADED_MODELS=2` (router + glm-ocr coexist in 12 GB) — `OPS`.
5. **Commit decision:** the batch is verified good with 3 P0 fixes pending — commit as-is now, or
   fix-P0-then-commit?

## TDD lessons banked (so this doesn't recur)
- The loopback error was a **diagnosis dressed as a fix** — no exit test, no attribution. Rule added:
  latency items require a measurement first.
- Known risks (money double-count, QR-on-downscaled) are **not real until pinned by a red test**;
  P0 items 1–2 each start with the red test.
- Draft labels = **untrusted oracle**; green means nothing until item 7.
