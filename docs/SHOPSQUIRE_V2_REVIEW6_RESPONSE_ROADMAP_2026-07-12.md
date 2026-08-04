# V2 — Review-6 Response + Reordered Roadmap (2026-07-12)

GPT-5.6 review-6 verdict: architecture is right; **not ready for search-core canary**, and
`RECOMMEND_CART_SERVE=on` only inside a supervised session. It found 22 items across quality,
transaction, tenancy, timeout, and measurement. This is what we did and the reordered plan.

## Fixed already (`7936c97`, all tested)
| # | Was | Now |
|---|---|---|
| 1 (P0) | Quality gate OPTIONAL — `quality is None or …` let an unmeasured run report `gates_pass=True` | Split: `diagnostic_pass` (parity/honesty) vs `gates_pass` (PROMOTION) which now REQUIRES `quality_evaluated=True`. Locking test + 2 parity tests fixed. |
| 4/13 | AUTO tier auto-applied a single op without a click | **Confirmation-only by default** (`RECOMMEND_CART_AUTO_APPLY` off) — nothing mutates without a human confirm during the soak |
| 21 | Canonical text-search still N+1 (`_canonical_get` per SKU) | `_canonical_get_many` (one query/table) |
| 22 | Shadow worker swallowed metrics + `db.close` failures | Logged; worker enrolled in the silent-except ratchet @0 |
| 18 | "unauthorized" overclaimed; missing price evaded budget | Honest scope (budget+dupe only, documented); missing/unparseable price under a budget = violation |
| 19 | Coverage counted labeled refusal cases | Numerator restricted to product-expected (matches denominator) |
| 17/20 | `prior_shortlist` / `preferred` comments claimed they drove behavior | Comments now say RECORDED-not-consumed; wiring tracked |
| — | Packet scope stale; worktree dirty | Scope noted; `start_cart_validation.ps1` committed |

Also from the earlier defect-hunt (`3e42246`): apply_plan wedge/mutate-then-lie guarded, TOCTOU
narrowed, worker busy-spin fixed, dead `apply_cart_ops` deleted, hash normalized, 2 stale tests
greened.

## Reordered roadmap (GPT-5.6's order, adapted — P0 measurement/txn first)

**P0 — before ANY search canary or unsupervised cart-on:**
1. ✅ Quality gate requires measurement (done).
2. **One-transaction cart mutation** (#2/#3): thread ONE session through
   `_get_or_create_cart`/`_save_cart`/`_finish`; add a `draft_orders.version` column + versioned
   CAS (`WHERE version=:expected`); Postgres `SELECT … FOR UPDATE`, SQLite `BEGIN IMMEDIATE`.
   Undo stashed only after the versioned update succeeds (#4). Kills the crash-window + the
   cross-process lost-write.
3. **Tenant/principal ownership** (#5): derive tenant from the authenticated request (not the
   body); cart identity `(tenant_id, uid)`; remove client `tenant_id` from `ApplyPayload`;
   authorize the principal for the requested uid/cart. (Frontend hardcodes `"default"` today.)
4. **Confirmation-only soak** (done) + **plan-table migration** (#6): Alembic DDL for
   `cart_mutation_plans` with indexes `(tenant,uid,status)` / `expires_at` / `trace_id`; expired-plan
   cleanup + query-retention/redaction.
5. **SSE deadlines + shared idempotency** (#11): the 3.5s timeout is cleared on headers (SSE
   sends `thinking` instantly) so the body read can hang forever — add heartbeats, an idle
   timeout on `reader.read()`, a total turn deadline, and one idempotency key shared by
   stream+fallback (the resolve side has no idempotency; a slow first call can double-resolve).

**P1 — make the measurement REAL (so V2 can be PROVEN before canary):**
6. **Serialize the full typed envelope** into shadow jobs (#7): `TurnEnvelope.as_dict()` with
   schema version — budget/session/image/role/qty, not just query+uid+trace.
7. **Richer redacted V1 projection + quality-in-replay** (#8/#9): persist a full served-response
   projection (message class, clarify, panel, gates, fit), and CALL `evaluate_case_quality`/
   `summarize_quality` in the worker + offline replay. Today quality.py is test-only — the A/B
   census still shows `quality: null`.
8. **Stateful multi-turn replay + real referent consumption** (#10/#17): carry node/shortlist/
   constraints/ts turn-to-turn so M3-C2 session behavior is in the A/B evidence; wire
   `prior_shortlist` into a referent stage.

**P2 — smarter model, then cut over:**
9. **Store-profile host nodes for reroute** (#15): `capability_host_nodes.run_on = [Laptops,
   Desktops]` — model picks the relationship, policy picks the device (not "most-classified",
   which can pick an accessory).
10. **Continuation evidence for session inheritance** (#16): bounded `refers_to_prior` +
    confidence + session age, not lane alone.
11. **`preferred` → ranking** (#20); **fill + seal relevance labels**, rerun `--facade-mode` +
    stateful A/B.
12. **chat.py thin-edge** (#12): kill `_classify_turn_intent` + the internal HTTP hop; ONE
    router classifies lane AND produces the cart proposal in one model call — removes the
    per-carted-turn extra resolver call (#12) and the double-classifier.
13. Only after P0+P1 gates pass: `canary:1` → measured ramp → primary → archive `suggest()`.

## Go-live posture (GPT-5.6-aligned)
- `RECOMMEND_CART_SERVE=on` ONLY during a supervised validation session; **return to `shadow`
  (or off) after** until P0 #2/#3/#5 land. Confirmation-only means no silent mutation meanwhile.
- **Search core stays off** — the cyberpunk/budget screenshots (legacy bugs V2 targets) can't be
  promoted-away until quality is measured in replay (P1 #7) and labels are sealed.

## The screenshot verdict (30/28)
Both are the *cyberpunk, $2,300* SEARCH query → **legacy `suggest()`** (V2 search off):
- **30 "lose budget":** follow-up drops the $2,300 → a $5,999 top pick. Legacy multi-turn
  budget-loss. V2 fix path = session-carried budget RANGES (B1) + C2 session — but unproven
  until P1 measurement.
- **28 "why lenovo looks bad":** gaming query → zero-GPU top pick (score 100) + self-contradicting
  narration. Legacy use-case-fit + narration. V2 fix path = intent_resolver workload floors
  (cyberpunk → gpu_vram) + fit verdicts + reroute.
- Neither is caused by cart/M2/M3. Both are the CASE FOR finishing P1 (measure) before trusting
  V2 to serve search.
