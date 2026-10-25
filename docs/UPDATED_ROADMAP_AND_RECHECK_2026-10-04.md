# ShopSquire updated roadmap and execution recheck — 4 October 2026

## Conclusion and scope

The platform remains a substantial fictional-shop prototype with useful, tested services and several connected demonstrations. It is not release-ready, and the previously withdrawn 64.3% whole-roadmap completion claim remains withdrawn. The priority is verified identity, business-state consistency, reproducible fixtures and one complete buyer journey. New model architecture is not the main blocker.

No production implementation was changed, no model installed, and no commit or push performed in this reassessment. Fresh browser tests exercised only the local fictional shop; supplier transport remained fake. A separate identity probe created new synthetic audit cases and did not access any existing customer's case. The incoming-ETA probe used a pure generated replay, not the live inventory database.

Companion documents:

- [File/line/LOC and wiring review](FILE_AND_WIRING_REASSESSMENT_2026-10-04.md): 79 reviewed boundaries across 73 files, plus the structural inventory and runtime API map.
- [Research and application decisions](RESEARCH_REASSESSMENT_2026-10-04.md): verified primary sources, adoption/defer choices and evaluation design.
- [October 1 pause audit](PAUSE_RETEST_AND_ROADMAP_REASSESSMENT_2026-10-01.md): historical broad-suite results and earlier confirmed defects.

“Each file” has two different coverage levels here. The selected code/test/configuration roots have a per-file index of 3,586 files and 681,453 physical lines, including comments and blanks. Critical connections were assessed at the 79 boundaries above. This is not a manual semantic review of every line, every configuration, or all 813 live API operations. The inventory explicitly marks files not manually reviewed. Python AST parsing succeeded for the indexed Python files; parsing and import counts do not establish correctness.

## Current source and fresh execution evidence

HEAD is still `c7daafaa5b7d4248ca97abffd7a9b3e8a031e457`. Hash comparison of all 1,425 inventoried backend/storefront files against `20261001-roadmap-64pct-v2.zip` found **zero changed files and zero missing files**. The paused defects have therefore not been repaired by intervening source edits. The comparison does not claim dependency, database or environment equivalence.

Artifacts are in `.artifacts/reassessment-2026-10-04/`; commands are preserved in `retest.py` and `retest-results.json`.

| Fresh check | Result | Meaning |
|---|---|---|
| Focused service suite | **151 passed** | Existing memory, supplier, inventory, approval, outbox, recovery, retrieval, official research and benchmark boundaries still pass their selected tests. External sockets were guarded. |
| Two known procurement regressions | **Both still fail** | Expired holds leave obsolete shortfalls dispatchable; shipped units are omitted from remaining-quantity calculation. |
| Core/profile architecture checks | **152 passed, two failed** | One actual display-vocabulary boundary violation; one test ceiling needs ratcheting down after a prior improvement. |
| Storefront TypeScript | **Still fails** | Undefined evidence-tab setter and other type/configuration errors remain. |
| Real-API Playwright, nine spec files | **13 passed, three failed; no skips, retries or flaky results** | The two offer cases and merchant case now hit stale fixture data. This is 16 selected cases, not the full browser inventory. |
| Frozen forecasting runner | Nine cases, 60 held-out days each; no winner | Reproducible synthetic comparison, not real market effectiveness. |
| Database | Integrity `ok`; migration `20260891_governed_product_offers`; 284 tables | Schema integrity and migrations are intact in the existing isolated database. |
| Runtime | `/healthz` 200; `/readyz` **503** | `storefront_catalog_ungrounded`: configured default storefront tenant has zero sold-taxonomy entries. Router/search/query-proposer readiness is also not established in this bounded runtime. |
| Main contract identity probe | Creation 201, copied-UID read 200, wrong-UID read 403, credentialless selection **200/current** | UID equality is enforced, but the caller was not authenticated. Probe used only a newly created synthetic case. |
| Incoming-ETA probe | Receipt delayed from **2 days to 367 days**; dataset identical, decision still `wait_and_monitor` | The current baseline input loses the ETA. This does not prove that every delay should trigger a purchase; it proves the decision cannot distinguish these delivery scenarios. |
| Supplier minimum-order probe | Four offered units against a ten-unit minimum are `eligible=true`, `partial`, with a computed landed cost | The shortfall is 15, so the current check compares the wrong quantity to the minimum. Fake transport/in-memory fixture only; no purchase authorized. |

