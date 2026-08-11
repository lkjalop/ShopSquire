# Research Architecture — Wiring Roadmap

**Date:** 2026-08-07 · **HEAD:** `532ea387`
**Companion:** [SHOPSQUIRE_RESEARCH_TRIGGER_FINDINGS_2026-08-07.md](SHOPSQUIRE_RESEARCH_TRIGGER_FINDINGS_2026-08-07.md)

---

## The headline

The target architecture is **already built end to end** — utterance-act interpretation, bounded
semantic proposal, deterministic clamp, concurrent evidence fan-out, requirement compilation,
catalog authorization, and human-gated supplier RFQ.

Every stage of it hangs off one boolean, computed in seven lines, that is **`False` exactly when
the buyer needs the architecture most.**

```
plan.py:83-89     needs_concept = (validation == "valid") AND any(material concept)
                        |
core.py:894             if plan.needs_concept_resolution:      <-- master gate
                        |
        +---------------+-----------------+------------------+-------------------+
        v               v                 v                  v                   v
  evidence fan-out  semantic clamp  requirement compiler  catalog align   supplier RFQ
  core.py:930       core.py:948     core.py:959          core.py:1174    core.py:1195
```

For the screenshot query, `needs_concept` is `False`. All five stages are skipped. Ten gaming
laptops are returned by the ordinary catalog path, which never learns that anything was unresolved.

---

## Answer to "shouldn't it fan out in parallel, then spec, then check inventory, then RFQ?"

Yes. That is the design, and it is wired. Traced against the actual query
*"I need a laptop to simulate a cyber attack with a digital twin"*:

