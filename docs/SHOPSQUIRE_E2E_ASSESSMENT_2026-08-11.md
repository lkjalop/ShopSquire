# End-to-End Assessment — Search, Bulk, Shortfall, Supplier, ERP

**Date:** 2026-08-11 · **HEAD:** `d755ab88` · **Method:** 7 live browser journeys, no code changed
**Runtime:** demo_v2 / core primary / external_search live · SearXNG :8888 · fixture :8099

---

## 0. Headline

**Two genuine wins shipped since the last assessment. One client-side regex is silently disabling the
entire bulk-procurement value proposition, and one clarification deadlock swallows every follow-up
turn.** Neither is deep — both are contained and precisely located.

---

## 1. What actually works

### 1.1 The governed evidence ladder is live in the trace ✅

Phase-0 recommendation shipped. Rendered per turn:

```
Tier 0: evidence cache            — completed        Billing: free
Tier 1: enrolled canonical origin — completed        Billing: free
Tier 2: buyer upload or link      — not attempted (no upload provided)
Tier 3: vendor resolution         — not attempted (not requested)
Tier 4: self hosted discovery     — not needed       dispatched: 0 · allowlisted hits: 0
Tier 5: paid discovery            — not attempted (provider not enrolled)
Tier 6: governed abstention       — not needed
"Missing evidence remains not verified. No unavailable source establishes
 safety, compatibility, or fit."
```

Every rung reports execution truth *and* billing class. This is exactly the design and it is the
strongest artifact in the product.

### 1.2 External search works, and is cached ✅

Journey A, "Research approved sources":

> *"Approved-source research completed in the same shopping case. I compiled **8 scoped product
> claims** and kept 0 source or capability gaps visible. No cart or supplier action was authorized."*

**1,307 ms**, Tier-0 cache hit, `dispatched: 0`, zero paid calls. The cache landed and it works —
repeat runs of the certified query no longer touch the network at all, which is precisely the fix
for the CAPTCHA fragility.

### 1.3 Ambiguity handling is strong ✅

Journey A produced three correct interpretations (Factory I/O host requirements · Hyper-V host
capability · ICS adversary behaviours), one high-information question, per-hypothesis shelves,
`Conditional fit` with a stated reason, and four next-step affordances including the new
**"Use official link or vendor"**.

### 1.4 The RFQ drafter is genuinely well-engineered ✅