The October 1 broad result remains **historical**, not a newly rerun full-suite result: 7,233 passed, 340 failed, 48 setup errors, 215 skipped, 22 deselected. Its test isolation, missing-schema and event-loop-context problems remain open. Today's focused pass does not close them. The prior 447 frontend unit passes/build passes were not relabelled as fresh results either.

## What the three browser failures actually mean

The previous all-green showcase depended on dated fixtures:

- Both product-offer traces now contain HTTP 409 with `current_configuration_price_required`. Prices were seeded on October 1 and the service permits one day of freshness. The old tests first expected an incompatibility message; the earlier price guard now wins. The visible cart remains empty. These failures are not evidence that stale prices were accepted.
- Merchant replenishment returns `status=blocked`, `reason=quote_not_current`, `commerce_authority=none`. The test expected an advisory result from the old quote. This is a correct expiry boundary and an unreproducible positive-test setup.
- A smaller UI truthfulness issue is visible: the merchant screen says “Lexical and semantic matches combined” while retrieval is empty and no dense retrieval ran. See [MerchantDecisionCard.tsx](C:/AI/ShopSquire/frontend/src/components/MerchantDecisionCard.tsx:47). Distinguish not-called, empty, lexical-only, degraded and successfully combined states.

Do not relax freshness checks to make these tests green. Build a disposable seeded scenario with an explicit test clock/fresh fictional evidence, then run a separate expiry progression. Actual provider evidence must be refreshed from its source rather than simply retimestamped. Reset stock through a reproducible test-database restore so repeated shipment tests do not gradually consume the showcase stock.

## Priority findings and wiring gaps

### P0 — Identity on main buyer contract routes

[shopping_cases.py:49](C:/AI/ShopSquire/src/app/routers/shopping_cases.py:49) includes the contract router. [shopping_case_contracts.py:53](C:/AI/ShopSquire/src/app/routers/shopping_case_contracts.py:53) accepts a UID/tenant and changes the selected contract; [case_contract_binding.py:25](C:/AI/ShopSquire/src/app/services/case_contract_binding.py:25) compares the supplied UID with the case owner. This path does not call the existing [buyer principal resolver](C:/AI/ShopSquire/src/app/security/buyer_principal.py:104).

The direct local HTTP probe confirmed credentialless selection of a new synthetic case when its UID and ID are supplied. This changes requirement selection, not payment or purchase authority. Do not infer a remote production exploit from a localhost test, but do not claim authenticated buyer ownership either. Wire the existing signed-session/JWT principal into this path and reject tenant/UID mismatch at the server. Test strict deployment mode as well as the local demo mode. Synthetic enrolled users are sufficient; a real customer or external identity vendor is not required.

### P0 — Procurement state must be current at dispatch

[supplier_enquiry_journey.py:77](C:/AI/ShopSquire/src/app/services/supplier_enquiry_journey.py:77) computes shortfall from current reserved quantities. Its [dispatch path](C:/AI/ShopSquire/src/app/services/supplier_enquiry_journey.py:119) checks case revision and the exact grant but does not detect that an expiry/shipment changed the business facts without changing that case revision. Both October 1 regressions still fail.

Define remaining demand across reserved, shipped, returned and cancelled states; bind the relevant inventory/fulfillment snapshot into the enquiry's validity. A changed snapshot should produce a fresh proposal and, when effect bytes change, fresh approval. Add expiry/dispatch and amendment/shipment race tests. Preserve the existing outbox and person checks.

There is also a quote feasibility defect at [supplier_enquiry_journey.py:184](C:/AI/ShopSquire/src/app/services/supplier_enquiry_journey.py:184): minimum order is compared with total shortfall before `sourced_quantity=min(shortfall, offered_quantity)` is calculated. A reviewed four-unit offer with a ten-unit minimum and 15-unit shortfall is presented as eligible partial supply with cost. Validate the actual proposed sourced quantity against all terms; contradictory capacity/minimum terms need explicit rejection or renegotiation, not a usable cost commitment. Evidence: `supplier-moq-probe.json`.

### P0 — Readiness, types and test isolation

[App.tsx:3558](C:/AI/ShopSquire/frontend/src/App.tsx:3558) still calls an undefined setter. The default storefront's catalogue grounding is missing, even though named synthetic tenants have fixtures. Resolve the intended tenant/catalogue mapping; do not bypass the readiness check. Make isolated feature flags, migrations and event-loop cleanup part of the baseline test harness. A clean targeted suite is insufficient for committing a large batch as regression-clean.

