# ShopSquire — Detailed Roadmap (post GPT-5.6 review-11b, 2026-07-14)

Supersedes the earlier roadmap docs. Grounded in the **verified** state after GPT-5.6's review:
money-path is **NOT production-closed** (the identity bug is fixed; the state-machine work remains),
and V2 promotion is blocked by **more than labels** (6 safety divergences + latency/reliability).

Owner tags: **[ME]** agent-doable · **[USER]** you (labels, judgment, sharing replay output) ·
**[CAL]** calendar/soak-clock. Effort: **S** <½day · **M** ~1-2 days · **L** ~3-5 days · **XL** week+.

---

## 0. Where we actually are

- **Done + verified:** money-path CAS/idempotency for the *clean* races (order-state, inventory
  release, refund slot-lock, checkout key required, **cross-tenant/query idempotency #1**, failed-
  payment inventory release #4, failed-path ledger dedup #5, no-un-keyed-live-intent #7); the
  retrieval host-union fix (constraint-sat 80→87%); the cart-ambiguity gate; fail-closed flips;
  audit-log-in-prod + DPA; injection dedup; off-catalog gate; middleware hardening; CI Postgres.
- **NOT done (the real blockers):** money state-machine (leases/outbox/refund-retry); eval
  schema+split; V2 divergences + latency; cart whole-op authorization; SSE hang timeouts; archive.

---

## TRACK M — Money-P0 state machine (THE real-store blocker; critical path) — **[ME]**

The identity bug is fixed; these are the durable-state gaps GPT-5.6 found. Build in this order
(each is the foundation for the next).

- **M1 · `payment_attempts` + transactional outbox** (GPT-5.6 #3) — **L**
  - Where: `payments.py:335-360` (Stripe intent created, then `stripe_intent_id` + ledger writes are
    SWALLOWED → an externally-created intent can have no local association).
  - Do: a durable `payment_attempts(id, order_id, provider, provider_ref, amount_cents, state,
    created_at, updated_at)` row written BEFORE the provider call; provider creation → local
    association → reconciliation as explicit states, via a transactional outbox (not best-effort
    warnings). A reconciliation reader closes orphans.
  - Gate: kill a process between Stripe-create and local-write → reconciler finds+associates the
    orphan; no intent without a durable attempt row.

- **M2 · Idempotency reservation as a STATE MACHINE + leases** (GPT-5.6 #2) — **M**
  - Where: `security/idempotency.py` (reservation is a boolean; a reserved-no-response row returns
    409 forever — no TTL/expiry on DB rows; `call_next()` raising is treated as "no side effect,"
    which is unsafe — an endpoint can commit then fail during serialization).
  - Do: `reserved → executing → succeeded | failed_retryable | indeterminate→reconcile`; add
    `state, lease_expires_at, owner_token, updated_at` + stored response headers to the schema; a
    lease lets a dead owner's reservation be reclaimed after expiry; `indeterminate` routes to
    reconciliation instead of blind retry or permanent 409.
  - Gate: killed-mid-flight reservation reclaims after lease; a commit-then-serialize-fail does NOT
    re-execute NOR stick at 409.

- **M3 · `refund_execution` states + idempotent retry/reconcile worker** (GPT-5.6 #6) — **M**
  - Where: `payments.py:600-620` (approval committed BEFORE the provider refund call; if the provider
    fails, re-calling approve returns `no_open_refund_request` — the "operator can retry" comment is
    not backed by an endpoint).
  - Do: `refund_execution(order_id, approval_id, state[pending|executing|settled|failed], provider_ref,
    idempotency_key, updated_at)`; a retry/reconciliation worker drives approved-but-unsettled to
    settlement idempotently (reuse the Stripe idempotency_key). Add an explicit execute/retry endpoint.
  - Gate: provider-fail after approval → worker retries to settlement; approved_cents never exceeds
    captured; no double refund.

- **M4 · Full Stripe `event.id` dedup table** (completes #5) — **S**
  - Where: `payments.py` webhook (succeeded + failed now CAS-gated; `charge.refunded`/settlement path
    still appends on repeat delivery).
  - Do: persist `stripe_events(event_id PK, type, processed_at)`; process each event once across ALL
    handlers.
  - Gate: replay the same webhook 3× → ledger unchanged after the first.

- **M5 · Concurrent HTTP integration tests** (GPT-5.6 roadmap #2) — **M**
  - Where: new `tests/chaos/test_money_concurrency_http.py`.
  - Do: threaded/async concurrent POSTs through the REAL handlers (checkout, cancel, refund) against
    Postgres + a mocked provider — exercising middleware + inventory + ledger together, not just the
    SQL primitives (`test_money_concurrency_postgres.py` tests the primitives only).
  - Gate: N-way concurrent checkout/refund/cancel storms hold every invariant end-to-end.

**TRACK M EXIT (real-store production grade):** M1–M5 done + **full-repo pytest green in CI with
Postgres** + a GPT-5.6 re-review finds no confirmed money defect. Est **~1.5-2 weeks [ME]**.

---

## TRACK E — Evaluation truthfulness (prereq for labels) — **[ME] then [USER]**

- **E1 · Fix the label loader + ENFORCE the split** — **S/M**
  - Where: `recommendation_core/quality.py:58` (reads `entry.get("labels")` — the real schema is
    `{cases:{"case:turn":{labels:{sku:grade}}}}`) and `:232` (aggregates ALL labeled rows — the
    declared dev/test split is never enforced).
  - Do: one validated JSON schema; the evaluator honors an explicit `dev` (tunable) vs sealed `test`
    (gate) split; store `catalog_snapshot_hash`, `taxonomy_version`, `annotators`, disagreement
    resolution. Add a schema-validation test.
  - Gate: a malformed label file fails loudly; dev labels never leak into the test gate.

- **E2 · Produce the labels** — **[USER] + GPT-5.6**
  - GPT-5.6 = weak/dev labels (it's an independent judge, not the evaluated qwen3). **Human review
    for the sealed test split.** Corpus: `tests/golden/suggest_corpus/`, keyed `case:turn`, grade the
    CANDIDATE SLATE 0/1/2 against the demo catalog.
  - Gate: **100% coverage of the test split** (GPT-5.6's bar, not 30% of convenient cases); NDCG@10
    and precision@10 become computable.

---

## TRACK V — V2 quality + reliability (promotion blockers beyond labels) — **[ME] + [USER]**

- **V1 · Adjudicate the 6 BLOCKER divergences** — **M** — *BLOCKED on [USER] sharing the replay
  output* (`tmp/quality_diagnosis.json`). Classify each (accessory/compare/explain-followup/
  off-domain/off-catalog) as V2 defect | legacy known-wrong | expected contract change; fix the V2
  defects. Gate: 0 unresolved BLOCKERs.
- **V2 · Latency + reliability gates** — **M** — the replay had 2 cases at 34-35s and ended in a
  `qwen3:14b` timeout. Add **p95 < 8s** and **timeout/fallback < 1%** gates to the eval; add model
  deadlines + fallback in the router. Consider a faster/smaller served router model (routing is
  bounded-vocab classification). Gate: p95 < 8s, timeout-rate < 1% on the corpus.
- **V3 · Retrieval scalability** — **M/L** — the host-union does multiple `ORDER BY sku LIMIT` + an
  in-memory merge (`core.py:915`): correct for 114 demo products, NOT a scalable relevance strategy.
  Replace with a vector/typed-attribute retrieval that spans the host family in one ranked query.
  Gate: single ranked retrieval, no in-memory N-way merge on the hot path.
- **V4 · Diversity/message-class regression** — **S** — the retrieval fix dropped diversity 68→62%
  and message-class 84→79%. Tune (shelf-band diversity, message composer) so fit gains don't cost
  answer variety. Gate: diversity/message-class back to prior levels with fit held.

**TRACK V EXIT (V2 promotable):** V2 ≥ legacy on labeled relevance (Track E) + V1-V4 gates. Partly
[USER]-bound (replay output + labels).

---

## TRACK C — Cart safety — **[ME]**

- **C1 · Deterministic authorization for whole-cart ops** (GPT-5.6) — **M** — `clear_all` /
  `keep_only` / quantity commands must be INDEPENDENTLY proven from the shopper's words, not trusted
  from the model alone; retain human confirmation for destructive ops. Where: `cart_resolver.py:239`
  (whole-cart intents currently trust the model's action). Gate: a model `clear_all` with no
  clear-intent token in the query is not executed without confirmation.
- **C2 · `keep_only` vs `set_quantity` misclassification guard** (#2b) — **S** — "make the Lenovo 15"
  → model returned `keep_only`, dropping the number. A deterministic "clear number + one target →
  set_quantity" heuristic. Gate: quantity-bearing commands never silently become keep_only.

---

## TRACK H — Hangs + tech debt — **[ME]**

- **H1 · SSE heartbeat timeouts** — **S** — `routers/decision_trace_events.py:260`,
  `escalation_room.py:879/913/1848`, `decisions.py:934`: `await q.get()` in `while True` with no
  timeout parks the coroutine forever on client disconnect. Wrap in `asyncio.wait_for(..., heartbeat)`
  + re-check `request.is_disconnected()`. Gate: a disconnected SSE client's coroutine exits within
  the heartbeat.
- **H2 · Thread-future timeouts** — **S** — `services/async_safe.py:25`, `orchestrator.py:24`:
  `pool.submit(...).result()` with no timeout. Add bounded `.result(timeout=…)`.
- **H3 · Middleware streaming buffer** (P2) — **S** — don't buffer streaming responses for keyed
  requests (real streaming keyed endpoints don't exist today; low priority).

---

## TRACK A — Archive `recommend.py` (LAST — after M + E + V) — **[ME] + [CAL]**

*Correction: the "parity oracle disabled" blocker was WRONG (GPT-5.6 verified the suite passes minus
2 documented security xfails) — remove it from the blocker list.*
- **A1 · Extract non-canary lanes** — **L** — cart/procurement/support/policy/inventory/image fall
  through to legacy; extract into standalone modules (or a thin procurement shim) so deleting
  `recommend.py` doesn't orphan their handlers.
- **A2 · Kill the chat→HTTP loopback hop** — **M** — `chat.py:1856` calls `/suggest` over HTTP;
  replace with a direct in-process facade call.
- **A3 · Canary ladder** — **[CAL]** — shadow→1→5→25→50→100 with per-lane auto-rollback
  (refusal/empty/latency/label-quality/error gates).
- **A4 · Dated delete** — **M** — remove `recommend.py`, `suggest()`, the loopback, the 37
  legacy-only `recommend_*` shims; re-run the full suite.

---

## Critical path + sequencing (what blocks what)

```
NOW ─► TRACK M (money state machine, M1→M5)  ── the real-store gate, highest priority [ME]
        │
        ├─ parallel ─► TRACK E1 (eval schema/split)  [ME]  ─► E2 labels [USER+GPT]
        ├─ parallel ─► TRACK H (hangs)  [ME, cheap]
        ├─ parallel ─► TRACK C (cart safety)  [ME]
        │
        └─ after M green + E2 labels ─► TRACK V (divergences, latency, scalability) [ME+USER]
                                          │  (V1 also needs [USER] replay output NOW)
                                          └─► TRACK A (archive: extract lanes → loopback → canary → delete)
```

- **Real-store production grade** = Track M EXIT (money state machine + CI-green). ~1.5-2 wk [ME].
- **V2 promotable** = Track E (labels) + Track V (gates). USER-bound (replay + labels) + ~1-2 wk [ME].
- **Legacy archived** = Track A, only after both above. ~1-2 wk [ME] + canary [CAL].

---

## Immediate next 5 (my recommendation)
1. **[ME] M1 — `payment_attempts` + outbox** (the foundation the other money states build on).
2. **[USER] Re-run GPT-5.6** on the 4 committed money fixes (#1/#4/#5/#7) to confirm closed before
   more is built on them.
3. **[USER] Share `tmp/quality_diagnosis.json`** → unblocks V1 (6-divergence adjudication).
4. **[ME] E1 — fix the label loader + split enforcement** (prereq before any labeling).
5. **[ME] H1/H2 — SSE + thread timeouts** (cheap, removes the known hangs).

**One-line honest status:** the money path is *not* closed — the clean races are fixed, the durable
state machine (leases/outbox/refund-retry) is the remaining real-store blocker; V2 is blocked by
labels **and** safety divergences **and** latency. No overclaim this time.
