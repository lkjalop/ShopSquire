# Evidence-Coverage Architecture — Assessment, Roadmap, Wiring

**Date:** 2026-08-08 · **HEAD:** `58d87b03` · **Screenshots:** 51–56
**Prior:** [delta retest](SHOPSQUIRE_DELTA_RETEST_2026-08-08.md) · [cart/explain UX](SHOPSQUIRE_CART_EXPLAIN_UX_ASSESSMENT_2026-08-08.md) · [research adjudication](SHOPSQUIRE_RESEARCH_ADJUDICATION_AND_NARRATION_ROADMAP_2026-08-08.md)

---

## 0. The finding that reframes all six screenshots

Measured against the live demo database:

```
laptops = 41
windows_11_pro mentions   = 0
workstation mentions      = 0
professional GPU mentions = 0
price range               = $69.95 – $5,999
```

**The catalogue contains zero workstation-class machines.** Not one Win 11 Pro SKU, not one
RTX PRO / Quadro, not one ECC-capable platform.

So for *"laptop for digital twin project, OT cyber attack simulation"*, a perfect router with a
perfect research lane and a fully enrolled provider **would still return a consumer gaming
laptop** — because nothing else exists to return. The only truthful answer available today is
*"nothing in catalogue qualifies → draft a supplier RFQ."*

This changes the priority order. Every prior analysis — mine included — treated this as an
interpretation/research problem. Interpretation is necessary but **not sufficient**: fixing the
router without fixing the catalogue converts a wrong recommendation into an honest empty result.
That is progress, but it is not a demo.

The inventory file supplies exactly the missing class: HP ZBook Fury G1i (`MOBILE_WORKSTATION`,
RTX PRO 4000, 128GB, Win 11 Pro, 3yr onsite), HP Z2 Mini G1a (`DESKTOP_WORKSTATION`), MSI Titan
18 HX (Win 11 Pro, 175W TGP published, 128GB ceiling). It also lifts the peak from $5,999 to
$14,999 and introduces desktop/SFF form factors, which the OT workload legitimately needs.

**Ingest the catalogue before, or alongside, the research work.**

---

## 1. Screenshot verdicts

| # | What it shows | Root cause | Status |
|---|---|---|---|
| 51 | "why is this a good choice? add 30 more? 4 days?" → budget question, qty stays 30 | EXPLAIN act dropped when the turn also mutates; `slot_gap_clarify` fires on retrieval-emptiness while the cart holds $179,970 | Not fixed |
| 52 | Same shape, **honest refusal** + correct 30→60 read | Fit ledger empty for that SKU; arithmetic is correct | **Best behaviour in the set — hold as baseline** |
| 53 | "add 30 for ASUS / clear 30 Lenovo" → neither applied, confirm text twice | Pending `plan_id` silently superseded by the next message; compound → one op | Not fixed |
| 54 | "why is not researching" | `web` leg **arithmetically unreachable**; `concept_discovery` unenrolled | Not fixed |
| 55 | Buyer uploads a requirements screenshot → **same refusal repeated 3×** | No upload→claim path exists at all | Not fixed — see §2 |
| 56 | not scraped | same family as 54 | Not fixed |

### 52 is the target, not the bug

*"I can propose the quantity change, but the accepted workload-fit ledger for this exact SKU is
unavailable, so I will not invent a capability explanation."* That is the honesty layer working.
Every other screenshot should degrade to that sentence, not to a budget question.

---

## 2. Screenshot 55 is the worst of the six, and the cheapest to fix

The system says **"Provide an approved requirements document."** The buyer provides one. The system
repeats **"Provide an approved requirements document."** Three times, once inside
"HELP ME NARROW THIS DOWN".

