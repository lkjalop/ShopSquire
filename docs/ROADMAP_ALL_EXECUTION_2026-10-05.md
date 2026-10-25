# ShopSquire: roadmap 0-13 execution and evidence

**7 October status correction:** the isolated eight-hour run subsequently failed after 2,726.438 seconds, with 35 successful cycles and a failure on cycle 36. The failed qualification reload trace records `ERR_NO_BUFFER_SPACE` loading `FulfilmentOptions.tsx`; the root cause remains open. It did not reach its 60-minute checkpoint. See [the 7 October reassessment](REASSESSMENT_AND_COMMIT_GATES_2026-10-07.md) for the current commit gates, twelve-finding review, 95 fresh passing targeted tests and 14 fresh passing browser cases. Historical progress statements below are not current run status.

Updated 5 October 2026, Australia/Sydney. Execution is ongoing. This is a working-tree assessment, not a claim that all 14 items or every platform test passed. No commit, push, real supplier message, ERP purchase or payment was performed. Public read-only search was exercised explicitly in a disposable runtime.

**Results recorded on 5 October:** the frozen general Python run passed **7,782 tests, with 124 skips and zero failures/errors**. The later payment-boundary repair passed 71 focused tests with one skip. All 404 frontend tests passed; the nine-test model/browser batch passed. The isolated eight-hour browser/API replay started on 5 October at approximately 16:36 Sydney time and subsequently failed as corrected above. Its final status is recorded in `frozen-isolated-endurance/.artifacts/endurance-shop/eight-hour-isolated/soak/status.json` under the artifact root below.

The earlier bounded 0-7 report remains useful: [ROADMAP_0_7_EXECUTION_2026-10-05.md](ROADMAP_0_7_EXECUTION_2026-10-05.md). Its tests and snapshots are historical evidence, not automatic certification of later edits.

## Current capabilities and limits

The normal chat UI can qualify a **fictional RAM-capacity configuration**, preserve and correct requirements, show the current shelf/trace, accept simulated stock, expose a shortfall and show reviewed supplier offers. An independently approved fake supplier enquiry can be reconciled after an uncertain outcome and replaced only with fresh approval. A supported fictional accessory can be reviewed and explicitly accepted into the draft cart. None of these actions authorizes real commerce or qualifies a real Blender product.

Real-model tests now cover three distinct product images followed by a quantity correction; the response, durable case, read model and terminal trace must agree. These checks do not measure OCR accuracy or sustained mixed-model reliability.

Live FreeCAD discovery dispatched through the local SearXNG-compatible service. It returned degraded publisher-candidate evidence, correctly held product qualification and granted no commerce authority. This demonstrates a real network attempt and truthful incomplete evidence, not successful official requirement compilation or search quality.

## Complete remaining roadmap

