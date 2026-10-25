# ShopSquire architecture and current authority boundaries

Reviewed 25 October 2026. The integration branch contains the original 339 dirty paths in explicit commits; baseline is `a9778cf8` and the repaired code/test freeze is `e56a501d`. Public main and the earlier draft PR remain distinct. Arrows describe wiring; current qualification is in the [consolidated savepoint and pilot roadmap](../CONSOLIDATED_SAVEPOINT_AND_PILOT_ROADMAP_2026-10-25.md). The [earlier execution delta](../EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md) and [23 October architecture](CURRENT_ARCHITECTURE_2026-10-23.md) remain historical evidence.

Selected rehearsal data path:

```text
 August electronics .txt -> exclusive new fixture DB -> buyer category/bundle choices
   mock prices/stock          identity + case/revision      explicit acceptance
                                                           |
 SearXNG live discovery <- explicit source-check consent     v
   candidate URLs -> fetch/admission -> relevant citations  exact shortfall
                         |                                 |
                         +-> current scoped market answer  v
                                          one versioned supplier draft
                                          preview -> review -> amendment/reload
                                          real sending disabled
```

```text
 BUYER                                  OPERATOR / ADMIN
 chat, uploads, shelves, reload          inventory, evidence, reviewed draft
 scoped explanation [gap]              raw audit / privileged trace
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

 LEGACY / UNQUALIFIED PATHS
 query clustering -> invocation-time model attempts / hash fallback
                  -> embedding_cache.json [tenant/model/retention gap]
                  -> query_clusters SQL [tenant/job scope gap]
 Grafana JSON adapters -> shared built-in Node HTTP adapter
   explicit credentials / bounded upstream / typed failures
   [native controls pass; Linux observability deployment remains unqualified]

 OTHER IMPLEMENTED SURFACES [qualification varies by profile]

 uploads -> file/URL admission -> OCR / QR / basic CV -> scoped evidence
                                      |
                                      +-> optional vision model
                                          [readiness != accuracy]

 email/webhooks -> source/auth/security checks -> normalized observations
                                              -> proposals / review / outbox

 support / warranty / complaints -> escalation / returns / refund proposals
                                 -> role / person / policy checks
                                 -> provider / ERP adapters [not fully qualified]

 task queue / replay / durable outbox -> owned workers -> terminal receipts
                                       [admission/draining gaps remain]
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
| Buyer/operator explanation boundary | [buyer API calls](../../frontend/src/lib/api.ts), [trace UI](../../frontend/src/components/DecisionTrace.tsx); native buyer calls still cross into operator-only endpoints |
| Legacy analytics requiring isolation | [clustering](../../src/app/services/nlp_query_clustering.py), [persistence/read API](../../src/app/routers/query_clusters.py) |
| Multimodal and email security | [vision API](../../src/app/routers/vision.py), [CV API](../../src/app/routers/cv.py), [email security](../../src/app/security/email_security.py) |
| Post-purchase and effects | [complaints](../../src/app/routers/support_complaints.py), [payments/refunds](../../src/app/routers/payments.py), [task runner](../../src/app/workers/task_runner.py) |

The all-plane privacy cascade, product-agnostic unit/pack normalization, complete landed quote, production independent-person deployment, provider reconciliation and final-candidate endurance are open. SQL compatibility bootstrap is not a replacement for migration/restore qualification. SQLite evidence does not establish PostgreSQL contention correctness. Fixture citations are not live supplier confirmation. The larger local coordinator/source changes remain separately scoped until integrated and independently tested.

The buyer and operator remain different actors. A separate operator browser context can read the internal audit; an ordinary buyer must not receive those credentials. Current buyer UI calls to privileged telemetry/raw trace remain a demonstrated gap. The legacy embedding cache and query-cluster table are not covered by the indexed Redis erasure contract. See the [C22 findings with C23 follow-up](../audits/2026-10-25-c22-code-review-findings.md) and [latest C23 roadmap source map](../audits/2026-10-25-c23-roadmap-source-map.csv) for scope and exit tests.