[`fulfillment/draft.py:36-51`](../src/app/services/fulfillment/draft.py#L36) — fixed template, slot-filled, no free-text model output:

```
Subject: Availability and quote request — {item_ref} x {quantity} — {case_ref}
Body:    ... Please confirm availability and provide a quote for {item_ref},
         quantity {quantity}, required by {needed_by} ...
         Please reply with your unit price, lead time, and how long the quote is valid.
         This request does not constitute a purchase order.
```

With three real defences: a **price-leak guard** (`_PRICE_RE`, any currency token = unsafe), a
**commitment/PO-claim guard** (`_NOT_A_PO` required), and a **CC-injection guard** — any address in
the body not on the resolved supplier domain is rejected. Recipient comes from the allowlist, never
from the body. That is a properly caged send path.

Human gate at [`fulfillment/autonomous_send.py:4-17`](../src/app/services/fulfillment/autonomous_send.py#L4): any failing guard escalates and leaves the case at
`AWAITING_APPROVAL`; the function never changes state on escalate. Runtime confirms
`supplier_transport: sandbox`, `supplier_autonomy: off`.

### 1.5 ERP/CRM surface is broader than expected ✅

`src/app/erp/connectors/`: **sap.py, sap_inventory.py**, ariba, coupa, netsuite, dynamics,
quickbooks, shopify, csv, http — plus **salesforce.py and hubspot.py** for CRM, and
`connectors/accounting/xero.py`. Each has a paired `*_inventory.py`. The rails for the
trade-credit/PO work exist.

---

## 2. Defects, ranked

### 🔴 D1 — A client-side regex refuses the core bulk question

[`frontend/src/App.tsx:1676`](../frontend/src/App.tsx#L1676), refusal emitted at [`:1684`](../frontend/src/App.tsx#L1684):

```js
|| /\b(?:track|where('?s| is)|status of)\b.{0,24}\b(?:order|package|...)\b
   |\border\s+status\b|...
   |\bwhen\b.{0,24}\b(?:arrive|delivered|ship|get\s+here)\b/i.exec(q)
```

`"I need 15 of the top one. **When can they all arrive?**"` matches the last alternative and returns:

> *"I can't do that from chat yet ("When can they all arrive") — a human teammate can via the admin
> console."*

**The request never reaches the backend.** The regex conflates *"where is my existing order"*
(genuinely unsupported) with *"when can this prospective order arrive"* — which is the single most
important question in bulk procurement, and which the backend **can** answer: it has stock split,
network transfer, and supplier allocation already built.

Observed on bulk 15, 30 and 40 identically. This one line is disabling the product's headline
capability and logging it to the capability-gap ledger as if it were a missing feature.

**Fix:** require a post-purchase anchor (`my order`, `my delivery`, an order ref) for that
alternative; a prospective quantity/deadline question must fall through to the backend.

### 🔴 D2 — Pending clarification absorbs every subsequent turn

Journey D, three consecutive turns, three identical replies:

```
"I need laptops for a factory rollout"                  -> "This request needs current external
                                                            requirements... May I check approved
                                                            official sources?"
"I need 40 of the most expensive one within 3 days"     -> (identical)
"yes please raise a supplier enquiry for the shortfall" -> (identical)
```

Quantity 40, the 3-day deadline, and an **explicit supplier-enquiry request** were all swallowed.
No shortfall computed, no supplier enquiry raised, no human gate reached. The purpose field then
became:

> *"I need laptops for a factory rollout Buyer clarification to 'This request needs current external
> requirements…': yes please raise a supplier enquiry for the shortfall."*

Relation handling is at [`chat.py:3536-3541`](../src/app/routers/chat.py#L3536): only `answer` / `supersede` / `interrupt` are
handled. A new *commercial* intent arriving while a research-consent question is pending is
classified as an answer to it. This is the multi-act defect, now escalated to a total conversational
deadlock.

**Fix:** a turn carrying a new commercial obligation (quantity, deadline, supplier action) must be
`interrupt`, not `answer`. The pending question survives; the new intent is served.

### 🔴 D3 — Unavailable configurations rank first

Every journey returned the same top shelf:

```
HP Z2 Mini G1a Workstation  $3,699  Conditional fit  unavailable  network stock: 0   <- rank 1
MSI Titan 18 HX RTX 5090    $8,999  Conditional fit  available    network stock: 3
GMR Zephyr 5090 Gaming PC   $8,999  Conditional fit  unavailable  network stock: 0
```

Two of three "Best fit" options have zero stock anywhere, and the zero-stock one is ranked first.
For a 40-unit order this is not a ranking flaw, it is a wrong answer. Availability is *rendered*
([`ProductShelvesPanel.tsx:140`](../frontend/src/components/ProductShelvesPanel.tsx#L140)) but not *ranked on*.

**Fix:** availability must be a ranking term, and a zero-stock SKU must never occupy rank 1 without
an explicit "sourcing required" label and a lead-time.

### 🟠 D4 — Over-abstention on ordinary queries

`"I need gaming laptops for a studio"` and `"I need laptops for a factory rollout"` both triggered
the research-consent gate. These are catalog-servable. This is the false-positive risk flagged when
the `product_type_options` guard was removed — now measurable: **2 of 2 ordinary bulk openers
abstained.**

### 🟠 D5 — Shelves don't discriminate by workload

The identical three SKUs top the shelf for "PLC/OT cyber range", "gaming laptops for a studio",
"laptops for a factory rollout" and "20 laptops for CAD". An integrated-graphics mini workstation is
rank 1 for gaming. The hypothesis shelves are labelled correctly but populated identically.

### 🟠 D6 — Retained purpose overwritten by a swap utterance

Journey E: after *"actually swap that for the workstation one instead, same quantity"*, the panel's
Purpose became that sentence. The original *"20 laptops for CAD work"* — the thing that makes the
swap judgeable — was destroyed.

### 🟠 D7 — Contradictory clarifier still live

Journey E1: *"I didn't find a match yet — what budget range should I stay within so I can look
again?"* on a turn that had just produced a five-configuration shortlist.
[`gates.py:41-48`](../src/app/services/recommendation_core/gates.py#L41), unchanged.

### 🟡 D8 — Trace badges still assert unearned confidence

`FRESHNESS: Current`, `COMPLETENESS: Complete`, `UNCERTAINTY: No material concern`,
`AUTHORITY: Authority unrecorded` — on a turn whose own body says *"No bounded workload entity was
proposed."*

### 🟡 D9 — Research & Fit contradicts the panel

Trace says *"No bounded workload entity was proposed"* while the panel lists three interpretations.

### 🟡 D10 — Catalogue data quality

253 products, **170 with NULL `category`**, **38 duplicate name groups**, still **no `mpn` column**.
The new high-end inventory landed (peak now **$14,999** — ZBook Fury; Zephyrus Duo $12,999) but with
`category: NULL`, so any category-scoped query still sees only the old 41 laptops capped at $5,999.
Duplicates exist for Legion Pro 7, OMEN MAX and Alienware 16X — one categorised, one not.

### 🟡 D11 — Runtime not "ready"

`ready: False`, mismatch `compatibility_cutover expected on, actual off`; and
`requirement_authority_ready: False` (credential / publisher policy / freshness SLA unset on this
process).

---

## 3. What could not be exercised

**Mock supplier rejection and confirmation, and the human gate, were never reachable** — D2 blocked
every path before a supplier enquiry could be raised. The backend logic exists and reads well; it is
untested end-to-end from the buyer surface. Same for add-ons (journey C died at the same gate) and
for BNPL/terms (no threshold surface encountered).

---

## 4. Roadmap

### Phase 0 — unblock the demo (hours, all contained)

| # | Fix | File:line |
|---|---|---|
| 1 | Require a post-purchase anchor before refusing "when will it arrive" | [App.tsx:1676](../frontend/src/App.tsx#L1676) |
| 2 | New commercial obligation while a question is pending ⇒ `interrupt`, not `answer` | [chat.py:3536-3541](../src/app/routers/chat.py#L3536) |
| 3 | Availability as a ranking term; zero-stock never rank 1 unqualified | [ProductShelvesPanel.tsx:140](../frontend/src/components/ProductShelvesPanel.tsx#L140) + shelf reducer |
| 4 | Suppress the empty-slot clarifier when a shortlist or cart exists | [gates.py:41-48](../src/app/services/recommendation_core/gates.py#L41) |
| 5 | Badge honesty — `Not assessed` / `Material` when nothing was interpreted | trace ontology + DecisionTrace |
| 6 | Preserve retained purpose across swap utterances | [case_research_plan.py:117](../src/app/services/case_research_plan.py#L117) region |

After 1 + 2, journeys B, C and D become runnable for the first time.

### Phase 1 — prove the supplier path end-to-end
7. Re-run bulk 15/30/40 ± add-ons; assert split / transfer / shortfall arithmetic.
8. Drive shortfall → supplier enquiry → **mock rejection** and **mock confirmation**; assert
   `AWAITING_APPROVAL` persists on escalate and that no state changes without the human gate.
9. Surface the RFQ draft body in the UI for review before send — the guards at
   [draft.py:53-65](../src/app/services/fulfillment/draft.py#L53) deserve to be visible; they are a selling point.

### Phase 2 — retrieval quality
10. Workload-discriminated shelves (D5) — the hypothesis labels exist, the ranking doesn't use them.
11. Calibrate the abstention threshold against an ordinary-query battery (D4). Target <5%.

### Phase 3 — catalogue integrity
12. Backfill `category` on 170 rows; dedupe 38 groups; add `mpn`, `warranty_type`, `gpu_tgp_w`,
    `os_edition`, `form_factor`, `device_class`.

### Phase 4 — commercial ladder
13. Constraint solver + always-visible stretch slate.
14. Finance threshold ≥ $5k → **trade credit / PO terms / lease**, entitlement checked against the
    existing Ariba/Coupa/Xero connectors. Indicative only, named human approver, permitted/prevented
    pair in the trace. Not BNPL at these order sizes.

### Phase 5 — external gates (unchanged)
15. `reviewed_by` on all 13 sources · 43×8 relevance labels · pilot identities · rollback window.

---

## 5. Verdict

The evidence architecture is now the strongest part of the system: the ladder is honest, the cache
works, research is real and free, and the RFQ send-cage is properly built. The failures in this run
are not architectural — they are **one over-broad frontend regex and one clarification-relation
misclassification**, which together make the bulk-procurement journey untestable and therefore make
a well-built backend look absent.

Fix those two and most of this document becomes re-runnable in an afternoon.
