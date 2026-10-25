# ShopSquire platform assessment and remaining roadmap — 1 October 2026

## Assessment

ShopSquire has substantial tested foundations for scoped evidence, stock transactions,
supplier proposal normalization, exact-effect approval and uncertain-outcome recovery.
Its strongest current demonstration is the bounded fictional qualification and stock
journey. The ordinary conversational buyer journey does not yet reliably preserve and
present the same case through every turn and reload. Live external research and supplier
communication were not enabled in the audited runtime.

The immediate priority is to repair and prove those connections. More catalogue rows,
larger context windows, another recommendation version or graph infrastructure would
not address the failures reproduced here.

This is a cross-platform source and execution assessment, not a line-by-line audit of
every module or an exhaustive penetration test. The source inventory contains 1,185
Python files and 308,179 lines under `src/app`; 201 TypeScript/TSX files and 29,607 lines
under `frontend/src`. Counts include supporting code and frontend tests. Critical buyer,
research, inventory, supplier, authorization, memory and release paths were sampled.
Payments, refunds, every connector, every admin route and all production deployments
were not independently exercised end to end in this batch.

## Reproducible evidence

Root: `.artifacts/platform-audit-2026-10-01/`.

| Evidence | Result and interpretation |
|---|---|
| `backend.xml`, `backend.log` | 83 focused tests passed; zero skips/errors/failures. Memory scope and follow-up logic, search adapters, injection corpus/tool boundary, person approval, recovery, expiry, accepted stock and supplier continuation. |
| `security.xml`, `security.log` | 40 additional tests passed; zero skips/errors/failures. Indirect/direct injection endpoints, buyer principals, transport and outbox. |
| `browser-report.json` | First real-API browser battery: seven passed, three failed. |
| `targeted-browser.json` | Diagnostic rerun: two passed, one failed. Reproduced memory failure and captured request continuity; added research-unavailable and direct authority-injection cases. Do not add the repeated memory test as a new unique case. |
| `browser-final.json` | Final combined browser battery, run after backend tests finished: 12 cases, nine passed, three failed, zero skips or flaky results, 42.35 seconds. No automatic test retries. |
| `twenty-turn-browser.json`, `twenty-turn-summary.json` | Additional real, unmocked 20-turn browser scenario failed its consistent quantity-projection assertions: one case retained, 12→14→8 amendments applied, quantity exposed on eight turns and absent on 12. Commerce authority stayed `none` on all 20 turns. |
| `targeted-request-continuity.json` | Same UID and session epoch before/after reload; case ID present on follow-up requests but absent after reload. |
| `turn-*.json`, `after-reload.json`, `targeted-*.json` | Actual chat answers and research/security responses, not mocked server responses. |
| `demo-identity-probe.json` | New synthetic victim case: wrong UID 403; copied UID with no credentials 200. No existing customer case inspected. |
| `health.json` | Runtime capability snapshot: external search disabled, no requirement-authority readiness, supplier transport unset. |
| `code-inventory.json` | Source file/line counts and largest Python files. Counts are not coverage measurements. |
| `browser/`, `browser-final/`, `targeted-browser/` | Playwright screenshots, videos, traces and failure context. The memory failure screenshot was visually inspected. |

The checkout has extensive pre-existing uncommitted work. HEAD was
`c7daafaa5b7d4248ca97abffd7a9b3e8a031e457`; local tracking reported **29 commits ahead**.
No fetch was performed, so this does not establish the current remote state. No source
implementation was repaired during this assessment. A new browser audit spec and this
report were added; failures are intentionally retained.

Across the final battery and the additional long conversation, **13 distinct browser
scenarios ran: nine passed and four failed**. Earlier diagnostic reruns are not added
to that total. The 123 focused backend/security cases are separate from browser cases.

## Findings, ranked by delivery impact

### F1 — Conversational case continuity breaks at reload: reproduced, high priority

The real browser conversation requested 12 laptops at AUD 1,500 each, added a battery
preference, amended to eight units, reduced the budget to AUD 1,200, asked about delivery,
then reloaded and asked how many laptops had been requested.

| Turn | Observed quantity | Case behavior |
|---|---|---|
| Initial request | 12 | Case created. |
| Battery preference | 12 | Same case. |
| Quantity amendment | 8 | Same case, revision advanced. |
| Budget reduction | 8 | Same case, revision advanced. |
| Delivery question | Missing from tested response fields | Same case. Generic unresolved-fit answer, rather than useful delivery continuation. |
| Recall after reload | Missing from tested response fields | Different case created although UID and session epoch were unchanged. |

