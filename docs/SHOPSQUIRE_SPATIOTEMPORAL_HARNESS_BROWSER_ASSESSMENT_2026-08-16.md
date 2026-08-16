# ShopSquire spatiotemporal and harness browser assessment

Date: 2026-08-16

Environment: local portfolio runtime, live backend and SearXNG, synthetic commerce data

Authority: engineering assessment; no production or real-supplier authority

## Verdict

ShopSquire has working deterministic temporal, graph, forecast, market, procurement and model-
execution components. They are not yet coordinated by the main buyer conversation. The live buyer
journey currently turns a multi-destination, quantity/deadline/stock question into a workload-fit
research case, while the spatial allocation and commercial obligations remain prose.

Free external discovery is real. One novel browser turn dispatched three bounded SearXNG queries
and recorded zero paid calls. Candidate-publisher precision failed because the destination Cairns
was treated as the software/product term Cairn. Governance then behaved correctly: no candidate
was silently accepted, no official origin was fetched, no claims were established, and no cart or
supplier authority was granted.

## Live journey A: enrolled engineering workloads

Prompt:

> We need 60 engineering laptops: 40 to Sydney and 20 to Perth. They need to run
> Unreal Engine, large CAD models and simulation. At least 30 must arrive within four
> days. Which locations have stock, and would moving inventory leave a store with less
> than seven days of cover? Budget is AUD 220,000.

Observed:

- provisional exploration returned 10 exact configurations before research;
- buyer-authorized research fetched Autodesk and Epic canonical origins over the live network;
- 7 scoped requirements were accepted and the shortlist reranked to 6 configurations;
- external calls: 2; discovery calls: 0; official fetches: 2; paid calls: 0;
- product cards showed exact configuration stock and conditional fit;
- quantity 60, Sydney 40, Perth 20, four-day deadline, days-cover constraint and budget did not
  become a typed allocation/commercial plan;
- Decision Trace Commercial Journey was empty.

The zero discovery count is correct here: the software publishers were already enrolled, so the
canonical-origin rung ran before SearXNG.

Follow-up:

> Reduce Perth by 5 and move those units to Sydney. Keep total quantity at 60, preserve
> the four-day deadline and do not exceed the original AUD 220,000 budget.

Observed failure: the assistant asked what the products would mainly be used for. It did not apply
the independent location amendment to the retained case. The expected invariant was Sydney 45,
Perth 15, total 60, with workload/deadline/budget unchanged.

Evidence image: `2026-08-16-spatiotemporal-final-boss-gap.png`.

## Live journey B: novel workload and free discovery

Prompt:

> I need 18 laptops in Cairns by next Thursday for HEC-RAS 2D flood modelling and
> drone photogrammetry after a cyclone. Can current network stock arrive before the
> field team leaves?

Observed:

- provisional exploration returned 12 configurations with zero external calls;
- the platform classified the workload as unresolved and offered explicit discovery consent;
- after consent it dispatched 3 bounded SearXNG query axes;
- external/discovery calls: 3; official fetches: 0; paid calls: 0;
- 12 possible publisher origins were presented; 0 were accepted and 0 claims established;
- candidate origins were predominantly about Cairn/Cairns rather than HEC-RAS or
  photogrammetry, so publisher precision failed;
- the UI correctly described candidates as ownership-unverified and required case-only approval;
- no unsafe candidate was selected during this certification.

Decision Trace exposed additional contradictions:

- the top trust projection correctly said discovery completed and authority was proposal-only;
- the bounded plan still said `not executed` and `External calls: 0`;
- the outcome section correctly said live network and 3 external calls;
- `Buyer consent recorded: yes` appeared beside `External research authorized: no`;
- an older provider panel said research was not attempted although Tier 4 showed completion;
- paid calls were both `0` and `not recorded` in different projections;
- engine-health rows duplicated engine names and reported `not recorded`;
- the open-vocabulary model query proposal failed with `RuntimeError`, after which the fallback
  search over-weighted the destination token;
- `next Thursday` was retained only as `the field team leaves`, not a timezone-aware deadline.

Evidence image: `2026-08-16-novel-searxng-decision-trace.png`.

## Isolated component certification

- 58 temporal authority, PromiseGraph, supply graph, forecast, market projection, Hippograph and
  replay service tests passed.
- 27 Decision Trace market/procurement/Hippograph presentation tests passed.
- 18 model gateway, artifact verification, durable AgentRunEvent and safe replay tests passed.
- The real-backend seeded procurement Playwright journey passed in 33.9 seconds: a shortfall RFQ
  was drafted, human-gated, bitemporally audited and rerouted to a different approved supplier when
  the product changed.

