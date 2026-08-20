# Why "the commerce agent is the weakest part" was the wrong diagnosis

**Date:** 2026-08-12 · **HEAD:** `86a1efb3` · Corrects [SHOPSQUIRE_PLATFORM_DEEP_DIVE_SWOT_2026-08-12.md](SHOPSQUIRE_PLATFORM_DEEP_DIVE_SWOT_2026-08-12.md) §3, §8

---

## 1. The correction

I said the ranking layer was broken because 11 distinct queries returned an identical top three.
The observation was right. **The diagnosis was wrong.**

```
products                rows = 260      <- legacy catalogue: laptops, monitors, bags,
                                           furniture, pharmacy, routers, SSDs
product_configurations  rows =  12      <- evidence-grade catalogue the shelf reads
```

The twelve, in full:

```
 1  MSI Titan 18 HX A2WJ RTX 5090 Laptop            $8,999
 2  ASUS ROG Zephyrus Duo GX651 RTX 5090            $12,999
 3  HP ZBook Fury G1i 16 Mobile Workstation         $14,999
 4  HP Z2 Mini G1a Workstation                       $3,699
 5  GMR Zephyr 5090 Gaming PC                        $8,999
 6  Lenovo LOQ 15.6 RTX 3050                         $1,699
 7  Lenovo Legion 5i 15.1 RTX 5070                   $3,899
 8  Lenovo Legion 9i 18 RTX 5080                     $8,799
 9  MSI Crosshair 16 HX RTX 5070                     $4,599
10  MSI Thin A15 RTX 3050                            $1,498
11  HP OMEN 15.3 RTX 5070                            $4,799
12  Gigabyte AORUS MASTER 16 Gen 2 RTX 5090          $8,999
```

Every one is a laptop, workstation or desktop PC. There is no desk, no chair, no ibuprofen, no
monitor, no bag.