| Item | Implemented and exercised | Still required to close the broader item |
| --- | --- | --- |
| **0. Reproducibility/isolation** | Disposable Windows installation, fixtures, migrations, signed buyer identity, fake effects, explicit fixture clock, SQLite restore; additional Linux container installation/restore with network disabled. Browser runner refuses occupied ports and owns cleanup. Shared controls clear payment/ERP credentials and force sandbox transports. | Latest supplier-constraint candidate passed Linux restore and same-schema source rollback/roll-forward; the later payment switch repair has focused tests. Independent-machine restoration, deployment automation and observed current remote CI remain open. |
| **1. Conversation memory** | Prior multi-turn/reload/process-restart checks plus Redis write/erase failure tests; corrected image-amendment precedence, canonical quantity and retained budget scope/currency. Literal input remains separately available from accepted case facts. | Separate-process Redis erasure, partition and restart now pass. Concurrent erase/write races, load-balanced API deployment behavior, longer interdependent tasks and ambiguous commercial constraints remain open. |
| **2. Market dataset** | One synthetic tenant/SKU, reconciled events, incoming ETA and commitments, returns/cancellations/transfers, explicit missing/censored demand and cutoff filtering. | Broaden reconciled scenario profiles and ingestion-lateness corrections; preserve event identity across catalogue migrations. Real customer data is unnecessary for the fictional showcase. |
| **3. Merchant intelligence** | Read-only cited decision card, scoped/fresh reviewed fixture evidence, conflict abstention and explicit lexical fallback. Public-source transport now streams under a byte limit. | More useful evidence documents and independent relevance review; live-source-to-exact-SKU mapping and degraded retrieval browser checks. A public recall probe returned zero matching rows; that is not proof of safety or market relevance. |
| **4. Forecasting** | Rolling held-out synthetic evaluations with equal history budgets and observed/intermittent/zero demand, noisy/delayed/misleading/expired signals. Operational cost, stockout and excess metrics retained. | Variable realized supplier delays now have a controlled comparison; broader reconciled generators and calibrated uncertainty remain open. The 486 variants are correlated; no challenger promotion or model-quality winner is established. Retain the baseline. |
| **5. Positive buyer journey** | Normal chat, authenticated contract selection, local governed research, positive fictional shelf and trace; stale/conflicting/revoked evidence invalidates qualification. Live discovery remains visibly unqualified when evidence is insufficient. | Additional workload/category contracts and successful live official-source consumption under reviewed scope. Real Blender qualification remains separate and unproved. |
| **6. Inventory** | Holds/amendments/releases, expiry, receiving, transfers, shipping/returns/cancellation and reconciliation; API/UI and concurrency checks. Removed global SQLite INSERT OR REPLACE behavior that could silently overwrite existing identities. | Broader concurrent worker/scheduler/restart journeys and migrations with existing dependent records. Demo schedules remain deliberately disabled; controlled scheduler tests are separate evidence. |
| **7. Supplier conversations** | Same-case shortfall to independently approved fake send, structured reply and reviewed quote; current shortfall at dispatch; buyer-safe quote projection hides supplier costs and identities. Partial/stale/duplicate/substituted/expired replies are covered. | Buyer selection and current budget/deadline revalidation now pass through normal chat. Full operator purchasing handoff after selection and broader supplier conversation behavior remain open. Structured fake replies are not a live authenticated mailbox or autonomous negotiation. |
| **8. Amendments/approval** | 30 to 40 revises demand/holds and invalidates obsolete enquiries; supplier dispatch binds authenticated distinct people, tenant, exact payload and current authority. | Covered-order freight and typed budget/deadline checks now gate buyer selection; MOQ and substitutions are checked. Complete full-order pricing and purchasing consequences for unresolved shortfalls. Extend person-bound approval to legacy PO/refund/order/connector paths. Legacy HUMAN_OPERATOR role checks alone do not satisfy distinct-person approval. |
| **9. Recovery/effect boundaries** | Operator supplier revoke/reconcile/renew UI and real-API browser test; unknown outcome blocks automatic retry. ERP adapter now requires a valid provider receipt; durable PO dispatch intent survives simulated process loss. Workflow writes bind the validated version; PostgreSQL simultaneous dispatch produces one fake effect. | Full legacy PO/payment/refund/inventory/connector review and recovery screens, trusted reconciliation receipts and independent post-effect completion checks. A conservative blocked PO is safe but not a complete recovery workflow. |
| **10. Upgrades/bundles** | Governed standalone offers plus ordinary chat/cart accessory proposal and explicit acceptance; evidence/benefit and total displayed; tenant headers/authentication repaired. Acceptance invalidates obsolete qualification. | More reviewed compatibility configurations, discounts, upgrades and quantity expansion under concurrent edits. One invented accessory relationship is not catalogue-wide compatibility. |
| **11. Security/browser** | Direct and indirect endpoint tests, cross-tenant canary, UID spoofing, malicious artifact quarantine, durable effect snapshots across all tenants, uncaught browser exception checks; connected supplier/recovery/bundle/merchant tests. | Systematic search/supplier/OCR/memory adversarial matrix, larger benign controls, leakage/refusal metrics, accessibility and more network-loss/concurrent-tab cases. Selected passing attacks are not a security certification. |
| **12. Endurance/catalogue/release** | Preserved failed runs; reproduced semaphore/handle growth from metrics labeled with literal request URLs; normalized labels to route templates and regression-tested. Catalogue reconciliation now refuses conflicting identity merges and bound-record migrations instead of deleting dependencies. Linux restore and local CI-equivalent checks run. | The frozen 60-minute run passed (51 cycles). The eight-hour attempt failed after 24m44s/21 cycles when host available memory fell below 1 GiB; API RSS was about 233 MiB and handles 1,226 at failure. Rerun without competing test workloads, then extend to varied-model/image endurance. Historical browser failures are not conclusively explained by the newly reproduced metrics leak. Complete explicit identity migration/conflict-review UI, final-candidate restore, observed current remote CI and rollback. |
| **13. Representative benchmarks** | Frozen synthetic cases, negative forecasting promotion decision, bounded model/image behavior, and 56 current-catalogue brand/budget cases across 168 retrieval calls. | Independently reviewed labels, held-out unfamiliar categories, equal runtime budgets and error-led model/retrieval/reranker/graph comparisons. No quality winner; no justification yet for a broad graph or V3 rewrite. |

## Current execution receipts

Paths below are under `.artifacts/execution-all-2026-10-05/`. Runs overlap; **do not add counts together as unique coverage**. Failed red-stage receipts are retained alongside passing repairs.

| Receipt | Observed result / scope |
| --- | --- |
| `fulfillment-current/receipt.json` | 419 passed, one slow test skipped; fulfillment service directory, API, runtime controls, catalogue reconciliation, effect snapshot and metric cardinality. |
| `postgres-effects-current/receipt.json` | 11 passed on real PostgreSQL 16, including simultaneous PO dispatch, outbound/refund races, tenant/RLS and audit recovery. Fake providers; owned container removed. |
| `workflow-version-red` -> `workflow-version-green` | Stale validated-version regression failed before repair; 38 selected tests passed after repair. |
| `sqlite-identity-red` -> `sqlite-identity-green` | Duplicate INSERT overwrite reproduced; 101 selected tests passed after removing implicit replacement. |
| `final-clean-model/model-image-keyboard/report.json` | Nine browser tests passed on a fresh fixture: six conversational qualification/procurement/accessory checks (including keyboard trace focus/Escape) and three different images with current quantity assertions. Real local models, fictional offline research. |
| `integrity-candidate/final-restored-browser/report.json` | 18 real-API browser tests passed on the restored database after SQLite and shared-state repairs, including operator inventory, supplier approval/recovery, memory, merchant card and requirement-read recovery. |
| `image-continuity-v3/adversarial-canary/report.json` | Three browser tests passed: cross-tenant canary/direct attacks and two artifact-security cases. Durable all-tenant effect snapshots unchanged. |
| `security-endpoints/receipt.json` | 25 selected security tests passed. Security flag overrides now use temporary files instead of modifying repository configuration. |
| `budget-scope-red` -> `budget-scope-green` | Retained scope/currency regression reproduced; 27 tests passed after repair. |
| `live-research/live-browser-v2/receipt.json` | Consented live-search browser passed with budget-scope assertions and unchanged commerce effects. Degraded discovery, publisher review required, no qualification. |
| `linux-restore-results/receipt.json` | Clean Python 3.12 Linux install, dependency check, seed/migrations, authenticated reload and SQLite restore passed with network disabled. Earlier snapshot; not Linux browser evidence. |
| `frontend-final.json` | 401 frontend tests passed after the keyboard-focus repair; production Vite build also passed. One ineffective dynamic import warning remains. |

