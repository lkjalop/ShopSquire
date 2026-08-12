# Post-Consent External Search + Relevance — Verdict

**Date:** 2026-08-12 · **HEAD:** `86a1efb3` · **Method:** 10 live journeys, no code changed
**Runtime:** demo_v2 · core primary · ready True · SearXNG healthy · 10 of 13 sources approved

---

## 1. Does external search actually run once a human approves it?

**Yes — and it is consequential.** This is a genuine, verified delta.

Q1 (drone photogrammetry / GIS), after clicking **Research approved sources**, in **5,404 ms**
(previously a 120 s hang):

```
Status: Provisional  ->  Researched — scoped product requirements compiled

Research receipt
  Researched 3 official publisher sources. 8 requirements were established;
  product identity and availability remain separately verified.

What changed after approved-source research
  JW-818845      4 -> 2   newly evidenced meets: gpu vram gb, storage gb
  JW-822962      2 -> 4   newly evidenced meets: storage gb
  SCORP-125638   5 -> 3   newly evidenced meets: gpu vram gb, storage gb
  SCORP-C07NXPT  3 -> 5   newly evidenced meets: storage gb

Conditional fit because not verified: cpu cores
```

That before/after ranking delta is the strongest evidence in the project so far: external evidence
was fetched, compiled into predicates, and **it moved the ranking**. Two SKUs promoted, two demoted,
each with the named attribute that changed. That is not a fixture and not decoration.

---

## 2. Verified delta since 2026-08-11