`build_product_shelves` ([product_shelves.py:365](../src/app/services/recommendation_core/product_shelves.py#L365)) is a clean pure function: it excludes verified
hard failures, computes `available_now` / `shortfall` / `quantity_fit`, and splits within-budget
from stretch shelves. `project_accepted_catalog` ([accepted_catalog_projection.py:415](../src/app/services/accepted_catalog_projection.py#L415)) filters on
`tenant_id` and `active` only, then optionally narrows to a case-bound id list.

**Given twelve candidates of one category, of which roughly five survive fit filtering, returning
the same top three for every query is not a bug — it is the arithmetic.** "Provisional shortlist —
5 configurations" was telling me this the whole time and I read past it.

So: the ranking algorithm is sound. What is missing is **catalogue breadth in the evidence-grade
table** — and one genuine defect that survives the correction.

---

## 2. What is still genuinely broken

**The sellability gate.** A request for ibuprofen and a blood-pressure monitor returned a $14,999
mobile workstation. Even with a 12-row laptop-only universe the correct answer is *"I don't sell
that"*, not the nearest laptop. Same for the standing desk — which was additionally asked *"which
named software or standard governs this work?"*

That defect is **orthogonal to catalogue size** and would still exist with 10,000 configurations.
It is the real ranking-layer bug, and it is much smaller than the one I claimed.

---

## 3. The architectural fork this exposes

There are two catalogues and the migration between them is incomplete:

| | `products` (260) | `product_configurations` (12) |
|---|---|---|
| Breadth | all categories | laptops/workstations only |
| Identity | name + specs blob | **MPN, retailer SKU, source_url, configuration_hash** |
| Provenance | none | per-attribute, with freshness |
| Availability | single flag | per-location, dated, freshness-tracked |
| Can support a qualified claim? | no | **yes** |
| Powers the shelf? | no | **yes** |

This is the crux. The evidence-grade table is the *right* model — it is what lets the platform say
"RAM 64GB meets the ≥32GB requirement established by Microsoft on 2026-08". But it costs real work
per SKU, so it has twelve rows while the demo catalogue has 260.

**Every option below is a different answer to: how do you get evidence-grade breadth without
hand-curating every SKU?**

---

## 4. Five options, with trade-offs

### Option A — Backfill: promote all 260 into `product_configurations`

Mechanically derive configurations from `products` specs.

| | |
|---|---|
| **Buys** | Immediate breadth. Furniture and pharmacy queries get real candidates. Ranking becomes observable. |
| **Costs** | Derived rows have no MPN, no `source_url`, no per-attribute provenance. |
| **Risk** | **Destroys the differentiator.** Every card would read `Evidence freshness: unknown` and every fit `conditional`. You would have 260 unverifiable rows instead of 12 verifiable ones. |
| **Verdict** | Fast, and the wrong direction. |

### Option B — Two-tier catalogue with explicit labelling

Legacy `products` powers *exploration*; `product_configurations` powers *qualification*. The UI
shows both, visibly separated: "Evidence-qualified (3)" and "Catalogue matches — not yet verified (17)".

| | |
|---|---|
| **Buys** | Breadth **and** honesty. Preserves the "conditional vs verified" distinction that is the product. Makes the 12-vs-260 gap a visible feature rather than a hidden constraint. |
| **Costs** | Two retrieval paths, two ranking passes, a more complex panel. |
| **Risk** | Buyers gravitate to the longer unverified list; needs careful default ordering. |
| **Verdict** | **Best fit for the thesis.** It is the stretch-slate principle applied to evidence rather than budget. |

### Option C — Narrow the official scope

Declare ShopSquire a workstation/laptop procurement platform. Refuse everything else by design.

| | |
|---|---|
| **Buys** | Every query lands in-scope. The sellability gate becomes trivial. Demo is coherent. Matches the enrolled 31 workloads and 13 publishers. |
| **Costs** | Gives up the general-commerce story. |
| **Risk** | Looks like a retreat if presented badly; looks like focus if presented well. |
| **Verdict** | **Strongest for a demo or pilot in the next month.** Combine with B later. |

### Option D — Lazy promotion on demand

A legacy product is promoted to evidence-grade only when it enters a shortlist: fetch the retailer
page, extract MPN/specs/availability, write a configuration.

| | |
|---|---|
| **Buys** | Breadth without bulk curation. Evidence cost paid only where it matters. Reuses the working discovery→origin-fetch→parse pipeline. |
| **Costs** | First-touch latency; needs the cache and a retailer-page parser (currently only publisher parsers exist). |
| **Risk** | Retailer pages are exactly the hostile input your own ingest documented — intra-page conflicts in 4 of 11 records, empty and image-only spec tables, prices moving $2,899→$4,799 minutes apart. |
| **Verdict** | The elegant long-term answer. Not a next-month move. |

### Option E — Sellability gate first (do this regardless)

Before any workload framing, decide whether the request is in the sold taxonomy at all. Out of
scope → refuse and say why.

| | |
|---|---|
| **Buys** | Kills the worst-looking failure (ibuprofen → $14,999 workstation) for very little work. Also kills the "which named software governs this desk?" leakage. |
| **Costs** | Small. `sells_within()` and the classifier already exist from the T1 taxonomy work. |
| **Risk** | Over-refusal if the taxonomy is thin — needs the same care as the abstention threshold. |
| **Verdict** | **Do it first.** Orthogonal to the catalogue question and required under every other option. |

---

## 5. How this changes the five proposals

| Original | Revised |
|---|---|
| 1. "Make the shelf a function of the query" | **Retired as stated.** The shelf already is; the candidate pool is twelve rows of one category. Replaced by: **E (sellability gate)** then a catalogue decision between **B** and **C**. |
| 2. Unblock the commercial half (clarification-interrupt clamp) | **Unchanged — now clearly #1.** One deterministic rule releases feasibility, escalation and RFQ, all built and tested. Nothing else has this leverage. |
| 3. Feed post-catalog observer into the gate | **Unchanged, and now better motivated.** With 12 candidates the coverage gap is *genuinely* high; the observer is right and is being ignored. |
| 4. Catalogue hygiene | **Promoted and reframed.** Not tidying — it is the central architectural decision (§4). |
| 5. Narrow the story | **Strengthened.** Option C is the same instinct, now with a measured justification. |

**Revised order:** ① clarification-interrupt clamp → ② sellability gate → ③ catalogue decision
(C now, B next) → ④ post-catalog observer feedback → ⑤ narrow the story.

---

## 6. Trade-off that matters most

The deepest tension in the platform:

> **Evidence-grade catalogue entries are expensive, and the product's entire value comes from
> having them.**

Twelve rows is not laziness — it is the honest cost of per-attribute provenance, MPN identity,
dated availability and conflict retention. The 260-row table is cheap and cannot support a single
qualified claim.

Three coherent stances:
- **B** — carry both and label the difference. Truthful; more UI.
- **C** — shrink the promise to match the evidence. Coherent; smaller.
- **D** — make evidence acquisition incremental. Elegant; hardest.

The stance I would **not** take is A — scaling breadth by diluting evidence. That converts the one
genuinely differentiated asset into an ordinary product catalogue.

---

## 7. Revised verdict

Replace §8 of the deep dive with this:

The commerce agent is **not** the weakest part. Its ranking layer is a sound pure function that has
been operating correctly on a twelve-row, single-category universe and reporting exactly that
("5 configurations") the whole time.

The real weaknesses are narrower and more tractable than I claimed:
1. **No sellability gate** — the only genuine ranking-layer defect.
2. **Evidence-grade catalogue breadth** — an unmade architectural decision, not a bug.
3. **The commercial half is still gated behind one relation-classification bug** — unchanged, and
   still the highest-leverage fix in the codebase.

I should have checked the candidate table before calling the algorithm broken. The observation that
eleven queries returned three identical products was real; concluding "ranking is broken" from it
was not warranted, and the correct read — *the evidence catalogue has twelve rows* — points to a
completely different set of options.