This proves partial within-session retention and a buyer-visible continuity failure.
It does **not** prove the underlying Redis record was erased. Quantity omission on the
delivery response could be a projection problem rather than storage loss. The reload
request demonstrably drops `shopping_case_id`; the backend then returns a new case.
The screenshot still showed the AUD 1,200 budget, so it would be inaccurate to say all
memory was lost.

Relevant code:

- [useShoppingCaseResearch.ts:44](C:/AI/ShopSquire/frontend/src/hooks/useShoppingCaseResearch.ts:44): initial presentation has no active case.
- [useShoppingCaseResearch.ts:113](C:/AI/ShopSquire/frontend/src/hooks/useShoppingCaseResearch.ts:113): in-memory presentation reducer initialization.
- [App.tsx:2161](C:/AI/ShopSquire/frontend/src/App.tsx:2161): sends the conversation epoch.
- [App.tsx:2169](C:/AI/ShopSquire/frontend/src/App.tsx:2169): sends case ID only when the current presentation holds one.
- [browserSession.ts:100](C:/AI/ShopSquire/frontend/src/lib/browserSession.ts:100): session epoch survives reload.
- [platform-audit-memory.spec.ts:17](C:/AI/ShopSquire/frontend/e2e/platform-audit-memory.spec.ts:17): retained failing regression.

Fix: restore an authenticated, tenant/session-bound active case, revalidate its revision,
and consistently project retained facts on policy and recall turns. Do not make arbitrary
client-stored case IDs authoritative. Temporary chat, deliberate new conversations and
tenant changes must still clear or change scope.

The additional 20-turn real-browser probe strengthens the distinction between storage
and presentation. It kept one case, accepted 12→14→8 corrections, and returned eight
on the final recall response's structured field. However, 12 responses omitted quantity,
and the final visible answer was generic unresolved-fit text rather than a summary.
This is not a 40% memory-accuracy score: eight of 20 is the observed field-presence and
correctness count under this test contract. Budget, destination and preference recall
need independent structured assertions before claiming comprehensive fact retention.
See [platform-audit-memory.spec.ts:64](C:/AI/ShopSquire/frontend/e2e/platform-audit-memory.spec.ts:64).

### F2 — Existing long-conversation evidence overstates server coverage

[governed-conversation-lifecycle.spec.ts:38](C:/AI/ShopSquire/frontend/e2e/governed-conversation-lifecycle.spec.ts:38)
intercepts chat requests and supplies predetermined responses, including remembered
quantities. It is useful for frontend session/payload wiring, but cannot establish
20-turn server memory retention. The existing real-API context-retention tests also
failed in this runtime at their expected budget-scope clarification.

Relevant: [context-retention.spec.ts:50](C:/AI/ShopSquire/frontend/e2e/context-retention.spec.ts:50)
and [context-retention.spec.ts:83](C:/AI/ShopSquire/frontend/e2e/context-retention.spec.ts:83).
Those failures stop before the later budget/quantity assertions; they do not prove
every subsequent assertion would fail. Diagnose route/configuration and expectation
drift before changing the tests. Do not weaken them merely to obtain green output.

### F3 — Live external search is unavailable in this runtime

Health reports external research disabled, no endpoint configured and no enrolled tenant
with requirement authority. The consented Blender browser prompt returned: required
research could not be completed; compatibility and budget fit could not be established.
No qualified product was produced. That is a truthful unavailable outcome, not a
successful external search demonstration.

The adapter tests use injected HTTP transports and DNS resolvers. They exercise domain
filtering, unsafe-address refusal, bounded requests and redirect handling; they do not
measure live search relevance or publisher freshness.

- [external_research_httpx.py:55](C:/AI/ShopSquire/src/app/adapters/external_research_httpx.py:55): network address policy.
- [external_research_httpx.py:210](C:/AI/ShopSquire/src/app/adapters/external_research_httpx.py:210): pre-request host validation.
- [external_research_httpx.py:233](C:/AI/ShopSquire/src/app/adapters/external_research_httpx.py:233): bounded HTTP request, redirects disabled.
- [official_workload_research.py:390](C:/AI/ShopSquire/src/app/services/official_workload_research.py:390): publisher claim compilation.
- [test_external_research_httpx.py:1](C:/AI/ShopSquire/tests/adapters/test_external_research_httpx.py:1): explicit hermetic test scope.