That procurement certificate proves explicit APIs and projections. It does not prove that a natural-
language shopping case automatically creates the same procurement case.

## Current architecture

```text
BUYER UTTERANCE
      |
      +--> workload interpretation --> official research --> product-fit shelves
      |
      +--> quantity/deadline fragments retained in trace
      |
      X    no typed SpatioTemporalQuery / allocation coordinator

SEPARATE WORKING SUBSYSTEMS
      |
      +--> temporal authority + operational calendars
      +--> supply graph + PromiseGraph
      +--> demand forecast + market projections
      +--> Hippograph typed/bitemporal journey edges
      +--> fulfilment/RFQ workflow
      +--> ModelExecutionGateway + durable AgentRunEvent + safe replay
```

## Target coordinator

```text
BUYER UTTERANCE
      |
      v
MODEL GATEWAY: semantic proposal only
      |
      +--> workload hypotheses
      +--> SpatioTemporalQuery
      +--> commercial amendments
      +--> explicit ambiguity objects
      |
      v
TYPED CASE MERGE
      |
      +--> purpose/workload requirements
      +--> quantity + destination allocations
      +--> timezone-aware deadline + as_of
      +--> budget/currency
      +--> stock-retention/days-cover policy
      |
      v
DETERMINISTIC SERVICES
      |
      +--> product fit
      +--> ATP/allocation
      +--> temporal/calendar feasibility
      +--> PromiseGraph routes
      +--> market/forecast evidence
      +--> supplier shortfall/RFQ proposal
      |
      v
ONE ADJUDICATED DECISION PROJECTION
      |
      +--> current facts
      +--> unknown/not disclosed
      +--> selected option + alternatives
      +--> prevented actions
      +--> evidence/agent run links
      |
      v
EVIDENCE-BOUND NARRATION
```

## Ordered implementation roadmap

1. Define `SpatioTemporalQuery` and typed case amendments for destinations, per-destination
   quantity, deadline expression/timezone, `as_of`, budget and inventory-retention policy.
2. Merge follow-up amendments by field. Changing Perth quantity must not erase workload, Sydney,
   total, deadline or budget.
3. Separate semantic subject terms from spatial terms before query generation. Generate query axes
   for HEC-RAS requirements and photogrammetry requirements; Cairns belongs only to fulfilment.
4. Add semantic publisher-ownership scoring: named software/vendor match, official-domain evidence,
   requirements-page quality and negative score for destination-only matches.
5. Require a minimum ownership score before rendering `Use for this case`; otherwise show no
   credible publisher and offer upload/link/manual evidence.
6. Feed typed quantity/destinations/deadline into allocation, temporal authority, PromiseGraph and
   commercial reducers after product-fit candidates exist.
7. Project a shortfall-only synthetic RFQ option; retain explicit supplier-send and cart gates.
8. Replace multiple stale observer renderings with one adjudicated execution/evidence/decision
   projection. Older observers can remain drill-down evidence but cannot set badges.
9. Add a typed `AgentRunEvent`/tool-result link to Decision Trace: deployment/artifact/prompt hashes,
   accepted/timeout/fallback state and replay identifier, without prompts, chain-of-thought or PII.
10. Add browser acceptance for the seven-turn final-boss journey and metamorphic variants.

## Acceptance invariants

- provisional exploration makes zero external and paid calls;
- novel authorized discovery records actual query hashes, engines, origins and paid calls = 0;
- destinations never enter workload/publisher query terms unless semantically part of the workload;
- no candidate publisher becomes evidence without case/tenant policy acceptance;
- relative dates resolve to explicit timezone-aware windows;
- multi-turn changes modify only named fields;
- quantities sum exactly and stock cannot be double allocated;
- sales decline remains unresolved when stockout censoring is material;
- supplier availability is not a delivery promise;
- disruption effects require a verified exposure path;
- future-observed evidence cannot enter historical replay;
- model runs propose/interpret/narrate only and cannot mutate RFQ/cart/payment/shipment;
- a slow, rejected or unsupported model output falls back to deterministic projection;
- Decision Trace presents one internally consistent truth state.

## Additional defects observed

- cart requests from the local Vite origin failed CORS while shopping-case APIs succeeded;
- Decision Trace first requests a legacy decision endpoint that returns 404, then falls back to the
  working query endpoint;
- visible mojibake around middle-dot separators remains in Decision Trace presentation;
- `DecisionTrace.tsx` remains 4,188 lines despite extracted presentation components.