Current remote CI successes observed previously refer to `879879676794c12902a6b6a2ecc0876e433edfc1`, not this dirty working tree. No current-code remote CI claim is made.

## Files and wiring to review

These are entry points in the current working tree, not a claim that every source line was audited. Line numbers can move as execution continues.

| Boundary | Source entry point and connection |
| --- | --- |
| Metric cardinality | `src/app/observability/http_labels.py:5` -> `src/app/main.py` HTTP middleware; route templates and one unmatched label replace case-specific paths. |
| Conversation commit | `src/app/services/conversation_case_state.py:746`; current typed patches apply after retained shared values. |
| Canonical facts | `src/app/services/turn_transition.py:157` -> `chat_terminal_projection.py:143`; accepted quantity/budget scope and literal provenance. |
| Memory backend failure | `src/app/services/memory.py`; timestamped cache envelopes and explicit incomplete-erasure error. |
| Buyer quote projection | `src/app/services/buyer_supplier_quotes.py:11` -> `routers/shopping_case_inventory.py` -> `BuyerSupplierQuotes.tsx`. |
| Supplier recovery | `src/app/services/supplier_enquiry_recovery.py:15`, `:25`, `:37` -> `routers/operator_supplier_enquiries.py` -> `SupplierEnquiryPanel.tsx:5`. |
| Chat accessory offers | `src/app/routers/shopping_case_product_offers.py:32`, `:63`, `:77` -> governed offer services -> `CaseProductOffers.tsx:5` within stock review. |
| Exact version write | `src/app/services/fulfillment/workflow.py:96` -> `repository.py:236`; validated version passed into conditional close-and-append. |
| PO dispatch and receipt | `src/app/services/fulfillment/purchase_order.py:52` -> `po_transport.py:51`; intent commit before transport, unknown outcome blocks retry. |
| Stock lifecycle | `src/app/services/inventory_transactions.py:134`, `:158`, `:193`; reserve, event transitions and expiry. |
| Market decision | `src/app/services/merchant_decision_dataset.py:26`, `:90` -> `merchant_evidence_retrieval.py:97` -> merchant card. |
| Forecast experiment | `src/app/services/heldout_inventory_benchmark.py` and `scripts/run_rolling_inventory_benchmark.py`; correlated synthetic cases, no winner. |
| Catalogue integrity | `src/app/models/db.py`; removed replacement rewrites. `scripts/reconcile_demo_catalog_identities.py`; conflicts now require explicit review. |
| Test isolation | `scripts/roadmap_runtime.py`, `prepare_roadmap_demo.py`, `prepare_live_research_demo.py`, `run_roadmap_browser.py`, `run_postgres_roadmap_tests.py`. |
| Browser scenarios | `frontend/e2e/conversational-qualification.spec.ts`, `varied-image-continuity.spec.ts`, `supplier-recovery.spec.ts`, `adversarial-case-isolation.spec.ts`, `consented-live-research.spec.ts`. |

## Next execution gates

1. Retest final connected workflows after shared-state repairs and finish the frozen endurance run without changing its source snapshot.
2. Bind accepted supplier quote and amendment costs/deadlines to the ordinary buyer case, then extend authenticated independent approval and operator recovery to remaining effect sinks.
3. Expand security/browser failure cases and representative benchmark review without weakening evidence gates to obtain a positive result.
4. Freeze the final candidate for restore/rollback and eight-hour testing; observe current remote CI only after an explicitly authorized publication step.

The core remains generic: identity, authorization, revision, freshness and transaction arithmetic are deterministic safeguards; product facts, workload scopes and fictional relationships are data/adapters. No additional graph infrastructure, V3 recommendation engine or larger context allocation was added.

## Reproducibility findings from the final reruns

A reused model fixture failed two tests because earlier stock reservations and cart/offer state remained. The failure is preserved in `image-continuity-v3/final-model-budget-regression` (seven passed, two failed). A newly seeded shop, fresh fictional evidence and the unchanged stock/cart expectations passed all nine tests in `final-clean-model/model-image-keyboard`. Do not use an already mutated shop as the initial fixture for this suite.

The slow market integration test skipped by default was explicitly enabled and passed separately in `market-pipeline-slow/receipt.json`. The trace dialog focus regression was red before repair; eight focused navigation tests and the 401-test frontend suite passed afterward. The panel is nonmodal, matching its existing interactive background. This does not establish WCAG compliance.

