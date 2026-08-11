# Governed Degradation + Commercial Ladder — Architecture and Roadmap

**Date:** 2026-08-09 · Design memo
**Answers:** surface *why* discovery degraded, fall through to next-best, budget-insufficient handling, finance options, all provable in Decision Trace

---

## 1. Is the idea right?

Yes — and it is the strongest product instinct in this thread. Specifically:

**"Surface why it failed to prove the platform works."** This is the whole thesis applied to your
own infrastructure. A system that says *"discovery degraded: 4 of 6 engines returned CAPTCHA,
0 allowlisted results, 0 paid calls — here are three other routes"* is demonstrating governance.
A system that says *"could not complete"* is demonstrating nothing. Same underlying failure, opposite
credibility.

**"Fall through to next-best rather than dead-end."** Correct, and it is the difference between an
outage and a workflow.

**"If budget is insufficient, keep the stretch goal visible."** Correct, and it is the missing
constraint-conflict engine.

**"Finance options need human oversight."** Correct instinct.

### One material correction: BNPL is the wrong instrument here

Not a nitpick — it changes the design.

1. **BNPL is regulated consumer credit.** In Australia it now sits under the credit regime:
   a licensed provider, responsible-lending obligations, disclosure. ShopSquire must not
   *originate* or *offer* credit. It can surface an **eligibility signal** and **hand off** to a
   licensed provider. That distinction is the difference between a feature and a compliance
   incident.
2. **At your order sizes BNPL doesn't apply anyway.** A 30-unit order is $180k. BNPL is a
   consumer-scale instrument. The B2B primitives for that number are **net-30/60 terms, PO-based
   invoicing, equipment finance / leasing, and staged payment against milestones** — and you
   already have the rails: `routers/billing.py`, `erp/connectors/ariba.py`, `coupa.py`,
   `connectors/accounting/xero.py`.

So the idea survives and gets stronger: **payment flexibility unlocks a budget-constrained deal** —
you just want *trade credit*, not BNPL. Keep consumer BNPL as an eligibility hand-off for the
sub-$5k single-unit path if you want it at all.

**You are not wrong and not incompetent.** You have repeatedly identified the real architectural
gap before the analysis did — the null class, the multi-turn loss, the "retroactive URL defeats the
purpose" objection, and now this. The instrument choice is a domain detail, not a thinking error.

---

## 2. The architecture

### 2.1 Whole picture

```
                          BUYER OUTCOME
        "simulate a PLC-controlled factory and cyberattacks on the OT network,
                          30 units, 4 days, ~$60k"
                                    |
              +---------------------+---------------------+
              |                                           |
              v                                           v
    ┌───────────────────────┐                  ┌───────────────────────┐
    │ INTERPRETATION        │                  │ COMMERCIAL FRAME      │
    │ model proposes 1..3   │                  │ qty · deadline ·      │
    │ hypotheses, clamped   │                  │ budget · destination  │
    │ to workload hierarchy │                  │ (buyer-stated only)   │
    └───────────┬───────────┘                  └───────────┬───────────┘
                │  NO EXTERNAL CALLS. This already works.  │
                v                                          │
    ┌───────────────────────────────────────────┐          │
    │ SHARED FLOOR   = ∩ of hypotheses          │          │
    │ DIVERGENT AXIS = where they disagree      │          │
    │   -> eliminates most of catalogue now     │          │
    │   -> yields the ONE question worth asking │          │
    └───────────┬───────────────────────────────┘          │
                v                                          │
    ┌───────────────────────────────────────────┐          │
    │ EVIDENCE LADDER  (stop at first success)  │          │
    └───────────┬───────────────────────────────┘          │
                v                                          │
                (see 2.2)                                  │
                │                                          │
                v                                          v
    ┌──────────────────────────────────────────────────────────────┐
    │ FIT VERDICT per SKU:  meets / conditional / fails / unknown   │
    │   evidence-backed predicates only, provenance per predicate   │
    └───────────┬──────────────────────────────────────────────────┘
                v
    ┌──────────────────────────────────────────────────────────────┐
    │ CONSTRAINT SOLVER  — four variables, name the one that moves  │
    │   floor · budget · quantity · date                            │
    └───────────┬──────────────────────────────────────────────────┘
                v
                (see 2.3)
                │
                v
    ┌──────────────────────────────────────────────────────────────┐
    │ HUMAN-GATED COMMERCIAL ACTION                                 │
    │   cart · RFQ · terms request · finance referral               │
    │   nothing outbound without explicit confirmation              │
    └──────────────────────────────────────────────────────────────┘
```

### 2.2 Evidence ladder — every rung reports *why* it stopped