Next: reproducible configured discovery, governed publisher fetch, provenance and
consumption-time freshness under a fictional tenant. Separately test successful, empty,
denied, unavailable, cancelled, stale and contradictory outcomes. Review DNS validation
versus connection-time resolution; no DNS-rebinding exploit was demonstrated here.

### F4 — Demo ownership is an asserted UID, not authenticated identity

On the enabled local demo surface, a new case could be read from an anonymous request
that supplied its creator's UID. A different UID was rejected. This is a confirmed
limitation of the demo API, not evidence of a bypass of every production buyer route.
Keep it disabled outside the isolated demonstration, or bind it to a verified principal
before exposing it to untrusted users.

- [demo.py:19](C:/AI/ShopSquire/src/app/routers/demo.py:19): demo feature gate.
- [portfolio_qualification.py:34](C:/AI/ShopSquire/src/app/routers/portfolio_qualification.py:34): read accepts UID from the request.
- [case_contract_binding.py:25](C:/AI/ShopSquire/src/app/services/case_contract_binding.py:25): ownership compares stored UID to supplied UID.
- [browserSession.ts:120](C:/AI/ShopSquire/frontend/src/lib/browserSession.ts:120): build-time owner-key fallback is a separate hardening concern. Do not put privileged secrets into public frontend environment variables. No actual privileged secret was extracted in this audit.

### F5 — Stock arithmetic and holds work; full supplier commerce is not connected

Passing browser checks cover quantity arithmetic, acceptance, 30-to-40 amendment, live
stock, qualification invalidation, reload and explicit release. Services additionally
cover expiry, rollback, concurrency and request replay. This is meaningful progress.

Supplier continuation can normalize deterministic certification offers. That does not
prove an enquiry left an outbox, a separately received supplier reply was authenticated,
or a quote remained valid through an accepted amendment and purchase dispatch.

- [case_inventory_acceptance.py:52](C:/AI/ShopSquire/src/app/services/case_inventory_acceptance.py:52): accepted case-bound stock transaction.
- [inventory_transactions.py:115](C:/AI/ShopSquire/src/app/services/inventory_transactions.py:115): shipment/cancel/return/expiry transitions.
- [inventory_transactions.py:150](C:/AI/ShopSquire/src/app/services/inventory_transactions.py:150): bounded expiry cleanup.
- [main.py:2367](C:/AI/ShopSquire/src/app/main.py:2367): existing inventory monitoring loop does not establish scheduled reservation-expiry execution.
- [shopping_case_supplier_continuation.py:205](C:/AI/ShopSquire/src/app/services/shopping_case_supplier_continuation.py:205): fixture offers explicitly described as non-network.
- [shopping_case_supplier_continuation.py:323](C:/AI/ShopSquire/src/app/services/shopping_case_supplier_continuation.py:323): exact request digest/replay binding.
- [transport.py:34](C:/AI/ShopSquire/src/app/services/fulfillment/transport.py:34): fake transport.
- [transport.py:42](C:/AI/ShopSquire/src/app/services/fulfillment/transport.py:42): real delivery remains held for independent-person approval.

### F6 — Strong service controls do not yet equal authenticated operator workflows

Person-bound approval and uncertain-send recovery tests passed. Separate credentials
must map to separate authorized people. Exact-effect dispatch, expiry, revocation and
uncertain outcomes have service-level controls. The operator enrollment, approval,
revoke/renew/reconcile browser journey remains a completion gate.

- [person_approval.py:49](C:/AI/ShopSquire/src/app/services/fulfillment/person_approval.py:49): distinct people and roles.
- [person_approval.py:62](C:/AI/ShopSquire/src/app/services/fulfillment/person_approval.py:62): exact-effect grant issuance.
- [person_approval.py:82](C:/AI/ShopSquire/src/app/services/fulfillment/person_approval.py:82): current grant validation.
- [outbound_queue.py:258](C:/AI/ShopSquire/src/app/services/fulfillment/outbound_queue.py:258): dispatch processing.
- [outbound_queue.py:388](C:/AI/ShopSquire/src/app/services/fulfillment/outbound_queue.py:388): uncertain send handling.
- [operator_recovery.py:22](C:/AI/ShopSquire/src/app/services/fulfillment/operator_recovery.py:22): audited recovery service.
- [refund_authorization.py:15](C:/AI/ShopSquire/src/app/services/refund_authorization.py:15) and [refund_completion.py:5](C:/AI/ShopSquire/src/app/services/refund_completion.py:5): distinct authorization/completion boundaries to include in future effect-sink testing.