### P1 — Complete the existing V2 connection

The persisted V2 binding is **already wired**, including before/after revision checking and passing the selected contract into compilation: [case_binding.py:64](C:/AI/ShopSquire/src/app/services/recommendation_core/case_binding.py:64), [case_binding.py:135](C:/AI/ShopSquire/src/app/services/recommendation_core/case_binding.py:135). It should not be listed as an entirely missing implementation.

The missing proof is the complete ordinary conversation through governed research, current exact configuration facts, positive qualification and matching response/shelf/trace. [main.tsx:22](C:/AI/ShopSquire/frontend/src/main.tsx:22) shows separate fixture entry surfaces. Sharing compiler/services does not prove that those surfaces and the main chat form one successful buyer journey. Keep one V2 path and use unfamiliar subjects/non-laptop cases to detect overfitting.

### P1 — Market intelligence currently loses decision-relevant information

[merchant_decision_dataset.py:46](C:/AI/ShopSquire/src/app/services/merchant_decision_dataset.py:46) aggregates future incoming orders; the baseline uses that total in inventory position. The ETA probe demonstrates a two-day versus 367-day arrival becoming the same dataset. Preserve ETA, certainty/status, reservations and commitments, then compare horizon-specific availability and expedites/alternatives. The read-only merchant API currently computes the baseline and retrieves supporting notes separately; the notes do not change the decision.

The positive dataset still lacks the integrated returns/cancellations/transfers history required by the original acceptance criteria. Do not solve this by adding more product rows. Connect existing event sources and reconciliation, then compare AI assistance with the corrected simple baseline.

### P1 — Recovery is a service, not a completed operator journey

[operator_recovery.py:22](C:/AI/ShopSquire/src/app/services/fulfillment/operator_recovery.py:22) implements and tests recovery observations for uncertain sends. No application caller or matching API/UI for this service was found in the current source/runtime wiring. Other recovery/reconciliation endpoints exist for different concerns and must not be counted as this workflow. Add authenticated review/revoke/renew/reconcile operations, then cover separate refund, payment, inventory and connector state machines.

### Cross-cutting — Agnostic core and evidence of AI quality

The generic drafting module still embeds GPU/VRAM labels at [draft.py:395](C:/AI/ShopSquire/src/app/services/fulfillment/draft.py:395). Move display vocabulary into profile/schema adapters. A second architecture-test failure is beneficial code simplification whose ceiling has not been updated: chat's counted domain vocabulary dropped from 17 to two. Neither issue justifies replacing the core.

Keep deterministic rules for authorization, identity, freshness, revisions, arithmetic and transaction consistency. Evaluate language extraction and suitability with supported evidence and unknown/conflict states. Review source-specific parsing branches as adapters; do not replace auditable invariants with model discretion or expand keyword exceptions whenever one showcase fails.

## Full remaining 0–13 roadmap