Verified cause: `grep image_ocr|ocr_text` across `recommendation_core/` and the requirement
compiler returns **zero matches**. The upload lands in the visual-search lane
([`ImageRecommendPanel.tsx:245`](../frontend/src/components/ImageRecommendPanel.tsx#L245), badge `Analysis degraded`), which does *product
identity*. Requirements live in a different subsystem. The two never meet.

**But the receiving contract already exists.**
[`requirement_compiler.py:21`](../src/app/services/recommendation_core/requirement_compiler.py#L21):

```python
_AUTHORITATIVE = frozenset({"official_requirements", "approved_tenant_document"})
```

`approved_tenant_document` is already an accepted authority. Nothing in the codebase ever emits a
claim with it. So this is not "add a new evidence tier" — it is **write one producer for a slot
that is already wired, validated, and audited**. The compiler's provenance checks
(`source_id`, `source_record_id`, `lineage_root`, `observed_at`, `minimum_confidence=0.80`) apply
unchanged.

That is the single highest value-per-hour item in this document. It also removes the dependency on
paid search for the demo entirely — the buyer *is* the evidence source.

---

## 3. Adjudicating the proposed architecture

**The evidence-coverage gate is correct and I would adopt it.** Specifically:

✅ **Tier ladder 0→4 with paid discovery last.** Matches the money constraint and the bounded domain.
✅ **"Persona is a cache/routing shortcut, not the authority."** Correct, and it is the fix for the CGI class.
✅ **Cheap internal hypothesis sketch *before* searching, non-authoritative, not buyer-facing.** This is the piece both earlier analyses missed — you cannot construct a good query without a hypothesis, but that hypothesis must not leak into the product claim.
✅ **Upload treated as a *lead*, not authority.** Right. Screenshot 55's sources are YouTube/Reddit/LinkedIn — buyer-supplied, unverified, and the confirmation UI correctly says so.
✅ **Separating workload evidence / procurement constraints / alternative envelope.** This is the sharpest idea in the proposal. "16GB VRAM is acceptable to me" authorizes a *search*, it does not establish *fit*. Nothing in the codebase models that distinction today.
✅ **Commit policy requiring a browser journey + trace assertions per slice.** Adopt verbatim — three of the last delta's specs went red precisely because behaviour changed without its own acceptance test.

**Two corrections:**

1. **Phase 2 ("fix evidence-orchestrator reachability") must move to Phase 0.** It is a one-integer
   change ([`core.py:960`](../src/app/services/recommendation_core/core.py#L960) `max_cost_units=3` vs `web` costing 5 at
   [`evidence_orchestrator.py:107`](../src/app/services/evidence_orchestrator.py#L107)) and until it lands, every downstream research test is
   measuring a lane that cannot execute. Renaming "cost" to "effort" is right and free.

2. **Catalogue ingestion is missing from the roadmap entirely.** Per §0 it is a hard blocker on
   demonstrating any of Phases 4–8. Insert it at Phase 0.

**One thing to drop:** Journey C asserts "exact paid-call count". Keep the counter, but the demo
target should be **zero paid calls in every journey** — buyer upload + sealed corpus + cache
should cover all six screenshots. If a journey needs a paid call to pass, the tier ladder failed.

---

## 4. Backend — what to fix

| # | Fix | Where |
|---|---|---|
| B1 | **Upload→claim producer** emitting `authority: approved_tenant_document` with full provenance | new `services/buyer_evidence_ingest.py`; consumer already at [requirement_compiler.py:31](../src/app/services/recommendation_core/requirement_compiler.py#L31) |
| B2 | **Effort budget** — rename cost→effort; make selected legs reachable or report `NOT_SELECTED` | [core.py:960](../src/app/services/recommendation_core/core.py#L960), [evidence_orchestrator.py:107](../src/app/services/evidence_orchestrator.py#L107), [:653](../src/app/services/evidence_orchestrator.py#L653) |
| B3 | **3-D status** `execution × evidence × decision`; paid-call counter separate from effort | [evidence_orchestrator.py:653](../src/app/services/evidence_orchestrator.py#L653), [trace_ontology.py](../src/app/services/recommendation_core/trace_ontology.py) |
| B4 | **Clarifier must not contradict state** — add `has_selection`/`cart_non_empty`; return `None` when either is true | [gates.py:41-48](../src/app/services/recommendation_core/gates.py#L41) |
| B5 | **Multi-act turns** — one narration block per obligation; unanswered acts recorded, never dropped | [cart_compound_response.py:72](../src/app/services/recommendation_core/cart_compound_response.py#L72), obligations at [:105](../src/app/services/recommendation_core/cart_compound_response.py#L105) |
| B6 | **Fit ledger persistence** across turns (half-landed in `78e5b408`) | [chat.py:1560](../src/app/routers/chat.py#L1560), [core.py:2502](../src/app/services/recommendation_core/core.py#L2502), [cart_session_state.py:28](../src/app/services/cart_session_state.py#L28) |
| B7 | **Pending plan supersession** — announce it; never discard silently | [recommendation_facade.py:436](../src/app/services/recommendation_facade.py#L436) |
| B8 | **Workload hierarchy** replaces 11 flat personas; requirement floor becomes the addressable object | `config/use_case_kb.json` → new hierarchy + floors |
| B9 | **Constraint envelope** — model `preferred` vs `acceptable_alternative` vs `mandatory` as procurement constraints distinct from workload evidence | new; feeds [core.py:1174](../src/app/services/recommendation_core/core.py#L1174) |
| B10 | **Catalogue schema** — `mpn`, `warranty_type`, `gpu_tgp_w`, `ram_ceiling_gb`, `os_edition`, `form_factor`, `device_class`, `gpu_class`, `claim_class`, per-location availability, conflict retention | `products` table (currently 13 cols, **no `mpn`**) |

### Catalogue ingestion (B10) — what the file demands

The inventory file is not just rows; it argues for schema changes and it is right:

- **`mpn` first-class** — all 9 fully-extracted records publish one; the table has no column.
- **Three freshness classes** — specs long-TTL, price **minutes** (the OMEN record repriced
  $2,899→$4,799 on the same URL minutes apart), availability real-time and *per location*.
- **`claim_class`: ATTESTED | DERIVED | BEHAVIOURAL | SUBSTITUTABLE** — the GMR Zephyr carries
  "| Or Equivalent" on six components. Those rows cannot be attested; a requirement resting on
  them must be UNKNOWN, not met.
- **`warranty_type`** (RTB vs ONSITE_NBD) alongside `warranty_years` — for a 30-unit fleet these
  are materially different procurement risk, and the word "warranty" hides it.
- **Never resolve conflicts** — 4 of 11 records contradict themselves intra-page. Carry both.
- **Never copy attributes across SKUs sharing a GPU name** — RTX 5090 **Laptop** = 24GB VRAM,
  RTX 5090 **Desktop** = 32GB. The file is its own regression fixture for that discriminator.
- **Retailer category tags are merchandising** — the ZBook mobile workstation is tagged
  "Product Use: General, Gaming". Keep them out of the fit engine.
- **Three spec-table failure modes** — POPULATED / EMPTY / IMAGE-ONLY. An extractor handling only
  the first silently returns zero rows for 3 of 11.

Ingest in two passes: **(a)** the 27 simple price/spec rows to widen the catalogue and lift the
peak; **(b)** the 11 provenance-rich records into the new columns, as the seed for the sealed
corpus and the conflict-handling fixtures.

---

## 5. Frontend — what to surface

**Panel switches on the turn's dominant obligation; one rail never changes.**

```
+-- [Interpretation] [Fit] [Shortlist] [Cart] [Delivery] --+
| PURPOSE (retained)                               [edit]  |   <-- never changes
| ACCEPTED FLOOR         source · captured · tier          |   <-- never changes
| CONFIDENCE  provisional | conditional | verified         |   <-- never changes
+----------------------------------------------------------+
```

That rail is the structural fix for "multi-turn isn't going back to the first reason why". If the
floor is always on screen it cannot be lost between turns.

**F1 — Research choice (replaces the dead end in 54/55/56)**

```
Your request isn't covered by the local requirements corpus.
Fastest way to ground it:
  [Research approved sources]   [Upload PDF/TXT/PNG]
  [Enter specifications]        [Browse provisional options]
```

Four doors, not one refusal. Three of them cost nothing.

**F2 — Upload confirmation (screenshot 55's missing screen)** — extracted claims grouped
Required / Recommended / **Conditional** / Needs confirmation, editable, with
`Evidence: buyer supplied — not independently verified`, and
`[Use provisionally] [Research and corroborate]`. The Conditional group matters: the screenshot's
GPU line is conditional on local 3D, and flattening it to "required" would be a fabrication.

**F3 — Configuration envelope** — Preferred vs Acceptable alternative, with
`(•) only if preferred has no match / ( ) show both / ( ) preferred is mandatory`. When preferred
has no match, say which constraint conflicts and how many products meet the rest — never silently
return the nearest thing.

**F4 — Shelves** — Shared-fit top 3, then top 3 per material hypothesis, `[+ next 5]`,
within-budget and stretch shelves visibly separate. Never mix.

**F5 — Trace** — execution/evidence/decision as three columns, **paid-call count visible and
expected to read 0**, rejected work never rendered as "pending", `FRESHNESS: Not assessed` when
nothing was fetched, `UNCERTAINTY: Material` when blocked for uncertainty.

**F6 — Pending cart plan** — durable card bound to `plan_id`, enumerating *every* op, with
`⚠ Typing a new request replaces this pending change.`

---

## 6. Roadmap

### Phase 0 — unblock and stop lying (days)
1. **Catalogue ingest pass (a)** — 27 rows, peak to $14,999, first workstation-class SKUs. *Without this, nothing downstream is demonstrable.*
2. **Effort budget** — B2. One integer + a rename.
3. **3-D status + badge honesty** — B3, and stop rendering refusals inside "HELP ME NARROW THIS DOWN".
4. **Clarifier state check** — B4.
5. **Fit ledger persistence** — B6; finish `78e5b408` and update its stale test.

### Phase 1 — buyer as evidence source (the demo unlock, zero cost)
6. **B1 upload→claim producer** + F2 confirmation UI. Covers 55 and removes the paid-search dependency.
7. **F1 research-choice panel** — four doors.
8. **Provisional tier** — shortlist labelled unverified; claims and autonomous actions stay gated. Loosen `authority before catalog` to *authority before claims and autonomous actions*.

### Phase 2 — reasoning (zero marginal cost)
9. **B8 workload hierarchy + requirement floors**; intersection floor + divergent axis; one high-information question chosen by candidate-set reduction.
10. **Sealed corpus + evidence cache**, seeded from inventory pass (b); freshness-tiered TTL in days.

### Phase 3 — commercial reasoning
11. **B9 constraint envelope**; conflict enumeration (relax budget / reduce qty / substitute / RFQ / split); F3 + F4.
12. **B5 multi-act narration** and **B7 pending-plan surface** — closes 51 and 53.

### Phase 4 — catalogue depth
13. **Inventory pass (b)** into the new schema; conflict retention; the RTX 5090 laptop-vs-desktop discriminator as a permanent fixture.

### Phase 5 — only now, discovery providers
14. SearXNG + local extraction for dev. One paid provider behind the tier-4 gate, if tiers 0–3 measurably miss. Re-verify pricing then.

### Commit gate (adopt as proposed)
Unit + reducer + adversarial + API + **browser journey + trace assertions + zero unexpected
provider calls** before any slice commits. The last delta shipped three behaviour changes whose own
specs went red — this gate is what prevents that.

---

## 7. Journeys to certify

Adopt A–F as written, with one change: **every journey asserts `paid_calls == 0`**, including C
(use the fixture provider). A separate opt-in live certification exercises real providers.

Add **Journey G — catalogue truth**: for the OT/digital-twin query against the *enriched*
catalogue, assert the shortlist contains only Win 11 Pro / workstation-class machines, that
consumer gaming SKUs are excluded with a stated reason, and that if none qualify the response is a
supplier RFQ draft — not a nearest-neighbour gaming laptop.

That journey is the one that proves the whole thesis, and it is not runnable until the catalogue
lands.