The first full Python suite finished in `frozen-integrated/.artifacts/full-pytest`: 7,269 passed, 371 failed, 48 errors and 242 skipped (7,930 reported cases). It is not green. The isolated source checkpoint contains 5,182 files, SHA-256 `b100f620836169142fa7db382344a3f6ddf5c5ea41386b375ec1aaccda0217f0`, and a consistent SQLite backup. Source checkpoints exclude runtime secrets, dependencies and large/binary assets; tests that need excluded assets need separately verified fixture packaging.

Research application and primary-source links: [RESEARCH_APPLICATION_2026-10-05.md](RESEARCH_APPLICATION_2026-10-05.md).

Detailed checkpoint-relative file index: [EXECUTION_CHANGE_INDEX_2026-10-05.md](EXECUTION_CHANGE_INDEX_2026-10-05.md). It lists changed files and their current line counts/entry points; those counts are file sizes, not lines newly added.

## Full-suite findings and current rerun

The first frozen full Python suite finished with 419 failures/errors. It is **not green**. Initial focused triage reproduced 11 failures among 17 tests: legacy case/source-resolution tests sent unsigned buyer requests, the admin smoke test omitted credentials, and two minimal database fixtures omitted the conversation migration. The tests now exercise signed principals and the actual migration; `authenticated-migrated-legacy/receipt.json` records 17 passed. Production authentication was not relaxed.

Other full-suite failures, including older checkout/payment, provider adapters, OCR fixtures and legacy browser surfaces, remain to be classified. The frozen run intentionally retains its original tests, so it will still report repaired test fixtures as failing. Optional/live tests may be skipped; excluded binary fixture packaging and test-order/global-state interference require explicit review before attributing every failure to application code.

The eight-hour replay in `frozen-endurance/.artifacts/endurance-shop/eight-hour/soak` failed after 1,484.485 seconds and 21 successful cycles: `resource_limit:host_available_memory`. Concurrent full-suite/browser activity is a host-contention confound; the API remained below its own resource thresholds. Do not lower the thresholds or count this as endurance success. The separate 3,600-second/51-cycle run passed. Both snapshots predate the latest tenant/recovery fixes and cover browser replay, not sustained mixed-model/image behavior.


## Additional regression repairs and evidence

- **Test collection isolation:** two security modules replaced the global DB and feature-flag path at import. A new import-isolation test failed twice before repair; 14 mixed security/tenant/flag tests then passed. A 459-case mixed run subsequently passed 458 with one slow skip, including the budget/quantity acceptance matrix. This explains part of the first full-suite failure cascade, not every failure.
- **Legacy procurement tenant propagation:** foreign case reads, draft/approval/RFI/quote/options/cancellation/PO commands, case creation, notifications and economics now use the authenticated scope. The broader operator regression passed 436 with one slow skip. Owner-only email evidence reads, legal holds, enrichment listing/replay also needed explicit tenant filters; a combined 418-test service/security/runtime regression passed. Distinct-person authorization on all legacy effect sinks remains open.
- **Recovery race:** the real browser exposed a SQLite deferred-read/write race. A WAL concurrent-writer regression failed before repair; recovery now uses the existing atomic write-reservation boundary and rechecks the enrolled operator inside it. Thirteen recovery tests passed. The subsequent browser run completed all recovery assertions but failed cleanup on a reused zero-stock fixture; the fresh fixture rerun `recovery-clean-shop/recovery-current` passed all recovery and cleanup assertions.
- **Exact browser selection:** missing scenario names now fail before startup, and receipts list exact requested files. Before this repair Playwright silently ignored two mistyped names alongside valid matches. Do not count the earlier partial receipt as supplier/merchant coverage.
- **Default limits retained:** the correctly selected combined browser run passed six and failed two with HTTP 429 on the admin path. Isolated supplier replay passed with limits intact. This remains a combined-test pacing and operator-usability concern, not grounds to disable the limit.
- **Backend isolation:** new local browser runtimes explicitly use an unavailable loopback Redis/queue endpoint with credentials cleared. They exercise local fallback and SQL persistence, not real Redis recovery. Older snapshots inherited configuration and reported Redis unavailable; they were not proof of independently provisioned cache isolation.
- **Checkpoint packaging:** `20261005-tenant-harness-candidate.zip` contains 5,226 files, SHA-256 `f9ab177a12339e12e2105f8bd5793c941898370f72bff976d46c0b6eb8d43c7e`. It now includes test images, JSONL corpora, SHA256 seals, Bicep and Dockerfile variants. The new full-suite run is `frozen-tenant-harness/.artifacts/full-pytest`; it finished with 7,310 passed, 397 failed, zero errors and 245 skipped; it is not green. That snapshot predates subsequent operator/email/recovery edits.

Current additional source entry points: `tests/test_security_collection_isolation.py`, `tests/api/test_legacy_po_tenant_scope.py`, `tests/api/test_inbound_operator_tenant_scope.py`, `src/app/routers/fulfillment_cases.py`, `src/app/services/fulfillment/change_order.py`, `src/app/services/fulfillment/operator_recovery.py`, `scripts/run_roadmap_browser.py`, `scripts/roadmap_runtime.py`, and `scripts/soak_resource_sample.py`.


## Latest connected selection and regression evidence