| Prior finding | Status |
|---|---|
| 🔴 R2 — "Authorized recommendation" on an uninterpreted turn | **FIXED** (`9e9841de`). Q2/Q4/Q5 now render `Provisional shortlist`, `Status: Provisional — external research not yet authorized`, `Conditional fit` |
| 🔴 R3 — consent click hung 120 s | **FIXED**. Q1 completes in 5.4 s |
| Research never executed in-product | **FIXED**. Q1 executed, compiled 8 claims, changed ranking |
| Null class absent for novel work | **SHIPPED**. Q5 reads `Unresolved workload requiring authoritative source discovery` |
| Blended fit verdicts | **IMPROVED**. Now per-attribute: `not verified: cpu cores` |
| Narration ungoverned | **IMPROVED**. `Narration authority` disclosure + toggleable `Concise evidence narration` + guarded `AI explanation preview` ([ProductShelvesPanel.tsx:132-158](../frontend/src/components/ProductShelvesPanel.tsx#L132)) |

Genuinely good work. The evidence spine now demonstrably closes the loop.

---

## 3. 🔴 The shelf is a constant — 11 of 11 queries return the same three products

This is the finding that overrides everything else.

| Query | Rank 1 | Rank 2 | Rank 3 |
|---|---|---|---|
| Ergonomic standing desk + mesh office chair | MSI Titan 18 HX $8,999 | HP ZBook Fury $14,999 | HP Z2 Mini $3,699 |
| **Ibuprofen + blood pressure monitor** | *identical* | *identical* | *identical* |
| Small hobby Blender renders, a few minutes | *identical* | *identical* | *identical* |
| Overnight 4K production renders, volumetrics | *identical* | *identical* | *identical* |
| Renders fast in client meetings, speed > quality | *identical* | *identical* | *identical* |

Plus the six personas from 2026-08-11 (digital twin, CGI, CAD, OT, BIM, Unreal) — also byte-identical.

**Eleven distinct queries across three product domains — laptops, furniture, pharmacy — return one
fixed list.** This is not weak ranking; the shelf is not a function of the query at all.

Two consequences worth stating separately:

- **A pharmacy request returns a $14,999 mobile workstation.** That is a sellability failure, not a
  relevance nuance.
- **No scale discrimination.** "A few minutes each, nothing heavy" and "overnight 4K with heavy
  volumetrics and thousands of frames" produce identical output. ChatGPT's scale-ambiguity test
  fails by construction.
- **ChatGPT's rule is failed.** *"At least one test should cause the most expensive laptop to
  lose."* Across 11 queries the $14,999 ZBook never leaves rank 2 and the $8,999 Titan never leaves
  rank 1.

---

## 4. 🔴 Novel workloads corroborate the wrong publishers

Q1 researched successfully — but look at what it interpreted "drone photogrammetry and GIS" as:

```
Current interpretations
  Named AutoCAD version and large-dataset/point-cloud tiers
  Blender application requirements and supported platforms
  Named NVIDIA Omniverse or Isaac Sim local workloads only
```

None of those is photogrammetry. Pix4D, Metashape, RealityCapture, ArcGIS Pro, QGIS — the actual
candidate stack — are absent from the 13-source registry, so the planner snapped to the nearest
*enrolled* sources and then reported **"8 requirements were established"** with full confidence.

It is not fabricating claims — the claims are genuinely from AutoCAD/Blender/Omniverse. It is
**answering a photogrammetry question with somebody else's requirements and labelling the result
established.** That is a subtler and more dangerous failure than refusing.

---

## 5. 🔴 Two dead ends remain on the research route

**Q3 (five-year fleet) — consent click is a silent no-op.** The button rendered, the click returned
in 2,122 ms, the chat showed only a spinner glyph, and the panel still reads
`Status: Provisional — external research not yet authorized`. Nothing happened and nothing said so.

**Q2 / Q4 / Q5 — provisional with no research route.** All three correctly refuse to claim fit, but
offer only `Upload requirements` / `Use official link or vendor` / `Enter specifications` /
`Continue provisionally`. No `Research approved sources`.

Q5 is the sharpest illustration: its interpretation is literally
**"Unresolved workload requiring authoritative source discovery"** — and then no discovery is
offered. The system correctly diagnoses that it needs discovery and has none to give, because
discovery is bound to `approved_sources_for_plan(plan)`
([case_research_plan.py:218-228](../src/app/services/case_research_plan.py#L218)) which filters the 13-source registry.

Q2's `Current interpretations` list is **empty** — no hypotheses at all for FEA/CFD.

---

## 6. 🟠 Category leakage into non-laptop domains

The standing-desk request was asked:

> *"Which named software or standard governs this work, and what must run locally?"*

…and offered **"Discover official sources"** for a desk and a chair. The ibuprofen request got
*"This request needs current external requirements before I can qualify products."*

The clarification template and the whole workload frame are laptop-shaped and are applied to every
domain. The furniture turn also took **29 s** and reported
*"The catalog-ranking step reached its deadline"* — a ranking timeout on the simplest query in the
battery.

---

## 7. Research tab — assessment

**Correct, and materially better than last week.** It now renders, and I verified each of these
live: model interpretation with material unknowns; both shadow observers with state, score and named
reasons; the bounded research plan with literal planned queries and prohibited-assumption lists;
material slots; governed provider search with consent state; `External provider calls` and
`Internal effort: 3 / 8`; the Tier 0–6 ladder with per-rung execution status and billing class;
evidence-to-requirement compilation status; deterministic authorization with an explicit
`Prevented:` list. Post-research it adds the **research receipt** and the **ranking-delta block**.

Remaining issues, all previously reported and still open:
1. **The two observers still disagree without adjudication** — the panel shows `catalog sufficient /
   score 0` beside a post-catalog `coverage gap` of 0.38–0.87 and never says which one gated.
   `research_trigger_post_catalog_shadow` is still written at [core.py:1265](../src/app/services/recommendation_core/core.py#L1265) and read only by
   [trace_ontology.py:159](../src/app/services/recommendation_core/trace_ontology.py#L159) to display it.
2. **`Paid calls: not recorded`** should read `0`.
3. **No engine health on the Tier-4 rung**, though `discovery_engine_reliability.py` records it.
4. **Badges over-claim** — `FRESHNESS: Current` / `AUTHORITY: Platform authorized` on turns that
   interpreted nothing.

---

## 8. LLM narration — assessment

Governed and honest where it appears. From Q1:

> *"The leading shelf has 3 options for the retained purpose; 0 have verified exact-configuration fit
> and the remainder stay conditional."*
> **Narration authority:** *"Official research compiled 8 scoped product claims and 0 context claims."*

No invented benchmarks, no "great for X", counts are stated rather than implied, and it discloses
its own authority basis. The toggle and the preview button are correctly gated
([ProductShelvesPanel.tsx:132-158](../frontend/src/components/ProductShelvesPanel.tsx#L132)).

Its weakness is inherited, not intrinsic: narration faithfully describes a shelf that is the same
for ibuprofen and for 4K rendering. Narration quality cannot exceed the quality of what it narrates.

---

## 9. What to hand Codex — ordered

**N1 🔴 The shelf must be a function of the query.**
11/11 identical across laptops, furniture and pharmacy. Before any further evidence work, establish
that retrieval and ranking consume the query at all. Suspect the shelf reducer is reading a fixed
pool rather than per-hypothesis retrieval output.
```
tests/services/test_shelf_is_query_dependent.py
  test_furniture_query_returns_no_laptops
  test_pharmacy_query_returns_no_workstations
  test_small_render_and_large_render_differ
  test_most_expensive_sku_loses_on_at_least_one_persona   # ChatGPT's rule, as a hard gate
  test_eleven_distinct_queries_do_not_share_identical_top_three
```

**N2 🔴 Sellability/domain gate before the workload frame.**
A pharmacy or furniture request must not be asked which software governs it, and must not be served
laptops.
```
tests/services/test_domain_routing_precedes_workload_frame.py
```

**N3 🔴 Q3's consent no-op.** A click that changes nothing must say so; on failure fall to Tier 6
abstention with `execution_status`, never a spinner glyph.

**N4 🔴 Novel-source honesty.** When `approved_sources_for_plan` returns only *adjacent* sources,
the receipt must say so — "researched AutoCAD/Blender as nearest enrolled sources; photogrammetry
publishers are not enrolled" — instead of "8 requirements were established". Same fix unblocks
Q2/Q4/Q5: offer discovery for unenrolled concepts, or state plainly that discovery is unavailable
for this concept and route to upload/link.

**N5 🟠 Feed the post-catalog observer into the gate** (unchanged from 2026-08-11 R1).

**N6 🟠 Catalog-ranking deadline** — 29 s and a timeout on "standing desk and office chair".

Prior **C1 (clarification interrupt)** and **C3 (availability ranking)** remain open and still block
the commercial half.

---

## 10. Bottom line

The question you asked — *can the platform actually do external search once a human approves it?* —
has a clear answer: **yes, it can, it does, and it changes the ranking.** The consent path, the
receipt, the compiled claims and the before/after deltas are all real and verified live.

The problem has moved. It is no longer the evidence pipeline; that now works. It is that the
**product shelf those evidence deltas are re-ranking appears to be a constant** — the same three
SKUs for a cyber range, a hobby render, a standing desk and a packet of ibuprofen. Until the shelf
depends on the query, a correct evidence layer is re-ranking the wrong list.
