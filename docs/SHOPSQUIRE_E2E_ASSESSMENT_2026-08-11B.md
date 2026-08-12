# E2E Assessment #2 — Personas, Bulk × Deadline, Escalation, SearXNG

**Date:** 2026-08-11 · **HEAD:** `e657c157` · **Method:** 12 live browser journeys, no code changed
**Runtime:** demo_v2 · core primary · **ready: True, mismatches: []** · worktree **clean (0 dirty)**
**Prior:** [E2E #1](SHOPSQUIRE_E2E_ASSESSMENT_2026-08-11.md)

---

## 0. Delta since assessment #1

| Prior finding | Status |
|---|---|
| 🔴 D1 bulk refusal regex | **FIXED** — [App.tsx:1687](../frontend/src/App.tsx#L1687) now calls `isUnsupportedPostPurchaseTracking(q)` (named predicate requiring a post-purchase anchor) instead of the bare `\bwhen\b…\barrive\b` alternative |
| 🟡 D11 runtime not ready | **FIXED** — `ready: True`, `mismatches: []` |
| 🟡 worktree 192–205 dirty | **FIXED** — 0 dirty, all committed |
| SearXNG CAPTCHA fragility | **FIXED** — `12e18d67` enrolled engine profile; live probe now **30 results, `unresponsive_engines: []`** |
| 🔴 D2 clarification deadlock | **NOT FIXED** — now the master blocker |
| 🔴 D3 unavailable ranks first | **NOT FIXED** |
| 🟠 D5 shelves don't discriminate | **NOT FIXED** — now provable at 6/6 |

Also new and good: `de144887` persists per-engine reliability observations
([`discovery_engine_reliability.py`](../src/app/services/discovery_engine_reliability.py)); `0ba34236` quarantines untrusted supplier responses;
`20da4154` certifies unreachable-discovery degradation; `fab67fdb` certifies supplier wait/split/cancel
paths; chat payload now carries `delivery_feasibility` and `human_escalation`
([suggest_contract.py:117](../src/app/contracts/suggest_contract.py#L117)).

---

## 1. Six personas — 6/6 return the identical shortlist

All six ran clean, ~3s each (cache hits), all `Provisional — external research not yet authorized`.

| Persona | Rank 1 | Rank 2 | Rank 3 |
|---|---|---|---|
| digital-twin / breakdown prediction | MSI Titan 18 HX $8,999 | HP ZBook Fury $14,999 | HP Z2 Mini $3,699 |
| CGI, no overnight renders | *identical* | *identical* | *identical* |
| CAD, large 3D + point clouds | *identical* | *identical* | *identical* |
| PLC factory + OT cyberattack | *identical* | *identical* | *identical* |
| BIM + real-time walkthroughs | *identical* | *identical* | *identical* |
| Unreal Engine Nanite/Lumen | *identical* | *identical* | *identical* |

**Byte-identical, same order, six semantically distinct workloads.** Ranking does not consume the
workload at all. Note this is *worse* than it looks: the hypothesis shelves are correctly *labelled*
per interpretation, then populated from the same unranked pool.

Good news inside it: the shortlist is now workstation-class and reaches $14,999 — the new inventory
is being retrieved, which it wasn't in assessment #1.

---

## 2. Bulk × deadline — the entire dimension is unreachable

| Qty | Deadline | Result |
|---|---|---|
| 40 | today (impossible) | research question, `(no panel)` |
| 40 | in 3 days | *identical* |
| 50 | in 5 days | *identical* |
| 60 | in 7 days (reasonable) | *identical* |
| 60 | by tomorrow (impossible) | *identical* |

Every combination returns the byte-identical string:

> *"This request needs current external requirements before I can qualify products. May I check
> approved official sources?"*

**No deadline was evaluated. No feasibility verdict. No shortfall. No RFQ. No escalation.**
Reasonable and impossible deadlines are indistinguishable in output.

Second defect visible in turn 1 of each: *"I need laptops for a factory rollout"* →
*"These all handle **general**, starting at $629"* + *"For **office**, which level fits?"* — a factory
rollout snapped to office/general, contradicting the persona runs which produced workstations for
similar language.

### The escalation machinery exists and is correct

[`core.py:2087-2100`](../src/app/services/recommendation_core/core.py#L2087):

```python
resp.extras["fulfillment_options"] = augment_deadline_alternatives(..., promise=deadline)
if deadline["feasibility"] != "met":
    from src.app.services.operator_escalation import build_operator_escalation
    resp.extras["human_escalation"] = build_operator_escalation(
        reason="deadline_confirmation_required", ...)
    deadline_text = (f"I cannot confirm all {int(quantity)} within the {int(horizon_days)}-day "
                     "window: inventory location is known, but date-qualified transfer and carrier …")
```

Plus [`promise_feasibility.py:17`](../src/app/services/promise_feasibility.py#L17) `evaluate_promise_feasibility` and `:100`
`evaluate_critical_path`. The escalation journey's trace confirmed `EXECUTION: Not executed`,
Commercial Journey empty — the code is never entered.

**This is the whole story: the commercial and escalation layer is built and looks right, and one
relation-classification bug makes it unreachable from chat.**

---

## 3. Root cause of D2, exactly

[`turn_router.py:2216-2225`](../src/app/services/recommendation_core/turn_router.py#L2216):

```python
raw_clarification_relation = str(data.get("clarification_relation") or "none").strip().lower()
clarification_relation = (
    raw_clarification_relation
    if raw_clarification_relation in {"answer", "interrupt", "supersede", "ambiguous"} and pending
    else "none"
)
if clarification_relation == "supersede" and _is_bounded_semantic_continuation(envelope.query):
    clarification_relation = "answer"
```

The relation is taken from the **model** (prompt at [:1527](../src/app/services/recommendation_core/turn_router.py#L1527)). For
*"I need 60 units delivered today"* arriving while a yes/no research-consent question is pending, the
model returns `answer`. Downstream, [`chat.py:3539-3541`](../src/app/routers/chat.py#L3539) consumes the pending question and
re-emits it, and the quantity/deadline are discarded.

**A turn carrying a bounded quantity or an explicit deadline cannot be an answer to a yes/no consent
question.** That is decidable deterministically, and the codebase already does exactly this kind of
clamp on the line above (`supersede` → `answer` when the query is a bounded continuation). The fix is
the inverse clamp, in the same place, in the same style.

---

## 4. Unavailable-first ranking (D3) persists

Assessment #1 observed rank 1 = `HP Z2 Mini, unavailable, network stock: 0`. This run the top three
are workstation-class but availability is still only *rendered*
([`ProductShelvesPanel.tsx:140`](../frontend/src/components/ProductShelvesPanel.tsx#L140)), never *ranked on*. For 40–60 unit orders a zero-stock
rank-1 is a wrong answer, not a ranking nuance.

---

## 5. SearXNG — resolved

```
q="Unreal Engine Nanite Lumen system requirements"  ->  30 results, unresponsive_engines: []
```

The CAPTCHA fragility from 2026-08-09 is gone. Two things fixed it: the enrolled engine profile
(`12e18d67`, mojeek/bing rather than the Google-proxying default mix) and the Tier-0 evidence cache
(persona runs completed in ~3s with `dispatched: 0`).

`discovery_engine_reliability.py` now persists `(endpoint, engine, outcome, latency_ms)` with bounded
retention — the right instrument. **What's missing is using it:** an engine with a recent failure
streak should be deprioritised automatically, and the observation window should surface in the trace
next to the Tier-4 rung.

---

## 6. Not exercised

Human↔human override could not be mocked: the buyer never reaches an escalation, so there is nothing
in the admin queue to approve or reject. The endpoints exist —
[`fulfillment_cases.py:1331`](../src/app/routers/fulfillment_cases.py#L1331) `/cases/{case_id}/request-approval`,
[`:1054`](../src/app/routers/fulfillment_cases.py#L1054) `/supplier-events`, [`:792`](../src/app/routers/fulfillment_cases.py#L792) `/cases/confirm-cart`,
[`:1433`](../src/app/routers/fulfillment_cases.py#L1433) `/cases/{case_id}/supplier-info` — and `/supplier-events` is the natural injection
point for a mock supplier accept/reject. Blocked entirely by D2.

---

## 7. Roadmap

### C1 — `fix(router): treat commercial obligations as clarification interrupts` 🔴

**Files**
- [`turn_router.py:2224`](../src/app/services/recommendation_core/turn_router.py#L2224) — add the inverse clamp beside the existing `supersede`→`answer` one:
  if `relation == "answer"` and the turn carries a bounded quantity, an explicit deadline, or a
  supplier/escalation verb, force `interrupt`.
- [`chat.py:3539-3541`](../src/app/routers/chat.py#L3539) — on `interrupt`, suspend rather than consume the pending question.
- [`clarification_state.py:137-146`](../src/app/services/clarification_state.py#L137) — `replacement_root_query` must not concatenate the
  pending question text into `retained_purpose` (source of the "Buyer clarification to '…'" purpose
  corruption seen in #1).

**TDD**
```
tests/services/test_clarification_relation_clamp.py
  test_quantity_bearing_turn_is_interrupt_not_answer
  test_explicit_deadline_turn_is_interrupt_not_answer
  test_supplier_verb_turn_is_interrupt_not_answer
  test_plain_yes_still_classifies_as_answer          # no regression on real consent
  test_pending_question_survives_interrupt
  test_retained_purpose_excludes_pending_question_text
```
Red first: assert `interrupt` on "I need 60 units delivered today" with a pending consent question.

**Green gate:** bulk 40/50/60 × {today, 3d, 5d, 7d} each produce a distinct feasibility verdict.

---

### C2 — `feat(fulfillment): surface deadline feasibility and escalation in chat` 🔴

Machinery exists; wire it to the surface.

**Files**
- [`core.py:2087-2100`](../src/app/services/recommendation_core/core.py#L2087) — confirm `human_escalation` + `fulfillment_options` reach the payload.
- [`suggest_contract.py:117`](../src/app/contracts/suggest_contract.py#L117) — already lists both keys; assert they are non-null when
  `feasibility != "met"`.
- [`promise_feasibility.py:17`](../src/app/services/promise_feasibility.py#L17), [`:100`](../src/app/services/promise_feasibility.py#L100) — verdicts for same-day / 3d / 5d / 7d.
- **Frontend:** render `delivery_feasibility` and `human_escalation` in the right panel; today
  neither has a renderer.

**TDD**
```
tests/services/test_promise_feasibility_matrix.py
  test_same_day_60_units_is_infeasible_with_reason
  test_seven_day_40_units_is_met_when_transfer_covers
  test_infeasible_emits_human_escalation_deadline_confirmation_required
  test_feasibility_never_promises_without_carrier_evidence
frontend/e2e/bulk-deadline-feasibility.spec.ts
  assert distinct verdict text per deadline; assert escalation card renders
```

---

### C3 — `fix(ranking): availability is a ranking term` 🔴

**Files**
- shelf reducer feeding [`ProductShelvesPanel.tsx:140`](../frontend/src/components/ProductShelvesPanel.tsx#L140) — zero verified network stock must
  not hold rank 1 without an explicit `sourcing required` label + lead time.
- Keep the SKU visible (stretch-slate principle); demote it, don't hide it.

**TDD**
```
tests/services/test_shelf_availability_ranking.py
  test_zero_stock_sku_never_rank_one_unlabelled
  test_zero_stock_sku_remains_visible_with_sourcing_label
  test_available_sku_outranks_unavailable_at_equal_fit
  test_bulk_quantity_beyond_stock_marks_shortfall_not_available
```

---

### C4 — `feat(ranking): discriminate shelves by hypothesis` 🟠

Six personas → one shortlist is the most visible quality defect.

**Files**
- [`case_research_plan.py:117-162`](../src/app/services/case_research_plan.py#L117) — hypothesis labels already exist per shelf.
- Shelf reducer — rank *within* a hypothesis using that hypothesis's requirement floor, not the
  shared pool.
- [`core.py:1174`](../src/app/services/recommendation_core/core.py#L1174) `align_catalog` — feed per-hypothesis predicates.

**TDD**
```
tests/services/test_hypothesis_shelf_discrimination.py
  test_six_personas_do_not_produce_identical_top_three   # the regression that caught this
  test_gpu_heavy_hypothesis_ranks_discrete_gpu_above_integrated
  test_virtualisation_hypothesis_ranks_ram_ceiling_above_vram
```

---

### C5 — `fix(gates): suppress contradictory clarifiers` 🟠
[`gates.py:41-48`](../src/app/services/recommendation_core/gates.py#L41) — add `has_selection` / `cart_non_empty`; return `None` when either
is true. Also fixes "factory rollout → office/general" over-generalisation surfacing as a budget ask.

```
tests/services/test_slot_gap_clarify_guards.py
  test_no_budget_question_when_shortlist_present
  test_no_no_match_claim_when_cart_non_empty
```

---

### C6 — `feat(discovery): consume engine reliability observations` 🟡
[`discovery_engine_reliability.py`](../src/app/services/discovery_engine_reliability.py) records but nothing reads it. Deprioritise an engine after a
failure streak; surface the window on the Tier-4 rung.

```
tests/services/test_discovery_engine_reliability_policy.py
  test_engine_with_failure_streak_is_deprioritised
  test_recovered_engine_is_restored_after_success_window
  test_trace_reports_engine_health_window
```

---

### C7 — `test(procurement): mock supplier accept/reject through the human gate` 🟡
Unblocked by C1+C2. Drive buyer → shortfall → RFQ draft → `/supplier-events` mock accept and mock
reject → assert `AWAITING_APPROVAL` persists on escalate and no state changes without the human.

```
tests/integration/test_supplier_human_gate.py
  test_mock_supplier_rejection_leaves_case_awaiting_approval
  test_mock_supplier_confirmation_requires_human_before_cart_apply
  test_rfq_body_passes_claim_safety_for_impossible_deadline   # no promise leaks
  test_admin_override_is_recorded_with_actor_and_reason
frontend/e2e/supplier-continuation.spec.ts
```

---

### C8 — `chore(catalog): backfill category, dedupe, add mpn` 🟡
From #1: 170 NULL categories, 38 duplicate name groups, no `mpn` column. Re-verify post-`e657c157`
("reconcile exact showcase OEM identities") before sizing.

---

### Commit order

```
C1  fix(router): treat commercial obligations as clarification interrupts   <- unblocks everything
C2  feat(fulfillment): surface deadline feasibility and escalation in chat
C3  fix(ranking): availability is a ranking term
C4  feat(ranking): discriminate shelves by hypothesis
C5  fix(gates): suppress contradictory clarifiers
C6  feat(discovery): consume engine reliability observations
C7  test(procurement): mock supplier accept/reject through the human gate
C8  chore(catalog): backfill category, dedupe, add mpn
```

**C1 alone makes assessments #1 and #2 re-runnable.** Everything after it is measurable; before it,
nothing in the commercial half of the product can be observed from the buyer surface.

### Per-commit gate (keep the existing discipline)

```
unit contract        GREEN
service reducer      GREEN
adversarial critic   GREEN
API integration      GREEN
browser journey      GREEN
trace assertions     GREEN
zero unexpected provider calls
```

---

## 8. Verdict

The evidence layer is genuinely finished work: the ladder is honest, SearXNG is stable at 30 results
with zero unresponsive engines, the cache makes repeat runs free and ~3s, engine reliability is being
recorded, supplier responses are quarantined, and the worktree is clean with `ready: True`.

The commercial layer is *also* built — feasibility, escalation, RFQ send-cage, supplier events, human
gate — and **none of it can be reached from chat** because one model-supplied relation label is
believed without a deterministic clamp. That single line is currently the difference between a
procurement platform and a product search box.
