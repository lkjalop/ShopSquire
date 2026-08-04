# ShopSquire V2 — Detailed Roadmap after Review-8 (2026-07-12, HEAD f2732f7)

> **STATUS UPDATE 2026-07-13 (post-review-9): R8 DONE (except R8.3 labels = USER), R9 DONE
> (all six), R10 DONE (10.1–10.4b), REVIEW-9 + FOLLOWUP FIXES DONE.** Label-free gate green
> (constraint-sat ~78%, empty 0/21, unauthorized 0, diversity ~73%). Since this doc was written:
> R9.1–R9.6, R10.1 (envelope-in-jobs + phantom-empty fix), R10.2 (tenant-cart identity, both
> steps), R10.3 (lease CAD), R10.4a (mandatory CI), R10.4b (Redis Streams worker), and the
> review-9 delta (composite authorization + fail-closed measured flag + classification-coverage
> gate + preferred-value ranking + logged degradation) all landed. **Remaining = R8.3 labels
> (USER), one real-Redis integration test, R11 soak→canary→primary→retire legacy.** This header
> supersedes every per-item status below where they conflict — the body is kept for the WHY.

## Where we are (measured, not asserted)
Final qwen3:14b re-measurement (`--facade-mode --diagnose`) after ALL 5 fixes (incl. f2732f7):

| Gate metric | Baseline (review-8) | Now (final) | Threshold | Status |
|---|---|---|---|---|
| constraint_satisfaction | 39.4% | **80.0%** (meets 112 / unknown 14 / fails 14) | ≥70% | **PASS** ✅ |
| unauthorized_rate | 0% | 0% | 0% | PASS ✅ |
| empty_rate | 16.67% | 22.22% (4/18) | ≤15% | FAIL — but see breakdown |
| diversity | n/a | n/a (brands NULL) | ≥30% | blocked by brand data (R9.5) |
| labeled_coverage | 0% | 0% | ≥30% | **FAIL — human task (R8.3)** |

**Read:** constraint-sat nearly DOUBLED (39.4→80) and the fails-dominated ranking problem is solved.
Two gate blockers remain: labeled_coverage (no human labels yet) and empty_rate. The 4 empty cases,
diagnosed by direct probe, are NOT one thing:
- `off_domain` "pizza place near me" → node=None, correct **honest-empty** → the only true R8.1 metric fix.
- `accessory_bag` "a laptop bag that fits a 16 inch laptop" → model routed to **Laptop Sleeves (empty)**
  instead of **Laptop Bags (lb-15, in stock)** = a **grounding-precision** miss (R8.2).
- `compare_two_models` → **model-nondeterministic** (probe returns 10 gaming laptops via el-6-11-2) + the
  COMPARE **no-op** (returns 10, never narrows to the 2 named) (R9.3).
- `explain_followup` "why is the first one better?" → **multi-turn continuation** gap (R9.4).
The 3 diagnostic "price-bleed" suspects are all `storage_gb≥1000` on A100/AI-fine-tune queries — LEGIT
AI-storage floors (1TB for local LLM work), a heuristic false-alarm, not a budget bleed. Item-2 holds.
V2 core is close to **label-free-green**; NOT canary-ready until labels + multi-turn + ops land.

Five fixes committed this arc: `00003b5` budget-bleed, `65baf39` reroute host-nodes, `11814bc`
integrated-GPU derive, `4e13502` accessory req-leak + pharmacy Bug A/B, `f2732f7` ungrounded-workload
reroute (last pharmacy hole). Pharmacy bleed killed on both phrasings. V2 core refuses A100/car/insulin
correctly (legacy @live test fails the same A100 case).

---

## PHASE R8 — close the measurement (make the gate honestly green). ~1 session.
Goal: the gate reflects TRUTH, then get the labels that unblock the labeled metrics.

- **R8.1 empty-rate honesty (item-7 — narrower than first thought).** `_quality_case`
  (tests/characterization/shadow_replay.py:48) counts `off_domain` "pizza place near me" (node=None,
  no requirements → genuinely off-domain) as an empty FAILURE. FIX: node=None AND no requirements AND
  not a groundable category → `expects_products=False`. Worth ~1/18. **Bound tightly** — a node-routed
  empty (accessory_bag routes to a REAL node) is still counted, so it can't mask a routing miss. Add
  node_handle+requirements into the case meta from `core.extras["decision"]`.
- **R8.2 accessory grounding precision (the real accessory_bag bug).** "a laptop bag that fits a 16 inch
  laptop" routes to **Laptop Sleeves (el-7-8-2-4, empty)** instead of **Laptop Bags (lb-15, in stock)** —
  reqs={} (leak gone), just the WRONG sibling node. This is a semantic-grounding precision miss (the
  model picks the node from candidates). Fix path: improve the onboarding candidate set / node
  disambiguation for accessory families (bag vs sleeve vs case), or a store-profile synonym hint. NOT a
  quick deterministic patch — it's model grounding quality. Measure first (how many accessory queries
  mis-ground), then decide candidate-retrieval vs profile-hint.
- **R8.3 HUMAN LABELING (unblocks precision@10 + NDCG@10 — the last gate).** USER fills
  `tests/golden/relevance_labels.json` (dev/test split; strata: budget / negation / gaming / persona /
  off-catalog / multi-turn; grades 0/1/2; TWO reviewers; the model never writes labels). This is the
  one thing only you can do. Everything else can proceed in parallel.