```
 TIER            MECHANISM                        ON FAILURE, RECORD
 ────────────────────────────────────────────────────────────────────────────
 0  CACHE        (source_id, entrypoint)          cache_miss
                 TTL = freshness_sla_hours        £0
                        │ miss
                        v
 1  ENROLLED     canonical_entrypoint fetch       origin_unreachable | http_4xx
                 10 approved publishers           £0
                        │ source not enrolled for this concept
                        v
 2  BUYER        upload PDF/TXT/PNG · paste URL   no_upload_provided
                 authority=approved_tenant_doc    £0
                        │ none supplied
                        v
 3  VENDOR       named product -> official site   vendor_not_resolved
                 (Wikidata P856, free)            £0
                        │ unresolved / unnamed
                        v
 4  DISCOVERY    self-hosted metasearch           engines_captcha: [brave,
                 engines: mojeek,bing               startpage,duckduckgo,qwant]
                 NO site: operator                zero_allowlisted_results
                        │ degraded                £0
                        v
 5  PAID         one licensed provider            provider_error | budget_declined
                 escalation-gated, opt-in         £ ~0.005/query
                        │ unavailable / declined
                        v
 6  ABSTAIN      provisional shortlist,           material_unknowns: [...]
                 explicitly unverified            £0
                 + 3 concrete buyer moves
```