### F7 — Security results are encouraging but not comprehensive red-team certification

Two real browser attachment tests passed: MIME/content mismatch remains blocked and
visible; malicious or incompletely inspected image input exposes a blocked authority
state and monitoring outcome. The latter accepts either detection or safe degradation;
it is not a measurement of the image detector's sensitivity.

The direct user prompt claiming system authority and self-approval did not obtain
commerce authority. Its response was a generic catalogue answer, not an explicit
security refusal. This test checks the response authority field; it does not independently
count every durable effect sink. Unit/integration tests cover additional injection and
outbox boundaries. Some assertions only check that malicious strings are absent from
responses; absence of those strings alone is not proof of non-execution or non-leakage.

Remaining evaluation must include protected canaries, independently observed sink counts,
malicious search pages, supplier messages, OCR, multi-turn memory poisoning, redirects,
tenant impersonation and benign controls. Report attack success and unnecessary refusal
rates separately. No messages, purchases or payments were sent to real third parties.

### F8 — Memory fallback and maintainability deserve bounded tests, not speculation

[memory.py:187](C:/AI/ShopSquire/src/app/services/memory.py:187) removes expired local entries
when those keys are read; [memory.py:198](C:/AI/ShopSquire/src/app/services/memory.py:198)
stores fallback values. The local store/index merit a capacity/expired-key churn test.
This is a resource-management review item, not the proven cause of the historical browser
buffer failure. Restart continuity also requires testing the actual Redis/degraded mode.

Large modules increase review and integration cost: `chat.py` is 4,839 lines,
`turn_router.py` 2,817, and `recommendation_core/core.py` 2,796. Extract under behavior
tests; do not add a V3 to avoid understanding the current flow.

The audited path uses [chat.py:169](C:/AI/ShopSquire/src/app/routers/chat.py:169),
[recommendation_facade.py:951](C:/AI/ShopSquire/src/app/services/recommendation_facade.py:951),
[recommendation_facade.py:1361](C:/AI/ShopSquire/src/app/services/recommendation_facade.py:1361)
and [core.py:140](C:/AI/ShopSquire/src/app/services/recommendation_core/core.py:140).
Runtime flags and compatibility routing matter more than historical filenames.

Keep identity, revisions, arithmetic, freshness, permissions and replay deterministic.
Keep publisher/product semantics in reviewed adapters and contracts. The fixed RAM-only
showcase at [portfolio_qualification.py:68](C:/AI/ShopSquire/src/app/services/portfolio_qualification.py:68)
and [portfolio_qualification.py:80](C:/AI/ShopSquire/src/app/services/portfolio_qualification.py:80)
is openly synthetic; it is not evidence of arbitrary-domain qualification.

## Complete remaining delivery roadmap