- **R8.4 DONE — stable diagnose confirmed 80% constraint-sat post-f2732f7.** (Also: `_diagnose_case`
  should record `node_handle` — it currently doesn't, which cost a probe round to recover routing.)

## PHASE R9 — multi-turn refinement (the big "smarter than legacy" lever). ~2-3 sessions.
This is where screenshots 30 and the FILTER/COMPARE/EXPLAIN no-ops live. Today plan.py:35-37 maps all
three to `["retrieve","fit_check"]` — they re-run the same retrieval and apply no refinement.

- **R9.1 session carries constraints forward (fixes budget-loss / screenshot 30).**
  postflight (recommendation_postflight.py:51) writes only last_node_handle + last_shortlist_skus. ADD
  last_budget_{min,max}_cents + last_requirements. facade (recommendation_facade.py:330) reads them into
  session. core inherits budget+requirements ONLY on a CONTINUATION turn (FILTER/COMPARE/EXPLAIN or a
  nodeless refinement — mirrors the prior_node inheritance already in turn_router:264), and a FRESH
  SEARCH resets them (context-rot guard, ledger §8). Test: T0 "gaming laptop budget 2500" → T1 "show me
  cheaper" keeps the 2500 + the node.
- **R9.2 FILTER executor.** New closed-vocab refinement resolver (model→{filter_brand, filter_price_max,
  add_requirement, sort} clamped to real values) + plan step `apply_filter` + core `_exec_filter` that
  narrows the inherited shortlist/node. "only Asus" → brand filter; "show me cheaper" → price sort/cap;
  "16GB or more" → add ram_gb>=16 to the inherited requirements. Reuses cart_resolver's DF-token binding
  discipline. Depends on R9.5 (brand) for brand filters.
- **R9.3 COMPARE executor.** "compare the Dell G16 and the MSI Katana" must NARROW to the 2 named units
  (bind names→SKUs via the DF-token index, show ONLY those with a spec-diff table), not return the whole
  category. plan.py COMPARE + core `_exec_compare` + entity-bind.
- **R9.4 EXPLAIN executor (consumes prior_shortlist — item 6/review-6 #17).** "why is the first one
  better for me?" → resolve "the first one" against session.prior_shortlist, explain that pick's fit
  verdicts. Kills the explain_followup empty case.
- **R9.5 brand data fix.** Demo `products.brand` is NULL (brand lives only in titles) → ProductCard.brand
  ='' → brand filter + diversity metric both broken. Backfill brand (seed script: extract from title or
  re-import), or derive brand in the read model. Unblocks R9.2 brand filters + the diversity gate.
- **R9.6 stateful replay (item 6).** shadow_replay.py:160 replays each turn statelessly. Thread session
  case_id:turn so multi-turn corpus cases (explain_followup, budget-persist) are actually measured. This
  is WHY labeling waits on case:turn keys (review-7): case-only keys collide follow-up turns.

## PHASE R10 — operational readiness for canary. ~1-2 sessions.
- **R10.1 full TurnEnvelope in shadow jobs (P1.1).** facade `_enqueue_shadow` drops budget/session/image;
  add TurnEnvelope.to_dict/from_dict + worker rebuild so the shadow census matches production turns.
- **R10.2 tenant = cart identity (P0 residual).** draft_orders is still uid-only app-wide; the (tenant,uid)
  migration is platform debt that must land before multi-tenant canary.
- **R10.3 single-flight lease hardening (item 8).** _idem_single_flight ownership token + compare-and-delete
  so a slow producer's lease can't be stolen.
- **R10.4 CI-mandatory ratchets + core suites; Redis-Stream worker.** Make no-flavour / no-silent-except /
  brain / stages / cart suites blocking in CI; upgrade the shadow worker's list-queue to a Redis Stream
  (dead-letter, replay).
- **R10.5 currency USD/AUD normalization (item 9) — DEFERRED per "monetary-agnostic".** evidence.py:133
  budget filter compares cents with no currency check; latent while the demo is all-AUD. Do before any
  multi-currency merchant.

## PHASE R11 — soak → canary → primary → retire legacy.
shadow soak (0 queue loss, p95 in budget, quality gate green incl. labels) → RECOMMEND_CORE_MODE=canary:1
→ ramp → primary → retire suggest() + App.tsx cart regex + chat.py double-classifier + the internal HTTP
hop. Cart lane (RECOMMEND_CART_SERVE) rides the same ladder.

---

## Recommended immediate order
1. **R8.3 labels (YOU)** — start now, unblocks the last gate; everything else parallelizes.
2. **R8.1 empty-honesty + R8.2 accessory_bag + R8.4 stable re-run** — finish the honest measurement (me).
3. **R9.1 budget-persist** — smallest multi-turn win, fixes a named screenshot (30).
4. **R9.2–R9.4 FILTER/COMPARE/EXPLAIN executors + R9.5 brand + R9.6 stateful** — the real "smarter than
   legacy" milestone; biggest lever, biggest build.
5. **R10 ops + R11 soak/canary** once the gate is genuinely green (label-free AND labeled).

**Not on the path (deliberate):** currency (deferred), HDD-A9AE2F06 seed anomaly (classification correct,
no live impact), archiving suggest() (only at R11), lowering any threshold.