| Item | Current evidence | Work remaining | Evidence required to close |
|---|---|---|---|
| **0 Reproducibility/isolation** | Source checkpoint verified; migrated DB intact; bounded fake-transport runtime | Correct storefront tenant/grounding; reproducible fixture clock/reset; clean dependencies and independent restore; isolated test flags | Fresh environment and disposable scenario pass documented startup/tests; expected expiry tests pass separately; real-provider effects remain impossible |
| **1 Conversation memory** | Six fresh browser cases pass; typed state projection exists | Deadlines, ambiguity, longer interdependent tasks, summaries, backend failure/restart and memory-backend behavior | Correct later decisions from changed facts, false-premise rejection and cross-user/tenant isolation; API/UI/trace parity |
| **2 Market dataset** | One scoped synthetic replay and reconciliation | Preserve inbound ETA and commitments; integrate returns/cancellations/transfers; distinguish missing/censored demand | Near/far inbound scenarios differ appropriately; events reconcile; future/oracle data excluded |
| **3 Merchant intelligence** | Read-only API/card and governed retrieval exist; current stale quote is correctly blocked | Relevant reviewed corpus, truthful retrieval status, strict identity/scope and useful decision alternatives | Current cited facts, appropriate abstention, source lineage and measurable decision relevance |
| **4 Forecasting** | Nine-case mean/EWMA/synthetic-signal experiment reruns; no winner | Rolling origins, intermittent/zero-demand cases, noisy/delayed/misleading signals; one optional model challenger | Equal budgets and held-out improvements in cost, stockouts, excess and delivery; uncertainty calibration |
| **5 Positive buyer journey** | V2 binding/compiler wired; fixed-clock fictional qualification browser passes | Authenticated main contract routes and normal conversation-to-qualified-shelf/trace connection | One complete positive fictional journey, plus changes/expiry/revocation/conflicts invalidate it; real Blender separate |
| **6 Inventory** | Transactional holds, amendments and operator browser workflows pass | Lifecycle-correct remaining demand; concurrent expiry/dispatch/shipment/amendments and target DB verification | No oversell or duplicate stock change; current availability and durable event reconciliation |
| **7 Supplier conversations** | Independently approved fake send and structured reviewed replies pass | Current shortfall revalidation, natural case integration, ETA/terms handling and usable review input | Duplicates, silence, substitutions, sender mismatch, expiry and stale revisions handled with exact effect counts |
| **8 Amendments/approval** | 30→40 and synthetic distinct-person checks exist | Strict authenticated buyer/operator integration, deadlines/MOQ/freight/cost and all changed-effect consequences | Two credentials for one person rejected; tenant/tier/revocation/payload checks hold at dispatch |
| **9 Recovery** | Internal uncertain-send service tests pass | Wire operator screens/API; fresh authority for replacements; audit all effect sinks | Crashes before/after provider response recover without duplicates, lost reservations or false completion |
| **10 Bundles** | Evidence/price gates work; current positive fixtures now stale | Fresh reproducible evidence, normal conversation/cart integration, broader compatibility and discount boundaries | Explicit acceptance, correct incremental/total prices, unknown/conflicting abstention and concurrency/replay safety |
| **11 Security/browser** | Selected negative tests and 13 fresh passing browser cases | Systematic direct/indirect/OCR/memory attacks; identity coverage; more connected failure paths and accessibility | Canaries, durable effect counts, leakage/false-refusal metrics, multi-tab/reload/network-loss assertions |
| **12 Endurance/catalogue/release** | Archive, migrations and local checks exist | Original buffer diagnosis, real timed runs, catalogue identity/conflict review, independent install/restore, remote CI and rollback | Predefined 60-minute/eight-hour resource/correctness passes and observed release/rollback evidence |
| **13 Representative benchmarks** | Structural harnesses and small comparisons | Frozen reviewed multi-category cases, comparable budgets, measured reranking/graph/model ablations | Reproducible held-out improvement; no architecture adoption or winner from marketing/leaderboards alone |

Items are not assigned a new misleading completion percentage. Working components are retained; broad original gates remain open.

## Recommended execution order

1. **Trust and reproducibility first:** authenticated contract ownership, current inventory at dispatch, frontend type failure, intended storefront grounding and repeatable isolated fixtures. Keep security and regression tests attached to these repairs.
2. **One ordinary buyer journey:** use the existing V2 binding/compiler and one fictional exact configuration to prove positive qualification, corrections and evidence invalidation in main chat. Keep the RAM-only fixture and real Blender claims separate.
3. **Useful read-only market decision:** reconcile lifecycle history, preserve inbound ETA/commitments, correct baseline decisions and make retrieval status truthful. This can progress independently of external commerce completion; do not give the decision card execution authority.
4. **Complete procurement and recovery:** accepted stock → current shortfall → simulated supplier reply → amendment costs/deadline → distinct-person approval → uncertain-effect recovery. Integrate bundles through the same buyer/cart path.
5. **Close systematic assurance:** full suite isolation, remaining browser/security paths, resource diagnosis, timed endurance, clean environment, observed CI and rollback.
6. **Promote AI only through evidence:** after the dataset/baseline is valid, run one forecast challenger and retrieval ablations. Representative model/graph expansion remains conditional on measured failures and improvement.

The small forecasting experiment can run before all commerce work is finished, because it is read-only and isolated. Architecture promotion and readiness claims still require their own evaluation/reliability gates. This order does not require real customers, private supplier access or real payments.

## What is demonstrable today

Fresh passes support multi-message recall/corrections, requirement selection and fictional qualification invalidation, stock amendments, operator inventory actions, approved fake supplier sends/reviews and requirement-load recovery. The stale merchant and bundle paths demonstrate refusal on old data today; their positive October 1 demonstrations require a properly refreshed/reset fictional scenario to reproduce. No real product was newly qualified, no external search success was newly demonstrated, and no eight-hour endurance result was established.

The useful claim is experience building and evaluating a governed simulated commerce system, including finding defects that happy-path demonstrations missed. A complete platform, production security, sustained stability and a superior model remain unproved.