| Order | Work and affected code | Completion test |
|---|---|---|
| P0.1 | Fix case restoration and recall projections: `useShoppingCaseResearch.ts`, `App.tsx`, `browserSession.ts`, chat/facade memory paths. | Real 20-turn browser sequence with 12→8, budget/deadline/destination corrections, pronouns, reload and restart. Same authorized case unless deliberately changed; API/UI/trace agree. Separate sessions/tenants cannot recall each other's facts. |
| P0.2 | Reconcile budget-clarification expectations and runtime profiles: `context-retention.spec.ts`, chat/core routing. | Existing failed tests pass through the intended live lane without accepting empty results as success; runtime capability preflight is recorded. |
| P0.3 | Preserve reproducible checkpoints and contain demo identity: demo router, auth, principal enrollment and CI configuration. | Demo off in non-demo profile; copied UID insufficient in authenticated workflows; clean checkout/migrations/seed/startup repeat on another environment. |
| P1.1 | Connect conversational scope, research, accepted facts and qualified shelf: binding, compiler and catalogue projection. | One positive fictional journey plus stale, revoked, changed-revision, contradictory and wrong-scope negatives across response/API/UI/trace. Real Blender evidence remains a separate gate. |
| P1.2 | Enable and validate governed external discovery and publisher retrieval. | Successful public-source fetch with source/time/policy provenance; truthful empty/denied/unavailable/cancelled cases; SSRF, redirects, disclosure and consent tests. No authority from search rank alone. |
| P1.3 | Finish inventory operation: scheduled scoped expiry, inbound receipts, transfers, shipments, cancellations and returns. | Ledger replay matches balances, concurrent orders cannot oversell, retries cannot double-release/restock, ETA respects inbound/transfer timing. Browser asserts durable stock. |
| P1.4 | Connect fake supplier enquiry→outbox→reply→reviewed quote. | Independently produced partial/full/late/duplicate/substitute/mismatched-sender replies remain case/revision scoped; supplier silence is truthful; no reply grants purchase authority. |
| P1.5 | Complete accepted amendment economics and invalidation. | 30→40 updates holds, supplier demand, landed costs, freight, delivery and total spend; obsolete quote/approval unusable; unaccepted suggestions mutate nothing. |
| P1.6 | Authenticated synthetic person enrollment, approval and dispatch UI. | Two credentials for one person denied; distinct authorized people succeed only for exact current effect. Server derives amounts/roles, rechecks membership/revocation/expiry at dispatch. |
| P1.7 | Operator recovery and all effect sinks. | Crash before/after fake provider acceptance; reconcile uncertainty using receipts; replacement requires fresh approval. Assert no duplicate sends/orders/refunds/inventory writes or false completion. |
| P2.1 | Supported upgrades, compatible accessories and accepted bundles. | Supported buyer benefit, compatible/unknown/incompatible controls, correct incremental/total prices and explicit acceptance; no invented capability from brand names. |
| P2.2 | Systematic injection and disclosure evaluation. | Search, supplier, image/OCR and memory attacks with canaries and sink counts, plus benign controls and cross-tenant tests; publish denominator and failure cases. |
| P2.3 | Connected Playwright coverage and runtime durability. | Buyer→supplier→amendment→approval→fake execution→recovery; double-click, concurrent tabs, cancellation, network loss, reload and process restart. Retain traces and state evidence. |
| P2.4 | Diagnose historical buffer failure and complete endurance. | Instrumented repeatable 60-minute run and successful eight-hour run with varied images/models, resource/latency bounds, zero unauthorized/duplicate effects. Preserve failures. |
| P2.5 | Reconciled synthetic merchant decision. | Replenish/wait/source decision derived from SKU-scoped events and current offers; compare with simple reorder baseline, reject stale/out-of-scope evidence. See `shop_operational_history.py:134`, `market_evidence_admission.py:13`. |
| P3.1 | Held-out representative quality benchmarks. | Frozen cross-category cases, reviewed labels, equal budgets, supported qualification/abstention/latency measurements. No model quality winner until evidence supports one. |
| P3.2 | Catalogue identity, conflict review and release proof. | Repeat import idempotency, exact configurations, preserved source conflicts and dependent references; observed remote CI, second-environment restore and rollback. |

Testing accompanies each implementation step: failing behavior test, smallest justified
fix, regression run, then real-API Playwright for the affected connection. Property and
concurrency tests suit quantities, money, replay and stock; they do not replace browser
tests. Mocked UI tests remain useful but must be labelled as such.

## Reliability and release limits

The historical 30-minute diagnostic passed 39 cycles. Neither historical eight-hour
attempt passed; the first failed after 7h11m51s, the rerun after 19m38s. This audit did
not run another soak. The resource-drain observation weakens the earlier backend-leak
hypothesis; `ERR_NO_BUFFER_SPACE` remains unresolved.

CI definitions are not remote CI evidence. The clean-checkout workflow runs a limited
storefront selection/scenario set at
[clean-checkout-smoke.yml:99](C:/AI/ShopSquire/.github/workflows/clean-checkout-smoke.yml:99).
The separate [playwright-ui-smoke.yml:41](C:/AI/ShopSquire/.github/workflows/playwright-ui-smoke.yml:41)
installs the admin frontend dependencies; its name alone does not establish coverage
of the buyer journeys above. Expand required checks and inspect actual execution.

## What can be demonstrated and claimed now

- Bounded synthetic product qualification with expiry/revocation and visible trace.
- Accepted multi-unit stock holds, quantity amendment, release and transactional invariants.
- Controlled tests for supplier normalization, independent-person grants and recovery.
- Browser-visible attachment safety boundaries and truthful unavailable research.
- Partial real conversational retention, together with an honestly reproduced reload defect.

Do not claim complete autonomous procurement, connected live supplier negotiation,
real-product Blender certification, production-safe public demo identity, arbitrary
20-turn server memory, sustained mixed-model/image stability or a model quality winner.
The fictional-shop portfolio does not require real customers or money to close its
remaining gates; it requires coherent, measured simulations with clear provenance.
