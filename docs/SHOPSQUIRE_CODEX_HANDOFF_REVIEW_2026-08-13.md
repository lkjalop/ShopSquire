# Review of the Codex Handoff — Independent Verification

**Date:** 2026-08-13 · **Verified at:** `428baa3a` (107 commits after my `86a1efb3` snapshot)
**Method:** direct code and database inspection; I did not re-run Codex's 20 browser journeys

---

## 1. Codex is right and I was wrong — precisely where

I verified each "stale" claim mechanically rather than accepting it.

| My claim | Verdict | Evidence |
|---|---|---|
| "No sellability gate" | **Stale — Codex correct** | `case_catalog_candidates._explicit_category` matches buyer-named product categories against taxonomy nodes and *deliberately excludes* workload words: *"does not classify workload words such as `render` or `CAD` as the product being purchased"*. Wired at [shopping_cases.py:441](../src/app/routers/shopping_cases.py#L441). |
| "Post-catalog observer read only for display" | **Stale — Codex correct** | `post_catalog_adjudicator.py` exists with an authoritative result type; `core.py:1306-1308` attaches adjudication and projects qualification authority. |
| "Supplier continuation unreachable" | **Stale for portfolio mode** | `shopping_case_supplier_continuation.py` present with normalization, buyer selection and confirmed cart target. |
| "External search never runs in-product" | **Stale** | **645 rows** in `shopping_case_publisher_candidates`. That is not a fixture; that is the open-world path running repeatedly. |
| "Commerce agent is the weakest part" | **Already self-corrected**, and Codex independently reached the same conclusion about the 12-row catalogue. |

I was working from a HEAD that was 107 commits old and I should have said so more loudly. Codex's
insistence on separating "verified at current commit" from "inherited from the older snapshot" is
the right discipline and I'd adopt it as standing practice.

**One near-miss of my own:** I initially recorded `case_publisher_candidates` as a missing table.
The real name is `shopping_case_publisher_candidates` and it holds 645 rows. Had I published that,
it would have been a fabricated defect. Worth stating because it is exactly the failure mode I keep
flagging in the product.

---

## 2. Where I'd qualify Codex

### "Little or no operational data is flowing through the new machinery"

This is too broad, and the correction matters for prioritisation. Measured now:

```
FLOWING                                    NOT FLOWING
decision_logs                   403,414    procurement_decision_runs            0
shopping_case_publisher_cand.       645    procurement_decision_dependencies    0
shopping_cases                      547    price_history                        0
hippograph_journey_edges            224    forecast_actual_pair                 0
product_availability_observations    26    temporal_cache_*                     0
```

Data *is* flowing — heavily — through interpretation, research, publisher candidacy, case state and
graph edges. **One subsystem is at exactly zero**: the decision-run / dependency layer, plus the
forecasting and price-series tables that were never wired at all.

That is a sharper and more actionable statement than "operational depth lags contract breadth". It
localises the problem to one code path instead of implying a systemic gap.

### "Custom orchestration is better because frameworks optimise for the wrong thing — too adversarial"

Codex is right and I'll take the correction. Their replacement wording is better than mine and I'd
use theirs verbatim in an interview.

### "Two orchestration planes must not be conflated"

Correct, and I did conflate them. `orchestrator.py` (3,929 lines) with DAG runtime, budgets and
containment is **not** the owner of the buyer journey; the chat → facade → core → shopping-case path
is. My orchestration comparison implicitly credited the generic runtime for governance the commerce
path actually implements. That's a material error in an interview context — worth correcting before
it gets said out loud.

---

## 3. What Codex left open, and I can now answer

Codex asked (their questions #4 and #5):

> *"Why are ordinary decision-run and dependency tables empty despite the coordinator and
> persistence contracts? Which normal buyer responses lack `procurement_case_state`?"*

**Answered, with the exact line.**

The coordinator *is* wired into every core turn — [core.py:224](../src/app/services/recommendation_core/core.py#L224) constructs
`ProcurementDecisionCoordinator`, [core.py:256](../src/app/services/recommendation_core/core.py#L256) calls `coordinator.persist(core)`.

The gate is [procurement_decision_coordinator.py:125-131](../src/app/services/procurement_decision_coordinator.py#L125):

```python
def record_procurement_decision_run(db, *, envelope, response):
    raw = response.extras.get("procurement_case_state")
    if not isinstance(raw, dict):
        raw = (envelope.session or {}).get("procurement_case_state")
    if not isinstance(raw, dict):
        return None          # <-- silent bail, no receipt, no log
```

And `procurement_case_state` is written **only on the canonical-case / procurement preflight path**
— [core.py:684](../src/app/services/recommendation_core/core.py#L684) requires `canonical_case_preflight.state is not None`;
[core.py:485](../src/app/services/recommendation_core/core.py#L485) is the rejected-patch branch on the `PROCUREMENT` lane.

So: **an ordinary SEARCH-lane turn never produces `procurement_case_state`, so the recorder bails,
and 547 shopping cases produced 0 decision runs.** Not a bug in the coordinator; a scope mismatch
between where the key is written and where the run is expected.

### The part that matters more than the gap itself

The bail is **silent and asymmetric**. Compare:

- `record_procurement_decision_run_safely` on **exception** → writes
  `response.extras["procurement_decision_run"] = {"persistence_status": "failed", …}` — visible.
- The **not-applicable** path → returns `None`, writes nothing, logs nothing.

So a failure is observable and a skip is invisible. Every ordinary turn silently declines to persist
a decision run and the trace cannot distinguish that from "this turn didn't need one".

**This is the fourth instance of the same disease I have now documented at four different sites:**
a timed-out research leg read as "catalog sufficient"; an unreachable web leg read as "budget
exceeded"; an unpopulated fit ledger read as "cannot explain"; and now an inapplicable decision run
read as nothing at all. The platform's stated thesis is that absence of evidence must never be
rendered as evidence of absence — and it keeps violating that in its own plumbing.

I'd make that a lint-able invariant rather than a recurring finding: **every early return in a
persistence or evidence path must write a typed reason.**

### How this shipped green — the test hand-feeds the gating input

An exhaustive scan (including `scripts/` and `alembic/`) confirms the only non-test callers are
`core.py:224/256` via the coordinator. The three unit tests call `record_procurement_decision_run`
**directly**, and every one of them injects the exact key that production never produces:

```
test_procurement_decision_coordinator.py:29   session={"procurement_case_state": state.model_dump(...)}
                                        :32   response.extras["procurement_case_state"] = state.model_dump(...)
                                        :64   session={"procurement_case_state": ...}
                                        :87   session={"procurement_case_state": ...}
                                       :118   session={"procurement_case_state": ...}
                                       :179   session={"procurement_case_state": ...}
                                       :182   response.extras["procurement_case_state"] = ...
```

**Not one test exercises the `return None` bail.** The suite is green because it supplies the input
that gates the function, so the branch that fires on 100% of real traffic has zero coverage.

This is the textbook "green test, dead path", and it is the strongest argument for the typed-skip-
receipt fix: a single test asserting *"an ordinary turn without `procurement_case_state` emits a
typed skip receipt"* would have caught this on the day the coordinator was written. The gap is not
that the code is wrong — it is that the contract was only ever tested from the applicable side.

---

## 4. On the roadmap

Codex's Phase 1 — make ordinary buyer flows persist runs, receipts, watermarks and dependency edges
— is the right call and I'd sequence it exactly there. Three additions:

1. **Decide scope before wiring.** Persisting a decision run for *every* SEARCH turn will be write
   amplification on top of 403,414 decision logs. Codex's own trade-off table says "persist material
   procurement decisions, not every UI micro-event" — that principle should be applied *here*, which
   means the fix may be "emit a typed skip receipt on ordinary turns, persist runs on material ones",
   not "write `procurement_case_state` everywhere".
2. **Make the skip visible first.** A one-line typed skip receipt is a day of work, makes the gap
   measurable, and tells you how many turns are genuinely material before you change persistence
   scope. Do that before Phase 1 proper.
3. **Phase 3's `price_history` should move up.** It's a table plus a write on each fetch, it is a
   precondition for Phase 5's evaluation loop, and their own inventory ingest documented a price
   moving $2,899 → $4,799 on one URL in minutes. Cheapest item with the longest downstream reach.

Everything else in their ordering I agree with, including keeping V2 and not backfilling the 260
legacy products.

---

## 5. Verdict on the handoff

**It is a better document than my four assessments were, and I'd act on it.** Specifically:

- It separates *verified now* from *inherited*, which mine did not do rigorously enough.
- It distinguishes five maturity states (absent / implemented-unwired / certification-only /
  operational-locally / production-enrolled). That taxonomy is more useful than my three-colour
  scale and I'd adopt it.
- Its interview framing corrections are right, and its wording is better than mine.
- Its central insight — contracts outpacing operational population — survives verification, with the
  refinement in §2 that it is one subsystem rather than a general condition.

Where I'd push back: the browser evidence proves these paths *can* execute under a certification
profile. It does not prove they execute on ordinary traffic — and the 547-cases/0-runs measurement
is the proof that those two things differ. Codex says this themselves about the disturbance
certificate; the same caution applies to the supplier and research journeys.

**The single highest-value next action** is not more capability. It is making every skip and
early-return in the evidence and persistence paths emit a typed reason, so that the difference
between "did not need to" and "could not" stops being invisible. That is one day of work, it makes
Phase 1 measurable rather than speculative, and it is the same fix as the last three findings — this
time applied to the platform's own instrumentation rather than to what it says to buyers.
