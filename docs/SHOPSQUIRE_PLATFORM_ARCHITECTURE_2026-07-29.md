# ShopSquire Platform Architecture

## Product boundary

ShopSquire is an integration-native decision and bounded-action layer. It can provide
native commerce intelligence where a client lacks it, but it does not attempt to replace
an authoritative ERP, OMS, WMS, planning, commerce or CRM platform.

```text
 existing authority                         ShopSquire authority
 ------------------                         ---------------------
 customer/product master  ----read---->     identity projections
 orders and inventory      ----read---->     forecasts and proposals
 receipts and invoices     ----read---->     reconciliation and outcomes
 approved PO/payment       <---gated----     typed authorized execution
```

An upstream platform can replace a native ShopSquire read model as long as it satisfies
the same versioned contract, provenance and tenant requirements.

## End-to-end authority path

```text
 [source]
    |
    | signed tenant, source identity, event time, availability time
    v
 [observation] -------- invalid/untrusted --------> [quarantine]
    |
    | immutable evidence reference
    v
 [canonical fact projection] ---- conflict -----> [incomparable / needs review]
    |
    +-------------------------+
    |                         |
    v                         v
 [prediction]             [market hypothesis]
    |                         |
    +-----------+-------------+
                v
          [typed proposal]
                |
      +---------+----------+
      |                    |
      v                    v
 [policy allows]     [human authorization]
      |                    |
      +---------+----------+
                v
        [idempotent execution]
                |
                v
       [outcome + calibration]
```

No LLM output is a canonical fact, authorization or payment instruction.

## 1. Buyer and recommendation path

```text
 buyer message / image
          |
          v
 input security + observation extraction
          |
          v
 intent and bounded durable preferences
          |
          v
 candidate retrieval -> inventory/lifecycle guards -> lexicographic ranking
          |                                             |
          |                                  optional shadow evidence
          |                                             |
          +---------------- Hippograph recall <---------+
          |
          v
 response contract -> narrative/payload consistency -> Decision Trace
```

Responsibilities:

- models may parse intent, extract constraints and draft explanations;
- catalog identity and availability come from governed services;
- lifecycle and policy gates may exclude or block products;
- explanations must refer to products and facts in the response contract;
- recalled feedback is evidence, not an unrestricted ranking objective.

## 2. Forecast and inventory path

```text
 orders + latent demand + inventory events + supply
                         |
                         v
            canonical append-only event ledger
                         |
                         v
       rebuildable location / lot / availability projection
                         |
                         v
 rolling-origin lead-time evaluation
                         |
       +---------+---------+----------+------+
       v         v         v          v      v
 seasonal     EWMA     Croston/SBA    TSB  undefined
 naive
       +---------+---------+----------+------+
                         |
             error + interval + FVA evidence
                         |
                         v
              replenishment proposal
 demand distribution | lead time | ATP | incoming | MOQ | pack/UoM | price
```

Important semantics:

- ATP is distinct from on-hand and depends on an explicit policy;
- stock cannot appear without a receipt, transfer or adjustment;
- corrections and reversals preserve prior accepted observations;
- forecast accuracy and decision utility are reported separately;
- synthetic histories remain `simulation_only`.

## 3. Market and supply intelligence path

```text
 official/public signal          supplier / operational evidence
 licence + revision + scope      quote + lead time + receipt + invoice
              |                              |
              +---------------+--------------+
                              v
                contradiction and scope grouping
                              |
                              v
       time-valid product/component/supplier/facility/lane graph
                              |
                              v
             dependency-path retrieval and exposure check
                              |
                              v
       bounded impact range + alternatives + missing evidence
                              |
                              v
       monitor | request confirmation | compare substitute | propose RFQ
```

A commodity price, recall or PESTEL event is not automatically evidence that a SKU is
exposed. The system requires a compatible dependency path and retains alternative
explanations. Public-source evidence is advisory unless stronger product, supplier,
facility or contractual evidence exists.

## 4. Procurement and supplier communication path

```text
 replenishment need / buyer requirement / supply hypothesis
                              |
                              v
                  immutable case-context snapshot
                              |
                              v
          supplier candidates + comparable landed economics
                              |
                              v
                     governed RFQ proposal
                              |
                        authorization gate
                              |
                              v
                  durable communication outbox
                              |
                              v
 supplier reply -> connector identity -> inbox/evidence -> quarantine gate
                              |
                              v
                     MessageObservation
                              |
                              v
               case correlation and re-evaluation
```

Supplier content can add evidence or trigger re-evaluation. It cannot directly alter a
quote, purchase order, payment or inventory state. Buyer messages similarly cannot
authorize consequential financial actions merely through text.