- Migration `20260892_buyer_supplier_selection` persists an explicit, owner/tenant/case/revision-bound supplier estimate choice. The digest includes current price, freight, quantity and reviewed terms. Expiry, inactive product, changed terms, remaining demand or case revision requires revalidation. It creates no purchase, supplier reservation or send authority.
- `selection-model-shop/selection-chat-images`: nine real-API browser tests passed (220.917 seconds), using local text and vision models. The ordinary buyer journey selects a reviewed partial quote, checks the durable receipt and remaining five-unit shortfall, then changes demand to 40 and observes the obsolete selection. Three varied-image correction scenarios also passed. Fictional qualification remains distinct from real Blender certification.
- `selection-clean-shop/selection-security-regression`: eleven real-API browser tests passed (44.296 seconds), including tenant canaries, malicious artifacts, requirement-read failure recovery and memory checks.
- `frontend-supplier-selection.json`: 403 frontend tests passed; TypeScript checking and the production build passed. One ineffective dynamic-import warning remains.
- `selection-active-green`: 39 focused Python tests passed, including inactive-product rejection, authenticated selection, supplier journey and recovery. `all-collection-green`: 38 passed after removing import-time environment/engine mutations from seven legacy test modules.
- `replay-scope-green`: five tests passed after a red test reproduced an authenticated email replay accepting a foreign tenant in its body. Replay now derives tenant from authenticated context and rejects a conflicting body scope.
- `incident-tenant-chain`: 29 passed. This isolated sequence does not reproduce the broad suite's missing membership-table failures; their cause remains under investigation.
- Checkpoint `20261005-selection-recovery-candidate.zip`: 5,233 files, SHA-256 `45f9a792152d28e7b68c98fbec0270d5c32945bd7ad299c6b9759f8030175fcb`, SQLite backup integrity checked at migration 20260892. It predates the later inactive-product and replay-scope repairs.

The second full Python run reported 7,310 passed, 397 failed, zero errors and 245 skipped. Its failure classes include fixture/schema contamination, session browser event-loop interference and payment tests run with the browser runtime's payments-disabled flags. Those confounds do not excuse the remaining application failures.

A new API/service run is isolated from Python browser/load fixtures and permits the existing simulated checkout path while clearing real provider credentials. Its initial misconfigured attempt was explicitly interrupted and preserved; `frozen-selection-recovery/.artifacts/general-simulated-pytest` is the corrected run. It already has failures and must not be called green. The separate TypeScript browser receipts above remain valid within their stated scope.

No eight-hour run is currently active. The previous eight-hour attempt failed the host-memory threshold; only the earlier 60-minute bounded replay passed. Run the next endurance candidate after competing heavy suites finish, without lowering admission or correctness thresholds.

## Subsequent broad-suite diagnosis and repairs

The corrected `frozen-selection-recovery/.artifacts/general-simulated-pytest` run finished: **7,637 passed, 87 failed, zero errors, 122 skipped** (7,846 cases). Python browser/load suites were explicitly excluded and require separate receipts. The selected failing-module rerun `remaining-general-current-v2` then reported 498 passed, 18 failed and two skipped. These are historical snapshots, not a current all-green platform claim.

Concrete repairs since that snapshot:

- Module-scoped API fixtures leaked minimal database engines into later tests. Four fixtures now use function-scoped temporary databases and restored environment state. The ordered API prefix passed 130 tests. A money-concurrency test also replaced a production guard globally; it now restores that patch.
- Three threshold tests wrote repository feature flags instead of their isolated test configuration. They now use the temporary path. The contaminated file was preserved; comparison with the checkpoint showed only those three threshold sections differed, and the checkpoint bytes were restored.
- Commercial interpretation mistook `Dell 15` and `15 inch laptops` for a 15-unit order. Quantity proposals and commercial parsing now use the shared bounded quantity grammar; product units come from store profiles. A separate budget-span repair prevents `max` in a budget correction from becoming an external-research concept. Industrial-profile cases guard against electronics overfitting.
- Cache erasure now reports incomplete backend/index deletion and retains a retryable index instead of claiming success. This is a failure-reporting and retry guarantee, not distributed deletion certification.
- Graph recall could expose unadmitted finding labels as useful insights. Findings now enter the useful projection only through evidence admission; raw graph recall remains diagnostic. The new unverified-demand canary failed before repair.
- Local-only HTML tests now supply actual loopback peer identity and owner credentials instead of relying on a Host header or unauthenticated access. Production authentication remains enforced.

Focused evidence: `conversation-quantity-budget-green` has 255 passed; `cache-erasure-green` has 24 passed; `router-boundary-extraction` has 417 passed; `local-peer-contracts-green` has 17 passed. These overlap other runs and must not be added as unique coverage. `commercial-current-shop/commercial-memory-regression` passed ten real-API browser tests, including the new model-number/dimension/budget regressions and seven memory scenarios. Model inference was disabled for that parser/memory run.

`remaining-general-final` finished with **514 passed, four skipped, no failures or errors**. The fresh `qualification-final-model/final-connected-model` text/vision browser run passed six conversational qualification tests but failed all three image-follow-up corrections: explicit `quantity to 12` was rejected by the stricter grammar, retaining 20. A new parser regression reproduced the defect before repair; the unchanged browser expectations are being rerun on a new fixture. This is why a focused API pass does not establish browser-wide success.

