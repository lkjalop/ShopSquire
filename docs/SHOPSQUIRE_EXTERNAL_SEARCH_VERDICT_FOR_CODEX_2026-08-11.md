# External Search — Does It Actually Work? Verdict for Codex

**Date:** 2026-08-11 · **HEAD:** `e657c157` · **Method:** 3 novel-workload journeys, live, no code changed
**Runtime:** demo_v2 · core primary · ready True · SearXNG 30 results / 0 unresponsive

---

## 1. Answer in one line

**External search works excellently inside a 31-item enrolled vocabulary and is effectively
deterministic. Outside that vocabulary it does not degrade — it silently returns gaming laptops
labelled "Authorized recommendation."**

---

## 2. Why the earlier persona test proved nothing

The six personas I ran (digital twin, CGI, CAD/point-cloud, OT cyber range, BIM, Unreal) all
completed in ~3s. That looked like speed. It was **coverage**.

[`config/official_workload_sources.json`](../config/official_workload_sources.json) enrols 31 workload tokens:

```
3d_modelling, ai_fine_tuning, autocad, bim, blender_rendering, cgi, cyber_range,
digital_twin, factory_io, game_development, ics_security_simulation, isaac_sim,
large_3d_models, large_bim_models, local_3d_physics, lumen, manufacturing_digital_twin,
nanite, network_simulation, nolvus, omniverse, ot_cyber_range, peft, plc_simulation,
point_cloud, predictive_maintenance, revit, robotics_simulation, skyrim_modding,
unreal_engine, virtualisation
```

Every one of my six personas maps onto that list. I was testing the cache, not the search.
**ChatGPT's five scenarios are all outside it** — which makes them the correct stress test, and I
ran three of them.

---

## 3. Results — three novel workloads

| Test | Turn 1 | Observer | Research offered? | Outcome |
|---|---|---|---|---|
| **N1** drone photogrammetry / GIS | 11.1s | `uninterpreted material`, score 0.425, `research candidate` | **yes** | consent click **hung 120s** (my timeout) |
| **N2** FEA/CFD, vendor-certified only | 25.9s | `catalog sufficient`, score **0** | **no** | 10 gaming laptops, *"Authorized recommendation"* |
| **N3** 8K RAW video + colour | 24.4s | `catalog sufficient`, score **0** | **no** | 2× duplicate Legion Pro 7 $5,999, *"Authorized recommendation"* |

### N2 is the most serious result in this whole series

The buyer said: *"our engineering team only wants hardware **officially supported by the software
vendor**… Is this **gaming laptop** actually suitable?"*

The platform answered:

```
Found 10 products
Authorized recommendation
  Alienware 16 Aurora  RTX 5060   $3,499
  MSI Thin A15         RTX 3050   $1,799
  Asus TUF F16         RTX 5060   $2,899
"Top gaming options are Alienware 16 Aurora … and MSI Thin A15 (RTX 3050)."

Trace: No bounded workload entity was proposed.
       State: catalog sufficient · Score: 0 · Recommendation: catalog first
       Deterministic authorization: not run · Prevented: none recorded
```

An explicit ISV-certification constraint was ignored, the buyer's own scepticism about gaming
laptops was answered with more gaming laptops including an RTX 3050, and nothing was gated. Note
this is **worse than the original screenshot-59 failure**: that one said *provisional*; this says
*Authorized recommendation* and *Prevented: none recorded*.

N3 reproduces ChatGPT's predicted failure verbatim: *"I do not care about gaming FPS"* → the two
most expensive gaming laptops in the catalogue, duplicated.

---

## 4. Root cause — the signal exists and is discarded

Two observers run per turn.