## 5. Party and account intelligence

```text
 customer / supplier / contact observations
                    |
                    v
       tenant-scoped Party + identifiers
                    |
                    v
        links, timeline and confidence
                    |
                    v
             merge/split proposal
                    |
          four-eyes authorization
                    |
                    v
       reversible append-only redirect
```

ShopSquire provides account intelligence needed for commerce decisions rather than a
generic sales-pipeline CRM replacement. Authoritative account facts are not overwritten
by extracted conversation observations.

## 6. Hippograph feedback architecture

```text
 trace edges       conversion outcomes       findings       human feedback
     |                     |                     |                 |
     +---------------------+---------------------+-----------------+
                                   |
                                   v
                       tenant-scoped projection
                                   |
                    canonical entities + typed edges
                                   |
                                   v
                  reward-weighted multi-hop recall
                       bounded per-hop decay
                                   |
                  +----------------+----------------+
                  v                                 v
         agent/operator context              ranking experiment
           advisory by default         treatment only, capped delta
                                                    |
                                             audit + revert
```

Hippograph currently provides:

- tenant-required database projection;
- entity canonicalization;
- trace, conversion, catalog, finding and optional human-feedback edges;
- bounded reward and multi-hop decay;
- filtered product, brand, finding and segment recall;
- cold-start observability and optional low-weight catalog reachability;
- shadow counterfactuals and reversible ranking nudges.

Before it can support stronger autonomy it still needs:

- independent relevance labels and a positive, replicated offline result;
- temporal train/test separation and leakage checks;
- calibration by cohort, cold-start and lifecycle regime;
- visible provenance for every recalled path;
- Sybil-resistance beyond distinct local identifiers;
- drift, graph-growth and stale-edge controls;
- a design-partner shadow experiment with guardrail metrics;
- proof that any lift survives against the V2 baseline and does not degrade diversity,
  margin, availability, fairness or safety.

Until then it should remain an evidence memory and experiment candidate, not a hidden
optimization authority.

## 7. Security and trust control plane

```text
 untrusted input
      |
      v
 connector identity -> tenant binding -> content/evidence separation
      |                                      |
      | invalid                              | suspicious
      v                                      v
   reject                                quarantine
                                               |
                                               v
 model/tool output -> schema -> policy -> budget -> authorization -> action
                          |         |             |
                          v         v             v
                       abstain   timeout       audit record
```

Controls include:

- fail-closed identity at consequential boundaries;
- immutable raw evidence separated from sanitized observations;
- source licensing, revision, freshness and completeness;
- typed unknown and incomparable outcomes;
- prompt-injection and data-poisoning regression tests;
- per-action budgets, deadlines, retries and stalled-job recovery;
- human authorization for material commitments;
- counterfactual replay and kill switches.

Security claims remain scoped. Local tests prove specified invariants; they do not prove
that every attacker, provider or production configuration is safe.

## 8. Runtime composition

```text
 Storefront :5173         Admin :3001
         \                   /
          +------ FastAPI :8080 ------+
                    |                 |
              PostgreSQL           Redis
                    |                 |
              migrations       jobs / cache / state
                                      |
                               worker + scheduler
                                      |
                         bounded external connectors
```

The frontends are consumers of versioned API contracts. Business authority belongs in
backend services and policy records, not in UI state. The admin surface may approve or
inspect an action; it should not silently invent one.

## Decision Trace information architecture

The current leaf panels should be retained but grouped through progressive disclosure:

```text
 Decision
   Summary | Events | Execution

 Reasoning
   Why | Intent | Memory | Complexity

 Evidence and risk
   Evidence | Multimodal | Security

 Commercial journey
   Market intelligence | Procurement

 Audit and technical
   Audit trail | Raw
```

This is a navigation refactor, not a data migration. A safe implementation keeps existing
leaf identifiers and fetch effects, adds a section-to-leaf view model, preserves old deep
links, and tests that every former tab remains reachable with identical request counts.

Each visible panel should answer:

1. What happened?
2. Why?
3. What evidence and uncertainty supported it?
4. What authority did the component have?
5. What changed or was prevented?
6. What is the next permitted action?

## Proof ladder

```text
 unit contract
      -> integration contract
      -> deterministic replay
      -> adversarial regression
      -> production-shaped local stack
      -> hosted CI / PostgreSQL artifacts
      -> live provider certification
      -> design-partner shadow pilot
      -> controlled business outcome
```

Evidence must be described at the level actually reached. Passing synthetic replay does
not imply business lift; a local provider protocol test does not imply live-provider
certification.
