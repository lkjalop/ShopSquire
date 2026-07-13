# GPT-5.6 Review Packet — Review-9 delta (2026-07-13)

**Scope: `git diff c0b996d..HEAD`** (2 commits: `624fe25` review-9 fixes, `ea7ae9c` CI+memory).
13 files, +521/-58. This is the delta since your last review (`c0b996d`, tenant-cart identity).
The four review-9 findings you raised are addressed here — the ask is to (a) verify the fixes are
correct, (b) hunt NEW defects the fixes introduced, (c) re-check for silent swallows, (d) confirm
the next-steps read.

## What changed and why (self-assessment — challenge it)

### 1. R10.4b — shadow queue → Redis Streams (the concurrency change, review hardest here)
`recommendation_shadow_worker.py` (+177) + `recommendation_facade._enqueue_shadow`.
- Producer: `XADD shadow:core:stream` (approx maxlen 10k); **list fallback** on `AttributeError/
  TypeError` (DummyRedis / stream-less client).
- Worker: consumer group `shadow-workers`; **XREADGROUP** new entries, **XAUTOCLAIM** stale
  pending (>60s idle) FIRST, **XACK only AFTER** process/dead-letter. Poison = delivery count
  > `_MAX_DELIVERIES` (4) → DLQ stream + ACK (so the group can't wedge on one poison job).
- Legacy list STILL drained every cycle via **non-blocking `rpop`** (migration + fallback); the
  blocking `brpop(timeout=5)` runs only when the whole cycle found no work — deliberately NEVER
  `brpop(timeout=0)` (infinite block = the hang class).
- **SPECIFIC QUESTIONS FOR YOU:** (a) Is the XAUTOCLAIM-before-XREADGROUP ordering correct for
  fair recovery, or can a hot producer starve pending reclaim? (b) `_delivery_count` fail-opens to
  None on XPENDING error — does the poison path still converge via the DLQ on repeated failure, or
  can a poison job with unreadable delivery-count loop forever? (c) ACK-after-process is
  at-least-once; the worker is a READ-ONLY shadow (no side effects except metrics + trace log) — is
  duplicate delivery genuinely harmless here, or does the cart_shadow_plan trace-write need
  idempotency? (d) approximate maxlen can exceed 10k transiently — acceptable for a shadow stream?

### 2. Finding #2 — composite `unauthorized_rate` (promotion-gate change)
`quality.catalog_authorization_violations(db, shown_skus, tenant_id)`: a shown sku violates if it
(a) isn't in `products`, (b) is inactive, or (c) sits in a taxonomy node where
`sells_within is False`. Row's `unauthorized` = `payload_violations` (over-budget/dupes) +
`catalog_violations`. Fail-open 0 only on DB-unreadable. Wired into `shadow_replay` per shown slate.
- **QUESTIONS:** (a) `unclassified != unauthorized` (a real+active product with no classification
  is NOT counted) — agree, or should coverage gaps gate too? (b) fail-open-0 on DB error: does that
  let a broken DB read as clean authorization (masking)? I argued an infra failure must not be a
  quality signal, but you flagged exactly this class before (the silent-swallow family).

### 3. Finding #3 — preferred-value ranking
`core._preferred_values` (from resolver constraints) → `fit._preferred_distance` (rel dist cap 1.0;
UNKNOWN attr = full 1.0) → `ranking.rank_key` soft stage: **below** fit-group/failed-keys/
availability AND below an explicit `sort`, **above** retrieval-relevance/price. Lexicographic
tuple position is the guarantee it can't lift a min-fail product.
- **QUESTIONS:** (a) Is the lexicographic placement provably safe, or is there an input where
  preferred_dist reorders across a fit-group boundary? (b) UNKNOWN=1.0 penalty — correct, or does it
  wrongly sink a legitimately-unmeasured-but-good product below a measured-but-mediocre one?

### 4. Finding #7 — logged degradation
`checkout_upsell` DB-read swallows → `logger.warning`. The no-silent-except ratchet then caught 3
NEW swallows in my own review-9 code (fit/facade/worker) — all converted to logged. **Ask:** sweep
the delta for any swallow the ratchet's regex missed (it only scans enrolled _CORE_MODULES).

## Non-actions I took (challenge if wrong)
- #4 (23 fails-shown): closest-match honesty — products shown are labeled `fails`, ranked below
  meets; whether they're acceptable fallback vs noise is a LABELS question, not a code fix.
- #5 (returns/orders tenant identity): documented platform debt, R11-gated (multi-tenant prod).
- #6 (legacy split-brain): recommend.py 12,312 ln stays as the fallback until canary proves V2,
  then DELETED at R11 — not refactored.

## The two questions I actually need answered
1. **Any real defect in the Streams worker** (the reclaim/ack/poison logic) — this is new
   concurrency code and the highest-risk surface in the delta.
2. **Next-steps sanity:** is "labels → shadow soak → canary ladder → delete legacy" the right
   order, or is there a prerequisite I'm treating as done that isn't? (e.g. should the composite
   authorization run in the SOAK metrics, not just the offline replay?)

## Verification already performed
- Full mandatory gate: 217 tests green as one run (incl. test_quality.py now in CI).
- 5 Streams durability proofs incl. crash-before-ack → XAUTOCLAIM reclaim → zero loss.
- Both ratchets green (no-flavour, no-silent-except @ baseline 0).
- 9 review cycles, zero finding ever reopened (falsifiable death-spiral check still holds).

---

## FOLLOW-UP (2026-07-13, post-review-9 assessment) — all 5 stream + 2 authz findings CONFIRMED and FIXED
The review above CORRECTLY caught real defects in this delta. Corrections landed:
- **CORRECTION to my "zero-loss" claim:** it was too strong. Crash-recovery IS zero-loss
  (XAUTOCLAIM), but the ORIGINAL delta had: approximate MAXLEN that could trim un-acked pending
  work (#1), ACK before durable DLQ (#2), malformed entries eternally pending (#3),
  poison-non-convergence when XPENDING unreadable (#4), and duplicate processing (#5). All real.
- **#1 fixed:** MAXLEN dropped from the active input stream; worker XDELs each entry AFTER a
  durable outcome (self-cleaning, length ≈ live backlog; XLEN is the soak backpressure signal).
- **#2 fixed:** typed outcome (PROCESSED/DEAD_LETTERED/DUPLICATE/RETRY); ACK only on the first
  three, and DEAD_LETTERED only when the DLQ write SUCCEEDED — a failed DLQ write → RETRY (stays
  pending). `_dead_letter` now returns bool.
- **#3 fixed:** malformed entry (no payload / trimmed) → DLQ + ack, never skipped.
- **#4 fixed:** poison detection uses a Redis attempt COUNTER independent of XPENDING; unreadable
  attempt state on a real client → assume poison, not infinite retry.
- **#5 fixed:** idempotency `done` marker per job — redelivery is a no-op (no re-process/re-count).
- **Starvation (stream-Q1) fixed:** bounded reclaim batch + ALWAYS also read new each cycle.
- **Authz #A1 fixed:** `catalog_authorization()` returns `{violations, measured, classified}`;
  UNMEASURED (db unreadable) → gate FAILS closed. **#A2:** the SAME evaluator runs in `process_job`
  soak metrics (one source of truth). **#A3:** `classified_shown_rate` is a SEPARATE gate (≥0.98).
- **STILL OPEN (correctly deferred):** a REAL-redis integration test (fakes are simulations) —
  next; UNKNOWN=1.0 penalty tuning (needs labels); category-chain completion (onboarding increment).