Forecasting now accepts an explicit, validated environment-only supplier-delay schedule. Twelve forecasting tests pass, including proof that changing realized delays changes outcomes without changing frozen policies, input digests or uncertainty inputs. `rolling-variable-deliveries.json` records 486 correlated synthetic variants: EWMA had lower cost in 78 and higher cost in 72; EWMA with signals had lower cost in 64 and higher cost in 111. Average cost deltas versus the baseline were positive for both. Keep the baseline; no winner is established. The delay cycle is shared by order ordinal, not a common calendar shock; customer deadline performance and calibrated uncertainty remain open.

All 0–13 items retain the broader closure conditions in the table above.

## Current candidate and browser-discovered blockers

- `explicit-quantity-green-v2`: 215 passed. Explicit quantity corrections now accept `quantity to 12` and terminal sentence punctuation, while refusing fractional/identifier truncation.
- `qualification-correction-model/quantity-correction-model`: eight passed, one failed. All three image corrections pass. The ordinary positive qualification test intermittently fails: the proposed concept includes the whole research instruction rather than the exact workload identity, while the source evidence names the exact identity. The semantic reducer correctly refuses to equate these. Compilation covered the selected fictional RAM contract, but no evaluated shelf was delivered. **The positive journey is not reliably closed.** Do not fix this by substring-matching evidence or suppressing unrelated material requirements. Review the router's access to authenticated selected-contract context and the separation between entity identity and requested predicates.
- `operator-final-shop/recovery-final`: the uncertain-send, reviewed reconciliation, fresh replacement approval and revocation browser journey passed on a newly seeded shop.
- Source checkpoint `20261005-regression-delivery-candidate.zip`: 5,239 files, SHA-256 `54112803bc6250a28d82a89cd2626d437c22d94798d201fde0eb94ed0c8bbaeb`. SQLite backup integrity passed at migration 20260892. Archive member digests were verified after extraction. The broad Python API/service run is `frozen-regression-delivery/.artifacts/general-pytest`; result pending. The source index now lists 164 checkpoint-relative changed files; it is an index, not a line-by-line audit certificate.

No commit or publication has occurred. No new eight-hour soak is active while the broad suite runs.

## Follow-up verification and security boundaries

The entity-span prompt now asks for the smallest subject-name span while retaining other conditions as material unknowns; it adds no product vocabulary or evidence-matching shortcut. `qualification-entity-model/entity-span-qualification` passed six conversational tests, then `qualification-entity-repeat/entity-span-images-repeat` passed all nine conversational/image tests on another fresh fixture. These observed passes address the reproduced prompt failure but do not certify arbitrary model outputs or sustained model stability.

`operator-final-shop/inventory-merchant-final` passed four browser tests on the independent SQLite restore (operator inventory, merchant decision card and requirement-read recovery). `frontend-final.json` records all 403 frontend tests passing; TypeScript checking and the production build passed. The existing dynamic-import warning remains.

Additional red/green boundaries:

- Invalid approval bands could silently lower authority. Nine new cases failed before strict band/role validation; 33 approval/person/inventory tests passed afterward.
- Legacy operator roles could dispatch through the configured real ERP adapter without a person-bound grant. A mocked-provider red test reproduced that call. The legacy path now returns `independent_po_approval_unavailable` before any state transition or provider call when that adapter is selected. The 425-test fulfillment/legacy-tenant run passed. This is a deliberate live-effect block, not completed independent PO approval or recovery.
- An isolated Redis test reproduced local-cache resurrection during a worker connection partition after another cache instance erased the shared value. Versioned shared-cache reads now abstain when the shared backend is unavailable. `redis-partition-green-v2` passed 22 tests, including two against real Redis. The owned container was removed afterward. This uses separate cache instances, not separately deployed API workers; atomic index/value publication and distributed erasure during concurrent writes still need scrutiny.

The CI workflow provisions its own Redis service for these tests and gives each browser scenario a fresh fixture/runtime. This is local configuration work; a successful current remote CI run has not been observed. The frozen broad run predates the prompt, approval and cache changes in this section and must be supplemented by their focused receipts.

`memory-cache-final/memory-security-final` passed the combined real-API memory, commercial-interpretation, tenant-canary, artifact-security and requirement-read-recovery browser batch after the cache repair. The three existing model-image fixtures are now copied unchanged into `tests/fixtures/browser_images`, with source paths and SHA-256 hashes in its manifest; restored checkpoints no longer depend on unbundled `dump/test-cv` assets.

`20261005-cache-approval-browser-candidate.zip` preserves 5,244 files, SHA-256 `b3b566f6a86106d03043393b01ef82cce5d42b351f3b69ba06d4c559daaaafbf`, plus the integrity-checked migration-20260892 database. `linux-current-results/receipt.json` verifies that candidate's fresh fixture, independent database restore, migrations, readiness and authenticated case reload under Python 3.12.14 with external networking disabled. It reuses the previously clean dependency image and explicitly reports `clean_install=false`; it is not another package-install result or an independent-machine/browser certification.

## Completed broad run and remaining order-sensitive repairs

`frozen-regression-delivery/.artifacts/general-pytest` finished after 1,580.86 seconds: **7,745 passed, 11 failed, one setup error, 122 skipped** (7,879 cases). It is not green. The failure details are retained in `general-final-failures.json`.

