# ShopSquire architecture and current authority boundaries

Reviewed 25 October 2026. This describes implemented components across the draft repair branch and explicitly identified local integration work. Arrows describe wiring; qualification is in the [execution delta and roadmap](../EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md). The earlier [23 October architecture](CURRENT_ARCHITECTURE_2026-10-23.md) remains historical evidence.

```text
 BUYER                                  OPERATOR / ADMIN
 chat, uploads, shelves, reload          inventory, evidence, reviewed draft
           | native signed session             | person + tenant role
           +-------------------+---------------+
                               v
 +-----------------------------------------------------------------------+
 | FASTAPI ADMISSION                                                     |
 | identity / tenant / case / revision / replay / upload-URL security      |
 +------------------------------+----------------------------------------+
                                v
 +-----------------------------------------------------------------------+
 | CANONICAL CASE STATE (SQL)                                             |
 | requested items + unit basis | currency / budget scope | destinations  |
 | workload + amendments | accepted evidence | material case revision     |
 +-----------+-------------------------+----------------------+----------+
             |                         |                      |
             v                         v                      v
 +----------------------+ +-------------------------+ +------------------+
 | RECOMMENDATION CORE  | | RESEARCH / MARKET        | | STOCK / COST     |
 | proposed typed route| | consent + source policy | | current holds    |
 | taxonomy sellability| | provenance + time/scope | | available / short|
 | stage dependencies  | | admitted measurements   | | same-currency    |
 | fit / uncertainty   | | question-relevant claims| | comparison       |
 +----------+-----------+ +------------+------------+ +--------+---------+
            |                         |                       |
            +-------------------------+-----------------------+
                                      v
 +-----------------------------------------------------------------------+
 | CASE TASK DELIVERY                                                    |
 | response / useful shelves / explicit unknowns / scoped citations       |
 | exact shortfall -> one immutable supplier draft version + content hash |
 +--------------------------+-----------------------------+--------------+
                            |                             |
                            v                             v
                 buyer preview + reload           operator review / edit
                                                          |
                                         edit -> new version, revoke approval
                                                          |
                                                          v
 +-----------------------------------------------------------------------+
 | COMMERCIAL AUTHORITY                                                  |
 | exact current artifact | independent person | scoped policy / expiry  |
 | price preview != executed effect; unknown landed costs remain unknown |
 +----------------------------------+------------------------------------+
                                    |
                                    v
                   durable outbox / signed work / idempotency
                                    |
                                    v
             fictional supplier + sandbox transport [qualified demo]
             configured real adapter [provider qualification still open]
                                    |
                                    v
                  accepted / delivered / unknown / reconciliation
                       [provider evidence must distinguish these]

 MEMORY / STORES                          OBSERVABILITY / EVALUATION
 +------------------------------------+  +-------------------------------+
 | SQL: durable revisioned case,      |  | trace / operation / source / |
 | evidence, inventory, draft, outbox |  | policy / approval / effect   |
 | Redis: scoped indexed memory/cache|  | receipt, typed failure       |
 | atomic publish/read/erase contract|  | Prometheus actual scrape    |
 | Hippograph: advisory relationships|  | held-out eval: unmeasured if|
 | and recall, not fact authority    |  | required evidence is absent |
 +------------------------------------+  +-------------------------------+
```

## Source entry points

| Boundary | Source |
|---|---|
| Composition/lifecycle | [main.py](../../src/app/main.py), [runtime lifecycle](../../src/app/bootstrap/runtime_lifecycle.py) |
| Canonical routing/state | [turn router](../../src/app/services/recommendation_core/turn_router.py), [case task delivery](../../src/app/services/case_task_delivery.py) |
| Catalogue boundary | [case catalogue candidates](../../src/app/services/case_catalog_candidates.py) |
| Admission and relevance | [market agent](../../src/app/services/market_intelligence_agent.py), [question relevance](../../src/app/services/market_question_relevance.py), [supplier evidence](../../src/app/services/supplier_market_evidence.py) |
| Price basis | [commercial reducer](../../src/app/services/commercial_decision_reducer.py), [pricing preview](../../src/app/routers/pricing.py) |
| Shared reviewed artifact | [draft storage](../../src/app/services/supplier_enquiry_drafts.py), [journey](../../src/app/services/supplier_enquiry_journey.py), [operator API](../../src/app/routers/operator_supplier_enquiries.py), [review UI](../../frontend/src/components/SupplierEnquiryPanel.tsx) |
| Person-bound authority | [person approval](../../src/app/services/fulfillment/person_approval.py) |
| Memory/cache | [memory](../../src/app/services/memory.py), [semantic cache](../../src/app/services/semantic_cache.py) |
| Privacy boundary | [privacy API](../../src/app/routers/privacy.py), [separate-process controls](../../tests/integration/test_privacy_multi_instance_http.py) |

The all-plane privacy cascade, product-agnostic unit/pack normalization, complete landed quote, production independent-person deployment, provider reconciliation and final-candidate endurance are open. SQL compatibility bootstrap is not a replacement for migration/restore qualification. SQLite evidence does not establish PostgreSQL contention correctness. Fixture citations are not live supplier confirmation. The larger local coordinator/source changes remain separately scoped until integrated and independently tested.