| Stage you described | Where it lives | State |
|---|---|---|
| Parallel search fan-out | [evidence_orchestrator.py:525](../src/app/services/evidence_orchestrator.py#L525) runs selected legs **concurrently**; bounded by `max_provider_fanout=3` ([research_contracts.py:105](../src/app/services/recommendation_core/research_contracts.py#L105)) and a 2000ms turn deadline ([research_contracts.py:107](../src/app/services/recommendation_core/research_contracts.py#L107)) | **Built** |
| "What *is* a digital twin / OT cyber range?" | `concept_discovery` capability; query strategy `identity` — observed live: *"…official definition scope"* | **Built, no provider** |
| "What hardware does it require?" | `official_requirements` capability; strategy `requirements` — observed live returning `ram >= 32GB`, `vram >= 8GB` | **Built + certified** |
| Recommended vs minimum specs | [requirement_compiler.py:31](../src/app/services/recommendation_core/requirement_compiler.py#L31) `compile_authoritative_requirements` — typed predicates, evidence source per predicate | **Built** |
| "What does inventory have?" | [core.py:1174](../src/app/services/recommendation_core/core.py#L1174) `align_catalog` → `exact` / `qualified` / `alternatives` / `no_exact_catalog_match`; unqualified SKUs are **filtered out** at [core.py:1194](../src/app/services/recommendation_core/core.py#L1194) | **Built** |
| "If not available, draft a supplier RFQ" | [core.py:1195-1204](../src/app/services/recommendation_core/core.py#L1195) `supplier_enquiry_option` — `auto_sent: False`, carries `evidence_refs` so the RFQ cites the requirements it was derived from | **Built, human-gated** |

So the harness exists. Three things are genuinely missing, and only the third is new work:

1. **The trigger** — none of the above runs (defects below).
2. **The discovery provider** — `concept_discovery` is only registered when
   `EXTERNAL_RESEARCH_SEARCH_URL` is set ([research_provider_registry.py:151](../src/app/services/research_provider_registry.py#L151)); the proof env sets only the
   requirements endpoint, so `endpoint_configured: false`. The live trace says so plainly:
   *"No configured provider: not configured for concept discovery."*
   Note the deliberate asymmetry at [line 162](../src/app/services/research_provider_registry.py#L162): the discovery provider is registered with
   `source_policy=None`, so it can generate **hypotheses but never requirements**. That is
   already the Tier-A/Tier-C split — keep it.
3. **Per-hypothesis fan-out.** Today the plan fans out per *concept* (identity + requirements
   for each unresolved span). Your question asks for fan-out per *competing interpretation* —
   OT/ICS cyber-range vs. 3D/Omniverse physical twin vs. cloud-hosted client. That is
   different, and it does not exist. The coverage abstention emits `workload_hypotheses: []`
   by design ([semantic_coverage.py:130](../src/app/services/recommendation_core/semantic_coverage.py#L130)) because deterministic code has no authority to invent
   interpretations — so hypotheses can only come from the model leg or from discovery
   research. This is the one genuinely new capability, and it should come **after** discovery
   is enrolled, because discovery is what populates the hypothesis set.

---

## The defect chain, in dependency order

### Defect 0 — a rejected proposal grants *more* authority than a valid one (NOT on the current roadmap)

[`plan.py:83-89`](../src/app/services/recommendation_core/plan.py#L83)

```python
needs_concept = bool(
    semantic.get("validation") == "valid"
    and any(... item.get("material") ... for item in (semantic.get("concepts") or []))
)
```

`needs_concept_resolution` requires a **valid** proposal. So:

| Proposal state | `needs_concept` | Clamp at core.py:894 | Outcome |
|---|---|---|---|
| valid + material concepts | `True` | runs | correctly blocked |
| `{"validation": "rejected"}` | `False` | **skipped** | products flow |
| `{}` (empty — case D) | `False` | **skipped** | products flow |

Meanwhile [`semantic_resolution.py:539-548`](../src/app/services/semantic_resolution.py#L539) opens with a fail-closed branch for exactly this
case — `outcome="rejected"`, `catalog_authority="blocked"`,
`state_prevented=("catalog_recommendation", "supplier_enquiry", "commerce_execution")`.

**That branch is dead code from the production path.** It can only be reached with a validation
result that `derive_plan` already refused to act on. The fail-closed guard was written, tested,
and then gated behind the success condition it was meant to catch.

This subsumes Defect 1: even after removing the `product_type_options` guard, a model proposal
that fails validation still skips the clamp.

### Defect 1 — product-category match suppresses the coverage check

[`turn_router.py:2423`](../src/app/services/recommendation_core/turn_router.py#L2423) — `if not product_type_options and not requirements and not raw_requirements and relationship != "run_on":`

Naming "laptop" disables the only backstop. Contradicts [`semantic_coverage.py:3`](../src/app/services/recommendation_core/semantic_coverage.py#L3).

### Defect 2 — observer has no null state

[`research_routing.py:78-79`](../src/app/services/recommendation_core/research_routing.py#L78) — empty proposal falls through to `else: state = "catalog_sufficient"`.

### Defect 3 — observer threshold structurally unreachable

Abstention pins `unresolved_ratio = n/2n = 0.5` and `hypothesis_ambiguity = 0` → score **0.425**
against a **0.45** threshold, for every n. Four of seven features are never populated by the only
call site ([core.py:543](../src/app/services/recommendation_core/core.py#L543)).

### Defect 4 — consent sentence contaminates purpose spans

[`semantic_coverage.py:15-18`](../src/app/services/recommendation_core/semantic_coverage.py#L15) `\bto\s+` matches inside *"I consent to that research"*.

### Defect 5 — discovery provider not enrolled

[`research_provider_registry.py:151`](../src/app/services/research_provider_registry.py#L151), needs `EXTERNAL_RESEARCH_SEARCH_URL`.

---

## Is the proposed roadmap correct?

**Directionally yes — the ordering, the TDD framing, and the "calibrate only after reachability"
discipline are all right.** Four corrections.

### Correction 1 — it is missing Defect 0, which is the actual root cause

The roadmap names `not product_type_options` but not `plan.py:83`. Fixing only the former leaves
the authority inversion intact for every rejected model proposal. **Fix `plan.py:83` first**; it
is the enforcement point, and it is what makes the invariants in the roadmap enforceable at all.

### Correction 2 — the invariants are proposed at the wrong layer

The roadmap says:

> Add an explicit `uninterpreted` observer state. Enforce invariants: `unresolved_workload`
> cannot recommend `catalog_first`; `uninterpreted` cannot authorize products.

The observer **cannot authorize or refuse anything**. It is declared non-authoritative in its own
schema — [`research_routing.py:25-27`](../src/app/services/recommendation_core/research_routing.py#L25): `mode: Literal["observer"]`,
`calibration_status: Literal["uncalibrated_shadow"]`, `authoritative: Literal[False]`. Its output
lands in `resp.extras` ([core.py:546](../src/app/services/recommendation_core/core.py#L546)) and is read by nothing that decides.

Enforcing "uninterpreted cannot authorize products" inside `research_routing.py` would be a test
that passes while the product stays broken. Split it:

- **Enforcement** → `plan.py:83` + `core.py:894`. Invariant: *products require positive
  interpretation evidence.* Absence of a valid proposal must route **into** the clamp, not around it.
- **Observation** → `research_routing.py`. Add `uninterpreted` for calibration data quality only.
  Keep `authoritative: False`.

Rule of thumb worth adopting: **if a state can be wrong without anything being blocked, it is
telemetry, not a gate.**

### Correction 3 — the green criterion hides Defect 3

> `-> research_candidate or consent_required`

Those come from two different subsystems. `consent_required` is the deterministic path
(`reduce_semantic_proposal` → `research_status`); `research_candidate` is the observer. Case E is
**already** `consent_required` today while the observer says `catalog_first`. The `or` makes the
test green with the observer still contradicting itself, and then item "calibrate QPP" inherits a
constant. **Assert both, separately.**

### Correction 4 — the biggest risk is over-abstention, and there is no negative battery

The `product_type_options` guard is almost certainly a **precision hack** compensating for a
coverage check that over-fires: `required = min(2, len(span_tokens))` with registry-vocabulary
overlap ([semantic_coverage.py:110-112](../src/app/services/recommendation_core/semantic_coverage.py#L110)). Remove the guard and every query with a `for X` /
`to X` span becomes an abstention candidate — *"a laptop for uni"*, *"a laptop for my daughter"*,
*"something to take to work"*.

That is the ShopTalk failure mode the research flagged: users answering refinement prompts with
*"stop asking me for specifics", "i'll just look thank you"*. Trading a silent misroute for an
interrogation is not a win.

`"ordinary university laptop"` is one case, and one case cannot measure a false-positive rate.
**Do not flip this guard blind.** Sequence it as a shadow change — the pattern already exists in
this codebase at [core.py:547](../src/app/services/recommendation_core/core.py#L547) (`workload_interpretation_shadow`):

1. Compute `unresolved_purpose_proposal` **unconditionally**, record under
   `resp.extras["coverage_abstention_shadow"]`.
2. Keep authority behind the existing guard for one iteration.
3. Replay the golden corpus + the 8 labelled slates. Measure abstention rate on queries that are
   *correctly* catalog-servable.
4. Flip the guard only when that false-positive rate is known and acceptable.

This costs one iteration and converts the roadmap's riskiest step into a measured one.

---

## Reordered roadmap

### Phase 0 — Freeze the evidence (do first, ~half a day)

Cases D/E/F from the findings doc, at three levels:

- **Unit** — `assess_research_trigger_shadow({})` must not return `catalog_sufficient`;
  `derive_plan` with a rejected proposal must set `needs_concept_resolution=True`.
- **API** — POST the two queries, assert `semantic_resolution.catalog_authority` and product count.
- **Playwright** — re-add as `frontend/e2e/unresolved-workload-abstention.spec.ts`, modelled on
  the passing `official-research-authorization.spec.ts`.

Add the two metrics now, so Phase 1 is measured rather than asserted:
**trigger reachability** (fraction of `unresolved_workload` observations recommending
`research_candidate` — currently **0%**) and **silent-misroute rate** (unresolved workload →
named persona with no abstention signal — currently **100%** for product-noun queries).

### Phase 1 — Make the clamp reachable (the screenshot fix)

1. **`plan.py:83`** — invert the condition. `needs_concept_resolution` should be true when the
   turn lacks positive interpretation evidence, not only when it has a valid proposal. Keep the
   valid+material case; add rejected and empty.
2. **`core.py:894`** — verify the clamp handles the new inputs. `reduce_semantic_proposal`
   already does ([semantic_resolution.py:539](../src/app/services/semantic_resolution.py#L539)); confirm `gather_evidence` tolerates an empty
   proposal without a provider call (it must not fan out on an uninterpreted turn — no query
   text to bound).
3. **`semantic_coverage.py:50`** — mask consent/instruction clauses before span extraction.
   Reuse the existing regex from [clarification_state.py:54](../src/app/services/clarification_state.py#L54) rather than writing a second
   one — a duplicated decision surface is the failure mode this codebase already documents.
4. **`research_routing.py:78`** — add `uninterpreted`; keep `authoritative: False`.
5. **`turn_router.py:2423`** — **shadow only this iteration** (Correction 4).

Green when: D ≡ E; consent never becomes a concept; ordinary queries unchanged; trigger
reachability > 0.

### Phase 2 — Re-scale the observer, then enroll discovery

6. Re-derive the score before any calibration: decouple `unknowns` from `concepts`, or populate
   `catalog_coverage` / `retrieval_confidence` at [core.py:543](../src/app/services/recommendation_core/core.py#L543), or lower the threshold.
   Any of the three; leaving it makes calibration fit a constant.
7. Enroll `concept_discovery` (`EXTERNAL_RESEARCH_SEARCH_URL` + allowlist). Keep
   `source_policy=None` on it. Extend the fixture at
   `tests/fixtures/fake_official_requirements_provider.py` to serve identity claims, then a real
   provider.
8. Revisit the **2000ms total deadline** ([research_contracts.py:107](../src/app/services/recommendation_core/research_contracts.py#L107)). It is sized for a
   localhost fixture. Two real providers over the network will not fit, and the failure mode is a
   silent empty leg — which now reads as "catalog sufficient". Raise it, or make research a
   continuation turn.

### Phase 3 — Flip the guard, on measurement

9. Review the shadow false-positive rate from Phase 1 step 5. Flip `turn_router.py:2423` if
   acceptable; otherwise tighten the coverage check ([semantic_coverage.py:110](../src/app/services/recommendation_core/semantic_coverage.py#L110)) first.
10. Two-stage triggering: semantic novelty (Phase 1) then weak catalog retrieval. The second
    stage is the QPP idea and needs `catalog_coverage` / `retrieval_confidence` from step 6.

### Phase 4 — Per-hypothesis fan-out (your parallel-search question)

11. Populate `workload_hypotheses` from discovery results, then fan out **one requirements query
    per surviving hypothesis** — OT/ICS vs. 3D-render vs. cloud-client — under the existing
    `max_provider_fanout` bound. [`compare_workload_hypotheses`](../src/app/services/semantic_resolution.py#L496) at semantic_resolution.py:496 and the
    ambiguity gate at [semantic_resolution.py:632](../src/app/services/semantic_resolution.py#L632) already consume this shape; they are
    currently starved of input.
12. Clarification by expected candidate reduction, selected over `material_slots` rather than the
    single fixed *"local, remote, or hybrid?"* question. The discriminating-unknown machinery at
    [semantic_resolution.py:627-632](../src/app/services/semantic_resolution.py#L627) is the natural place — it already computes
    `discriminating_unknown_ids`.

### Phase 5 — Unchanged from the current roadmap

13. Collect trigger/hypothesis labels; calibrate QPP. **Only after step 6.**
14. Shadow V2 against [nqe.py:88](../src/app/flows/nqe.py#L88) and the two decomposer calls
    ([core.py:1913](../src/app/services/recommendation_core/core.py#L1913), [turn_router.py:488](../src/app/services/recommendation_core/turn_router.py#L488)); remove named-title rules only after coverage.
15. Latency; seal the 8 relevance slates; IMAGE/voice proof; pilot + rollback; retire
    `/suggest` ([recommend_compat.py](../src/app/routers/recommend_compat.py)).

---

## Metric targets — amended

| Metric | Roadmap target | Amendment |
|---|---|---|
| Trigger reachability | 100% | Measure observer and deterministic path **separately** (Correction 3) |
| Silent misroute | 0% | Agreed; currently 100% for product-noun queries |
| Consent contamination | 0% | Agreed |
| Unnecessary research on ordinary queries | <5% | **Needs a negative battery before Phase 3, not after.** One case cannot measure a rate |
| Unsupported hard requirements | 0% | Already enforced — `validate_semantic_source_policy` ([semantic_resolution.py:394](../src/app/services/semantic_resolution.py#L394)) + `source_policy=None` on discovery. Add a regression so it stays true |