The subsequent diagnosis reproduced two application/harness boundaries: Alembic logging configuration disabled existing application loggers, and the egress unpatch helper reloaded `httpx` without restoring its cached client methods. Migration logging now preserves existing loggers; guard removal restores the original sync/async methods. An older security test also reinstalled a removed guard during monkeypatch teardown; it now mocks transport underneath the real guard. Market and return-partner adapters report explicit policy denial rather than conflating it with provider unavailability or leaking a policy exception.

The legacy session-bridge tests now isolate their process-local memory, and the contract-shape fixture uses a disposable file-backed database instead of sharing one SQLite connection across background tasks and teardown. `contract-fixture-green` passed 59 with two skips. `egress-logging-order-green-v2` passed 105 with one skip, running the security tests before the affected adapters, migration logging, safe-stage logging and facade tests. These targeted repairs still need the next broad frozen rerun.

## Conversation erasure and catalogue projection follow-up

The new frozen broad rerun is `frozen-order-isolation/.artifacts/general-pytest`, from checkpoint `20261005-order-isolation-candidate.zip` (5,246 files; SHA-256 `f3c63f06249ce223d90ab9ab0f3273026fcd49fbaca54962f3929306d8ffae1f`). It was still running when this section was written. It predates the following memory and catalogue changes; no broad green result is claimed.

Conversation `Memory` had a related stale-local-copy problem, separate from the semantic cache. A missing shared key now invalidates the local value; a shared-backend read failure abstains. The explicitly local-only `DummyRedis` adapter identifies itself as nonshared, preserving the deliberate demo fallback without treating a dummy read as authoritative erasure. `conversation-erasure-green-v2` passed **82 tests**, including three against owned real Redis. `conversation-erasure-browser/memory-after-erasure` passed **11 real-API browser tests**, with no skipped or flaky cases. Concurrent writes racing with erasure and genuinely separate deployed workers remain unclosed boundaries.

`security-model-final/model-adversarial-boundaries` passed **three selected browser tests**, with a model-enabled runtime, cross-tenant canary and durable effect assertions. Some attacks are intercepted before model invocation; this is not model-wide red-team coverage.

A read-only catalogue benchmark exposed **98 missing brand and 98 missing category columns** in the old fictional-shop fixture. Parsed categories existed in JSON, but the seeder did not populate the filter columns; the legacy ORM does not map those columns. Both seed entry points now persist the parsed category and reuse the existing conservative, reviewed title-brand matcher. Unknown brands remain unknown; source snapshots gain no qualification or commerce authority. Existing fixture databases were not rewritten.

`catalog-contracts-original-gap.json` now records truthful `insufficient_data`, rather than crashing or passing zero cases. `catalog-contracts-repaired.json`, on a freshly migrated shop, reports **98 products, one unknown brand, zero missing categories**, passing the current catalogue's brand/budget retrieval predicates. Every repeated result is checked, and brand matching follows the retriever's case-insensitive semantics. This is not semantic relevance evaluation or a model/graph winner. `catalog-metadata-shop/catalog-memory-regression` passed **11 real-API browser checks** across memory, commercial interpretation and the merchant decision card, without skips or flaky cases.

The forecasting follow-up `rolling-variable-deliveries.json` applies the same realized delay sequence to candidate policies without exposing future delays to their decision inputs. Across 486 correlated synthetic variants, the challengers still do not justify promotion: retain the baseline. Twelve forecasting tests passed in `variable-delivery-green-v2`. Calibrated uncertainty, independently reviewed labels and broader operational scenarios remain open.

## Buyer supplier constraints

Five new behavior tests reproduced a real gap: buyer selection ignored freight when checking a total budget and ignored the recorded delivery deadline. `buyer_supplier_constraints.py` now consumes the current revision's typed requirements, rather than reparsing conversation text. Selection blocks on unresolved deadlines, lead estimates beyond the required instant, budget currency/scope ambiguity, over-budget amounts and conflicting revisions. Revalidation can invalidate a previously accepted estimate as the delivery window closes; the selection digest does not change merely because another second passes.

Per-unit budgets are compared to unit price, with freight explicitly separate. A partial offer's total covers only priced units; no full-order affordability claim is made for unpriced shortfalls. The UI exposes these limits and the deadline failure. `supplier-recovery-constraints-green` passed **52 service tests**; the frontend's three supplier-card tests and TypeScript check passed. The new deadline UI test was red before implementation. `catalog-combined-green` passed **17 import/benchmark tests**, including idempotent legacy imports.

This closes a bounded part of item 8, not purchasing authority or the full procurement workflow. MOQ/substitution checks still apply; a selected estimate remains nonbinding, and legacy PO/refund/order person approval and recovery remain open. The fresh model/browser rerun is recorded under `supplier-constraints-model/connected-supplier-constraints`; inspect its completion receipt before claiming success.

That model/browser rerun completed: **nine passed**, zero skipped/flaky, in 223.174 seconds. It includes normal fictional qualification, supplier selection, amendment invalidation, accessory acceptance and three images. It remains a short run, not endurance evidence.

The frozen order-isolation Python run also completed: **7,770 passed, one failed, 123 skipped** (7,894 cases; 1,679.735 seconds). The remaining RAG contract test expected a cache hit despite a deliberately disconnected Redis backend. Its cache-hit contract now explicitly installs a working isolated local cache; production shared-backend abstention was not weakened. `rag-cache-mode-green` passed 17 cache/memory tests. A final broad candidate rerun is still required, including the subsequent conversation-memory, catalogue and supplier-constraint changes. Source/function size ratchets passed; historical oversized-file warnings remain architectural debt.

