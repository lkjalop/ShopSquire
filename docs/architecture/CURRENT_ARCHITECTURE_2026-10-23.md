# Current ShopSquire architecture

Reviewed **23 October 2026** against publication base `a4cbf28e`. This maps implemented components and control boundaries. Arrows do not certify deployed integration; see the [status and evidence](../REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md).

```text
                             EXPERIENCE
 +-------------------------+ +--------------------------+ +-------------------+
 | Buyer storefront        | | Merchant / admin React   | | Suppliers / feeds |
 | chat, uploads, shelves  | | trace, inventory, cases  | | external sources  |
 +------------+------------+ +------------+-------------+ +---------+---------+
              | signed buyer / scoped operator                     |
              v                          v                          v
 +-------------------------------------------------------------------------+
 | FastAPI admission and trust boundary                                    |
 | tenant membership | role/session | request/case revision | replay checks |
 | upload / URL / security checks | explicit feature and provider gates     |
 +----------------------------------+--------------------------------------+
                                    |
                      CANONICAL CONVERSATION / CASE
 +-------------------------------------------------------------------------+
 | Turn transition + deterministic case updates                            |
 | quantity | currency | budget scope | destination | workload | corrections|
 | evidence proposals -> accepted/rejected claims -> fit / qualification    |
 +-------------------------+----------------------+------------------------+
                           |                      ^
                           v                      | scoped recall / state
 +------------------------------------------------|------------------------+
 | Recommendation core                            |                        |
 | model route proposal -> deterministic validation -> taxonomy retrieval  |
 | typed stage plan -> fit -> bulk economics -> fulfillment -> explanation |
| declared dependencies / cancellation / outcomes -> evidence adjudication |
 +------------------------+-----------------------+------------------------+
                          |                       |
                          v                       v
              answer / refusal / shelves     bounded draft / proposal
                          |                       |
                          |              COMMERCIAL AUTHORITY
                          |     +------------------------------------------+
                          |     | price / currency / UoM / current stock   |
                          |     | case revision / exact effect / approval |
                          |     | policy and provider effect gate        |
                          |     +----------------------+-------------------+
                          |                            |
                          |                  outbox / signed task / worker
                          |                            |
                          |                            v
                          |                sandbox / configured adapter
                          |               publication may be unconfirmed
                          |               durable recovery remains open
                          v                            v
 +-------------------------------------------------------------------------+
 | Decision Trace / audit / replay / evaluation                            |
 | proposals, authority and blocked/error outcomes remain distinguishable  |
 +-------------------------------------------------------------------------+

                         DATA / INTELLIGENCE LANES
 +-----------------------+ +-----------------------+ +----------------------+
 | SQLAlchemy + SQL      | | Redis                 | | Hippograph           |
 | durable cases, claims| | tenant-scoped cache   | | advisory recall      |
 | inventory, audit,   | | queues / coordination | | relationships and    |
 | prices, outbox state| | not fact authority    | | feedback projections |
 +-----------------------+ +-----------------------+ +----------------------+

 Research / market adapters -> source / licence / time / scope checks
      -> admitted findings -> reasoning / citation -> ordinary chat
      [components exist; this complete positive chain remains open]

 Forecast / replenishment -> comparable history / baseline -> bounded proposal
      [synthetic/replay evidence; no real-world improvement claim]
```

## Source map

| Boundary | Representative source |
|---|---|
| Composition / lifecycle | [main.py](../../src/app/main.py) |
| Conversation / transitions | [chat.py](../../src/app/routers/chat.py), [turn_transition.py](../../src/app/services/turn_transition.py) |
| Routing and stages | [core.py](../../src/app/services/recommendation_core/core.py), [stage plan](../../src/app/services/recommendation_core/post_retrieval_stage_plan.py) |
| Shortfall draft | [supplier_enquiry_journey.py](../../src/app/services/supplier_enquiry_journey.py) |
| Stock / authority | [inventory_transactions.py](../../src/app/services/inventory_transactions.py), [fulfillment_cases.py](../../src/app/routers/fulfillment_cases.py) |
| Market projection / agent | [market_projection.py](../../src/app/services/market_projection.py), [market_intelligence_agent.py](../../src/app/services/market_intelligence_agent.py) |
| Evaluation / browser oracle | [ragas_eval.py](../../src/app/services/ragas_eval.py), [turnOracle.ts](../../frontend/e2e/helpers/turnOracle.ts) |

SQLite tests do not establish PostgreSQL contention correctness. Redis profiles require native distributed evidence. External models/search and graph backends are optional configured dependencies, not mandatory for every deterministic demonstration.

The publication base records phase order, dependency references and stage outcomes. Mutation snapshots/rollback, dependency-ID validation and propagation of blocked dependencies are local work under review; they are not claimed as integrated guarantees here.

## Proposed product-contract clarification

```text
 Buyer intent
     |
     +-- ordinary preferences -> catalog candidates + explicit fit uncertainty
     |                           [proposed; requires positive UI contracts]
     |
     +-- verifiable workload -> accepted requirements + current evidence
                                -> qualified result OR precise unresolved state
                                [implemented machinery; integration gaps remain]

 Neither branch grants purchase, supplier-send or payment authority.
```

Validate this proposal against browsing, qualified workloads, corrections and evidence withdrawal. It does not authorize unsupported fit claims or bypassing evidence gates.