**Pre-catalog** ([`core.py:543`](../src/app/services/recommendation_core/core.py#L543)) — sees only the semantic proposal. On N2/N3 the model
proposed nothing, so score 0 → `catalog sufficient`. This is the observer that gates.

**Post-catalog** ([`core.py:1265`](../src/app/services/recommendation_core/core.py#L1265)) — sees retrieval reality:

```python
resp.extras["research_trigger_post_catalog_shadow"] = assess_research_trigger_shadow(
    plan.semantic_proposal,
    catalog_coverage=(qualified_count / max(1, retrieval_count)),
    retrieval_confidence=(len(resp.products) / max(1, retrieval_count)),
    unknown_attribute_ratio=(unknown_requirement_count / possible_requirement_count),
    ...)
```

It computed **`catalog coverage gap: 0.8667`** on N3 and **0.375** on N2 — and it is read by exactly
one caller: [`trace_ontology.py:159`](../src/app/services/recommendation_core/trace_ontology.py#L159), to *render* it.

**The system measures that the catalogue can't serve the query, displays that measurement, and lets
the turn through anyway.** The pre-catalog observer, which saw nothing, is the one with authority.

That is the whole defect. It is one feedback edge.

---

## 5. Is it "mostly deterministic"? Yes — and be precise about it

| | Enrolled (31 tokens) | Novel |
|---|---|---|
| Path | cache → canonical entrypoint | model interpretation only |
| Latency | ~3s | 11–26s |
| Network | `dispatched: 0` | 0 (never reaches discovery) |
| Cost | £0 | £0 |
| Honesty | excellent | **absent** |
| Discovery actually exercised | no | no |

**In the running product, live discovery has not fired once across every journey I have run.** It
works in `scripts/certify_live_external_research.py` (verified: SearXNG → docs.factoryio.com, 200,
free) but no buyer turn has reached Tier 4. Enrolled queries short-circuit at Tier 0/1; novel
queries never get there.

So the honest framing for Codex: **this is a curated-corpus system with a discovery capability that
is built, certified in isolation, and unreached in production.** That is a defensible product — it
is not the same claim as "the platform searches the web."

---

## 6. Degradation UX — what exists and is genuinely good

N1's path is the good one, and it should be the universal floor:

```
Purpose retained verbatim
State: uninterpreted material          <- the null class, shipped
Recommendation: research candidate      Score 0.425
Bounded research plan
  concept identity for X via concept discovery
  recommended requirements for X via official requirements
  prohibited: unverified vendor, unverified product, invented hardware floor
Material slots: local / remote / hybrid? — unresolved
Governed provider search: consent required
External provider calls: 0 · Internal effort: 3 / 8
Deterministic authorization: BLOCKED
  Prevented: catalog recommendation | supplier enquiry | commerce execution
Four doors: [Research approved sources] [Upload requirements]
            [Use official link or vendor] [Enter specifications]
```

That is a good user experience under failure: nothing fabricated, the gap named, four routes
forward, three of them free. The effort budget is also fixed — `3 / 8`, renamed from "cost", so the
old `web (5) > max 3` unreachability is gone.

**The problem is not that degradation is bad. It is that N2 and N3 never enter it.**

Two remaining UX gaps on the good path:
- N1's consent click **hung for 120s** — `Turn deadline: 2000ms` is a *lane* budget; nothing bounds
  the user-visible wait, and there is no progress or timeout affordance.
- Badges still over-claim: `FRESHNESS: Current` / `AUTHORITY: Platform authorized` on a turn whose
  own body says `No bounded workload entity was proposed`.

---

## 7. Research tab assessment

**Strong.** It is the best artifact in the product. It renders, per turn: model interpretation and
material unknowns; both shadow observers with score, state and named reasons; the bounded research
plan with the literal planned queries and their prohibited-assumption lists; material slots; the
governed provider search with consent state; provider-call and paid-call counters; internal effort
as `used / budget`; evidence-to-requirement compilation status; and deterministic authorization with
an explicit `Prevented:` list. Plus the Tier 0–6 evidence ladder with per-rung execution status and
billing class.

Four fixes:
1. **The two observers can contradict each other** and the panel shows both without adjudication
   (N3: `catalog sufficient / score 0` beside `coverage gap 0.8667`). Show which one gated.
2. **`Paid calls: not recorded`** should be `0`. "Not recorded" undermines the cost claim that the
   ladder exists to prove.
3. **No engine health on the Tier-4 rung** — [`discovery_engine_reliability.py`](../src/app/services/discovery_engine_reliability.py) records
   `(endpoint, engine, outcome, latency_ms)` and nothing surfaces it.
4. **Badge honesty**, as above.

---

## 8. ChatGPT's five tests — all doable, and well-chosen

| # | Test | Runnable today? | What it would catch now |
|---|---|---|---|
| 1 | Photogrammetry/GIS scale ambiguity | **Yes** | Abstains correctly, then hangs 120s on consent |
| 2 | FEA/CFD certification vs horsepower | **Yes** | **Fails hard** — "Authorized recommendation", RTX 3050 |
| 3 | Five-year fleet, no single requirements page | **Yes** | Untested; needs multi-obligation decomposition, likely `catalog sufficient` |
| 4 | 8K video, compute vs display accuracy | **Yes** | **Fails hard** — two duplicate $5,999 gaming laptops |
| 5 | Secure 30-unit lab, 2 days | **Partly** — the deadline half is blocked by the clarification-interrupt defect (C1 in the prior roadmap) | Would test PSIRT/KEV/Linux-cert fan-out, none enrolled |

His framing is correct on every count. Two additions:

- **Adopt his rule as a hard gate.** *"At least one test must cause the most expensive laptop to
  lose."* Today N3 makes it win on a query that explicitly disclaims gaming. Make it
  `test_most_expensive_sku_loses_on_at_least_one_persona` and run it in CI.
- **Tests 2, 3 and 5 need sources that are not enrolled** (ISV certification matrices, OS lifecycle,
  Linux certification, vendor PSIRT, NVD/CISA KEV). They will therefore exercise Tier 3/4 for the
  first time. Expect them to expose the discovery path that has never run in-product — which is
  exactly what you want before shipping.

His per-attribute verdict idea is the right output shape and nothing today produces it:
`COMPUTE: STRONG · DISPLAY ACCURACY: UNKNOWN` rather than one blended verdict.

---

## 9. What to tell Codex — ordered

**R1 🔴 Feed the post-catalog observer back into the gate.**
[`core.py:1265`](../src/app/services/recommendation_core/core.py#L1265) → the authorization decision. A high coverage gap or zero qualified
products must be able to demote `catalog sufficient` to `uninterpreted material`, even when the
model proposed nothing. *One feedback edge; catches N2 and N3.*
```
tests/services/test_post_catalog_gate_feedback.py
  test_high_coverage_gap_demotes_catalog_sufficient
  test_zero_qualified_products_blocks_authorized_label
  test_low_coverage_gap_still_permits_catalog_first    # no over-abstention regression
```

**R2 🔴 "Authorized recommendation" requires positive evidence.**
The label plus `Prevented: none recorded` appeared on a turn with no interpretation. Absence of a
gate is not authorization.
```
tests/services/test_authorized_label_requires_evidence.py
  test_no_interpretation_cannot_render_authorized
  test_authorized_requires_non_empty_prevented_or_compiled_requirements
```

**R3 🔴 Bound the consent round-trip.**
N1 hung 120s. Bound the user-visible wait, stream progress, and fall to Tier 6 abstention on
timeout with `execution_status: timeout`.
```
tests/services/test_research_turn_deadline.py
  test_consent_turn_returns_within_budget
  test_timeout_degrades_to_abstention_not_silence
frontend/e2e/research-consent-timeout.spec.ts
```

**R4 🟠 Adopt ChatGPT's five as the regression corpus**, plus the most-expensive-must-lose gate.

**R5 🟠 Per-attribute verdicts** (`COMPUTE: STRONG · DISPLAY: UNKNOWN`) instead of one blended fit.

**R6 🟡 Research tab:** adjudicate the two observers, `Paid calls: 0` not "not recorded", surface
engine health on Tier 4, fix the badges.

**R7 🟡 Catalogue:** N3 returned the same Legion Pro 7 twice — the 38 duplicate groups are still
there.

Prior roadmap items **C1 (clarification interrupt)** and **C3 (availability ranking)** remain
unchanged and still block the entire commercial half.

---

## 10. Bottom line for the review

Say this plainly to Codex: the evidence architecture, the ladder, the trace, SearXNG stability and
the caching are genuinely finished, and the degradation UX on the path that works is good enough to
demo. The gap is that **the gate is driven by an observer that sees the query but not the
catalogue**, so any workload outside 31 enrolled tokens bypasses every safeguard and gets a
confident answer. The system already computes the correction and only renders it.