## Final candidate verification in progress

`20261005-supplier-constraints-candidate.zip` contains 5,249 files, SHA-256 `0838632757943f92b2160f1b96f17755722ad2131e8ad643e5ced534d8e3db3c`; its SQLite backup has integrity `ok`, head `20260892_buyer_supplier_selection`. The archive was extracted with per-file hash checks into `frozen-supplier-constraints`, where the next broad Python run is executing. Do not infer its result from earlier receipts.

`linux-final-results/receipt.json` passed fresh fixture creation, migrations, independent backup restore, readiness and authenticated case reload for that candidate. `linux-rollback-clean-results/receipt.json` additionally passed source rollback to the previous cache/approval candidate and roll-forward to this candidate over the **same database**, retaining the authenticated case and identical effect-table snapshots. Network access was disabled. Dependencies came from the previously clean image; this is neither a new clean package installation nor remote deployment automation or a schema-downgrade test. The first rollback harness attempt failed while copying changing SQLite sidecars from the running test checkout; the corrected attempt extracted only the immutable archive.

`memory-worker-processes/receipt.json` passed four real-Redis checks, including separate spawned worker processes, a read partition, erasure from another process, reconnection, restart and a foreign tenant. This extends the earlier instance-only checks. It is still not a load-balanced API deployment test or proof against concurrent erase/write races. The owned Redis container and worker processes were cleaned up.

`frontend-supplier-final.json` records **404 passed**, zero failures/pending. TypeScript and production build passed, with the existing ineffective dynamic-import warning. Only the additional process test and documentation postdate the candidate's application source.

## Provider switch follow-up after the candidate freeze

The effect-sink review found that direct Stripe provider calls did not honor `PAYMENT_EXECUTION_ENABLED=0`; the background refund path does not pass through the HTTP guard. Two mocked-provider red tests reproduced the bypass. `payment_execution_policy.py` now provides the shared policy, and both Stripe intent/refund methods check it before SDK effects. The existing HTTP helper imports the same implementation. This does not replace buyer consent, exact-effect permits or distinct-person authorization.

`payment-boundaries-green` passed **71 tests, one skipped**, across provider policy, refunds, attempts, webhooks, HTTP concurrency and procurement payment consequences. An earlier focused run also exposed a configuration-test secret-cache leak: a synthetic Stripe test key survived into later tests. That test now clears both settings and secret caches on entry/exit; no real provider call was performed. This repair postdates the running frozen broad candidate and has its own focused evidence.

See [the effect-boundary review](EFFECT_BOUNDARY_REVIEW_2026-10-05.md) for concrete remaining refund/order/worker wiring gaps, and [demo and engineering evidence](DEMO_AND_ENGINEERING_EVIDENCE_2026-10-05.md) for defensible demonstration and hiring-manager claims.

`linux-payment-final-results/receipt.json` repeats the isolated restore and same-schema rollback/roll-forward successfully for the payment-boundary candidate (`51ea5d5e32003f406bc7a6281c9b0cc50307a8c0dd1c3d74451b578d663ec447`). Three restored-browser preflight tests passed in `frozen-final-endurance/.artifacts/endurance-shop/restored-preflight`. These are short checks; the eight-hour timer had not started at that point.

The final endurance preparation additionally isolates Vite's dependency cache per owned runtime, because frozen checkouts share installed `node_modules`. This prevents shared cache writes from being a test/developer-runtime interaction; it is not a diagnosis of the historical buffer failure. `20261005-endurance-isolation-candidate.zip` preserves 5,253 files, SHA-256 `c20d79d03c0092094e0ebf26282e9c257c8c3553df64ab6198303bf1043014e0`. Its hash-verified extraction is `frozen-isolated-endurance`. Only runtime-cache isolation, CI wiring and documentation differ from the preceding application candidate.

## Completed regression and active endurance run

`frozen-supplier-constraints/.artifacts/general-pytest/receipt.json` finished successfully in **1,714.438 seconds**: 7,906 cases, **7,782 passed, 124 skipped**, zero failures/errors. Its application source includes the conversation-memory, catalogue and supplier-constraint repairs. Subsequent payment-provider changes have the separate 71-test receipt and Linux restore/rollback evidence above; the broad result is not silently relabelled as a run of later source.

`skips.json` beside the broad receipt records every exclusion reason. These include 21 frozen V1 characterization cases, 20 slow cases, 19 tests expecting a separate port-8080 backend, and opt-in PostgreSQL, Redis, model and optional-dependency tests. Selected real Redis/PostgreSQL/model checks have separate receipts; that does not mean every skipped case was exercised. Python browser/load directories were explicitly excluded from this run, with TypeScript Playwright results reported separately.

The new isolated-cache preflight passed all three restored-browser checks and created its own `vite-cache/deps` directory. After the heavy regression process exited, host available memory was approximately 7.7 GiB. The eight-hour replay then started with unchanged limits: at least 1 GiB host memory available, each observed application process below 2 GiB RSS and 5,000 handles, and each browser cycle bounded to 180 seconds. The first cycle passed. Completion requires `status=passed` and the runner's final receipt; a launch or a one-hour checkpoint is not eight-hour certification. The run restarts Chromium each cycle and excludes sustained model/image traffic.