Rule: **a rung never fails silently.** Each emits an `execution_status` + `rejection_reason` —
which [`research_contracts.py:201-237`](../src/app/services/recommendation_core/research_contracts.py#L201) already models and *validates*
(`rejected_admission` requires a `rejection_reason`). The schema is built; nothing renders it.

### 2.3 Constraint solver — when budget can't meet the floor

```
  floor $2,899/unit × 30 = $86,970        budget stated $60,000        GAP $26,970
  ────────────────────────────────────────────────────────────────────────────────
   MOVE            EFFECT                                        AUTHORITY
   ────────────────────────────────────────────────────────────────────────────────
   REDUCE QTY      20 × $2,899 = $57,980        within budget     buyer, reversible
   SUBSTITUTE      SKU-X $1,999 · meets 3 of 4  FAILS ram_gb      shown, not offered
                   -> would not run the workload
   SPLIT           7 now in budget · 23 on dated commitment       buyer + operator
   SOURCE          supplier RFQ at floor, 30 units                human send only
   TERMS           net-30/60 · PO invoicing · lease/equipment     finance + human
                   finance -> spreads $86,970, does not
                   reduce it
   STRETCH         keep the $86,970 slate visible, labelled
                   "meets floor · over stated budget"             always visible
```

**The stretch slate never disappears.** Budget filters *presentation*, never *truth*. A machine that
meets the workload floor stays on screen, marked over-budget — because "cheaper thing that cannot do
the job" is not an answer, and hiding the capable option is how a buyer ends up with 30 unusable
laptops.

### 2.4 Finance rung — what it may and may not do

```
  order_total >= FINANCE_THRESHOLD (e.g. $5,000)
        |
        v
  ┌──────────────────────────────────────────────────────────────┐
  │ SHOPSQUIRE MAY:                                              │
  │   compute the total and the gap                              │
  │   show indicative structures (net-30/60, PO, lease, staged)  │
  │   check tenant entitlement / existing credit terms (Ariba,   │
  │     Coupa, Xero connectors already present)                  │
  │   draft a terms request for human review                     │
  │                                                              │
  │ SHOPSQUIRE MUST NOT:                                         │
  │   originate or offer credit                                  │
  │   quote a rate, APR, or approval                             │
  │   imply eligibility                                          │
  │   send anything to a finance provider without a human        │
  └──────────────────────────────┬───────────────────────────────┘
                                 v
                    HUMAN APPROVER (named, logged)
                                 |
                                 v
                LICENSED PROVIDER / EXISTING TENANT TERMS
```

Every one of those lines belongs in the trace as an explicit permitted/prevented pair — same shape
as the existing `state_prevented` tuple.

---

## 3. Decision Trace panel — the proof surface

```
┌─ DECISION TRACE ─────────────────────────── e39ce1c7-25c ── SSE ──┐
│ AUTHORITY        FRESHNESS       COMPLETENESS   UNCERTAINTY       │
│ Platform         Not assessed    Partial        Material          │
├───────────────────────────────────────────────────────────────────┤
│ EXECUTION                EVIDENCE          DECISION      COST     │
│ degraded_upstream        material_gaps     provisional   £0.00    │
│                                                          0 paid   │
├─ WHY DISCOVERY DEGRADED ──────────────────────────────────────────┤
│ tier 0  cache          MISS      (source_id, entrypoint)          │
│ tier 1  enrolled       2 of 3 fetched                             │
│           learn.microsoft.com/…/host-hardware-requirements  200   │
│           docs.factoryio.com/manual/system-requirements/    200   │
│           attack.mitre.org/matrices/ics/          not attempted   │
│ tier 4  discovery      DEGRADED                                   │
│           engines queried : mojeek, bing, brave, startpage, ddg   │
│           CAPTCHA/blocked : brave, startpage, duckduckgo, qwant   │
│           responded       : mojeek, bing                          │
│           allowlisted hits: 0                                     │
│           dispatched      : 3    billing_class: free              │
│ tier 5  paid           NOT ATTEMPTED — not enrolled               │
│                                                                   │
│ This is an infrastructure fact, not an evidence conclusion.       │
│ No requirement was inferred from an unavailable source.           │
├─ WHAT UNBLOCKS IT ────────────────────────────────────────────────┤
│  [Upload requirements]  [Paste vendor link]  [Enter specs]        │
│  [Continue provisionally]                                         │
├─ COMMERCIAL ──────────────────────────────────────────────────────┤
│ floor          $2,899/unit × 30 = $86,970                         │
│ stated budget  $60,000                    gap $26,970             │
│ moves offered  reduce-qty · split · RFQ · terms                   │
│ finance        eligible for terms review (>= $5,000)              │
│                indicative only · no rate quoted · human required  │
├─ AUTHORITY LEDGER ────────────────────────────────────────────────┤
│ permitted   catalog exploration · provisional shortlist ·         │
│             terms-request draft                                   │
│ prevented   verified-fit claim (evidence incomplete)              │
│             autonomous cart mutation                              │
│             supplier send (human only)                            │
│             finance referral (human approver required)            │
└───────────────────────────────────────────────────────────────────┘
```

That panel is the demo. It says: *we tried six routes, here is exactly what each returned, we spent
nothing, we invented nothing, and here are your next moves.* A CAPTCHA on stage stops being an
embarrassment and becomes the slide that proves the governance is real.

---

## 4. Reordered roadmap

### Phase 0 — make degradation legible (days, no new capability)
1. **Per-tier `execution_status` + `rejection_reason` through to the UI.** Schema exists at
   [research_contracts.py:201](../src/app/services/recommendation_core/research_contracts.py#L201); render it.
2. **Engine-level detail on the discovery rung** — queried / responded / blocked, with
   `zero_allowlisted_results` distinct from `engines_captcha`.
3. **Badge honesty** — `FRESHNESS: Not assessed` when nothing fetched, `UNCERTAINTY: Material` when
   blocked for uncertainty.
4. **Never render a refusal inside "HELP ME NARROW THIS DOWN"** — that affordance takes questions only.
5. **SearXNG config**: `engines: mojeek,bing`, drop the `site:` operator (it zeroes those engines).

### Phase 1 — complete the ladder so it always lands somewhere
6. **Tier 0 cache**, keyed `(source_id, canonical_entrypoint)`, TTL from `freshness_sla_hours`.
7. **Tier 1 canonical-first** for the 10 approved sources — no discovery needed, fixes the MITRE
   `/analytics/` precision issue as a side effect.
8. **Tier 2 upload→claim producer** emitting `authority: approved_tenant_document` — the compiler
   already accepts it ([requirement_compiler.py:21](../src/app/services/recommendation_core/requirement_compiler.py#L21)); nothing produces it. Plus paste-a-link.
9. **Tier 6 abstain UX** — provisional slate + three concrete moves, never a dead end.

### Phase 2 — commercial reasoning
10. **Constraint solver** — four variables, name the one that moves, enumerate computed moves.
11. **Stretch slate always visible**, labelled over-budget. Budget filters presentation, not truth.
12. **Multi-act narration + pending-plan surface** — closes screenshots 51 and 53.

### Phase 3 — finance, carefully
13. **Threshold + entitlement check** against existing Ariba/Coupa/Xero terms. Indicative structures
    only; no rate, no APR, no eligibility claim.
14. **Human approver in the loop**, named and logged, before any referral leaves the system.
15. **Trace the permitted/prevented pair explicitly.**

### Phase 4 — tail coverage
16. **Tier 3 vendor-resolution** (Wikidata P856) for named products.
17. **Enrollment backlog** from real traffic — unenrolled terms become the registry roadmap.
18. **Tier 5 paid provider** behind the escalation gate, if 0–4 measurably miss. Budget $5–20/month.

### Phase 5 — external gates (unchanged, calendar-bound)
19. 43 × 8 relevance labels with named reviewer · `reviewed_by` on all 13 sources · pilot identities
    · rollback window · V2 retirement review last.

---

## 5. What changed in my advice

Previously I put canonical-first at the top as if it solved discovery. It doesn't — it solves the
enrolled case. The reorder above puts **making degradation legible** first, because that is what
turns the current failure into the demo, costs nothing, and is true regardless of which discovery
mechanism you eventually choose.
