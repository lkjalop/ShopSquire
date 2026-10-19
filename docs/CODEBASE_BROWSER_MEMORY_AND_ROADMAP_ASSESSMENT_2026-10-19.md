# ShopSquire codebase browser memory and roadmap assessment

**Execution follow-up:** this document preserves the initial assessment. Several findings below have since been repaired and regression-tested. Read [the execution, TDD and release-gate report](EXECUTION_TDD_AND_RELEASE_GATES_2026-10-19.md) for current repair status, browser failures, complete test accounting and safe local commits. The platform remains below release green.

Assessed 19 October 2026, Australia/Sydney, against working-tree HEAD `c7daafaa5b7d4248ca97abffd7a9b3e8a031e457`. ShopSquire has substantial implemented commerce, evidence, inventory and approval machinery, but the current tree is not ready for release. Fresh checks demonstrate failures in memory erasure, case continuity, tenant onboarding, resource limits and a CI architecture gate. Structured quantity and budget recall works in the tested conversations; that does not establish completion of the buyer's email or market-intelligence task.

## Review coverage

The inventory covers **5,617 eligible files and 970,523 text lines**, including tracked files and nonignored untracked files. Application code under `src/app` accounts for 1,212 files and 311,004 lines; `frontend/src` accounts for 231 files and 35,034 lines. All eligible Python files in source, tests, scripts, migrations and SDK were parsed and structurally scanned. The primary frontend received a TypeScript check, unit tests and a production build. The admin frontend was also tested and built.

This is a repository-wide mechanical inventory plus a detailed semantic review of the important execution paths. **It is not a claim that a human-equivalent semantic review was completed for every one of the 970,523 lines.** The file inventory records the checks applied to each file. Binary assets, generated outputs, deployment infrastructure, deprecated UI code and unexercised provider integrations do not receive a correctness certificate from these checks.

Evidence is retained in [the audit artifact directory](../.artifacts/deep-audit-2026-10-19/), particularly [file-inventory.csv](../.artifacts/deep-audit-2026-10-19/file-inventory.csv), [inventory.json](../.artifacts/deep-audit-2026-10-19/inventory.json), [browser-summary.json](../.artifacts/deep-audit-2026-10-19/browser-summary.json) and [reproductions.json](../.artifacts/deep-audit-2026-10-19/reproductions.json). Generated runtime credentials remain in ignored private fixture files.

## Release blocking findings

### Memory erasure can report completion while indexed data survives

**P1, reproduced.** [memory.py](../src/app/services/memory.py), `_register_key` around line 178 and `_set_json` around line 205, performs index registration and value storage separately. Index failures are swallowed; a later value write can succeed. After worker replacement, `erase_subject` has neither a Redis index member nor the previous worker's local index entry, and reports zero erased keys while the value remains readable.

The reproduction deliberately fails `SADD`, permits `SETEX`, replaces worker-local state, and requests erasure. Result: `erased_keys: 0`, one Redis value remains, and the synthetic private marker is recalled. This is different from the already handled case where deletion itself raises `memory_erasure_incomplete`.

Make successful writes and index membership one atomic backend operation. Treat incomplete index registration as a failed write or record a durable retry obligation. Add replacement-worker, concurrent write/erase and partial Redis-operation regressions; an empty index must not imply complete erasure without a trustworthy indexing invariant.

### A search follow up for the same workload replaces its selected case

**P1, reproduced in the model-disabled runtime with enrolled fictional evidence.** Six ordinary qualification scenarios fail at case continuity. An initial request for Fictional Memory Lab version 1, followed by selection of its memory-capacity requirements and a search for that same workload, produces a different case ID. The response marks the original selection `stale_case_revision` and records `subject_switch_boundary.cleared_fields: [canonical_case]`.

One recorded transition changes case `sc-dc0314052dd2b9f5ecd35560f70e20df` to `sc-98ca726b77e5020bafaff69c4ee5cb5a`. The initial role is `PROCURE_SUBJECT`; the follow-up role is `COMPATIBILITY_CHECK`. The exact routing cause needs a focused regression around [chat.py](../src/app/routers/chat.py), lines 1046 and 2660, and the subject-switch decision. Model unavailability should withhold unsupported fit conclusions while preserving an explicitly selected, unchanged case.

The generic quantity/budget memory tests and the FreeCAD search conversation pass, so this is a specific continuity defect rather than evidence that all memory is broken. Preserve the failing initial and qualification responses in `qualified-cpu/qualified-clickthrough` when repairing it.

### Storefront tenant routing and native registration disagree

**P1, reproduced.** Public registration and login pass, but the subsequent ordinary shopping message returns **403** in a storefront configured for `synthetic-electronics`. The same empty-profile scenario passes in the default storefront.

[LoginModal.tsx](../frontend/src/components/LoginModal.tsx), line 27, sends only a JSON content-type header. [api.ts](../frontend/src/lib/api.ts), around line 39, adds the configured storefront tenant to ordinary application requests. [auth.py](../src/app/routers/auth.py), around line 713, enrolls the customer in the current request tenant. Registration therefore creates a default-tenant customer and chat requests the configured tenant. Use the same trusted routing convention throughout registration, login, cart and chat; keep server membership checks enforced.

### Local memory expiration does not bound retained process state

**P1 for retention and endurance, reproduced.** [memory.py](../src/app/services/memory.py), `_local_get` and `_local_setex` around lines 193 and 205, removes an expired value only when that exact key is read. There is no periodic eviction or size limit on the class-wide local value and subject-index dictionaries. Successful shared Redis writes also populate this local store.

After 200 short-lived subjects expire, reading one subject leaves **199 expired value entries and 200 subject-index entries**. This establishes a retention mechanism; it does not establish that this mechanism caused all observed pytest growth. Add bounded eviction and consistent index cleanup, including idle sessions and shared-backend deployments.

### The legacy async bridge does not enforce its stated deadline

**P1 hang risk, reproduced with bounded work.** [orchestrator.py](../src/app/services/orchestrator.py), line 11, retains a private `_run_async_safe` implementation using `ThreadPoolExecutor` as a context manager. When `future.result(timeout=300)` times out, context exit waits for the worker. An indefinitely stuck worker can therefore keep the caller stuck after the nominal deadline.

The reproduction uses the exact function body, shortens only the future timeout to 30 ms, and supplies a 250 ms coroutine. The timeout reaches the caller after about **265 ms**, after the worker completes. The newer [async_safe.py](../src/app/services/async_safe.py) avoids executor shutdown waiting, but its synchronous queue wait still blocks a calling event-loop thread; a 250 ms heartbeat probe demonstrates that property. Consolidate the bridges, keep synchronous work off the request event loop, and bound the underlying I/O. No indefinitely hanging production request was deliberately created.

### Outbound email monitoring crosses tenant data boundaries

**P1, reproduced through authenticated HTTP and at the service boundary.** [outbound_email_monitor.py](../src/app/services/outbound_email_monitor.py), `_recent_events` around line 194, filters by agent without tenant; `list_outbound_anomalies` around line 398 reads anomalies without a tenant predicate. Setting the active tenant to `audit-a` still returns rows for both `audit-a` and `audit-b`.

The administrative endpoint at [admin_email_security.py](../src/app/routers/admin_email_security.py), around line 3113, requires a privileged role and tenant membership, but then calls the unscoped reader twice. In a private migrated database, an owner credential enrolled only in `audit-only-a` receives **HTTP 200 and both tenants' anomaly rows** when requesting its own tenant. A direct request to `audit-foreign-b` with that same credential correctly returns **403**. Thus membership enforcement works while the authorized reader leaks foreign rows. [outbound-scope-http.json](../.artifacts/deep-audit-2026-10-19/outbound-scope-http.json) records the result. Thread the authorized tenant through analysis and listing, and reserve any global SOC view for a separately explicit capability.

### Optional S3 upload silently bypasses sanitization

**P1 when `USE_S3_UPLOADS` is enabled, confirmed in source.** [cv.py](../src/app/routers/cv.py), line 1204, calls `sanitize_image` without importing or defining it in that upload function. The import around line 260 belongs to a different function. The `NameError` is caught and the branch uploads the original `content` bytes instead.

Use the canonical sanitizer in this upload boundary and make sanitization failure explicit. Verify the bytes passed to a fake storage adapter; disabling the S3 option does not exercise this path.

### Broad backend execution exceeds the existing resource gate

**P1 release gate, measured.** The selected broad run completed **5,208 passing checks and six skips** before controlled termination. The final sample records **2,572,087,296 bytes RSS and 5,806 handles** in the owned pytest process. The repository's endurance guard uses 2 GiB per process and 5,000 handles. The process exited 15; its receipt is not a successful full-suite receipt.

All remaining selected cases were completed in fresh bounded processes, with overlapping identities deduplicated: **6,380 passed and 32 skipped across 6,412 selected identities, zero assertion failures and zero unaccounted identities**. This includes four tests separately rerun against owned Redis; eleven additional PostgreSQL checks also pass. Passing the cases separately cannot turn the original resource gate into a pass. Investigate per-fixture engine ownership, native resources, app caches and worker lifetime with setup/teardown measurements. A test-process resource failure alone does not prove an equivalent production leak.

### The architecture ratchet currently fails CI

**P1 release gate, reproduced.** `scripts/check_function_sizes.py` exits 1 because `main.py:create_app` is **2,223 lines**, above its recorded **2,206-line** ceiling. `.github/workflows/clean-checkout-smoke.yml` runs that check. The separate source-file-size check and `git diff --check` pass. Review the extra lifecycle wiring and extract a coherent responsibility rather than silently raising the ceiling.

## Buyer task completion and browser reliability

The [custom browser sequence](../.artifacts/deep-audit-2026-10-19/deep-audit-journey-20261019.spec.ts) uses real local APIs and real read-only discovery: **30 laptops → approved external search → correction to 40 → request to draft a shortfall email → market-intelligence question → summary → reload and recall**. Every step retains the current quantity, AUD 1,500 per-unit budget and Sydney delivery allocation, and the effect snapshot remains unchanged.

The separate twenty-turn conversation keeps one case ID while correcting quantity 12→14→8, destination and budget. Its serialized response sizes remain approximately **80.7–81.5 KB**, with the case-memory section approximately 31 KB; this sequence does not exhibit recursive payload growth. Durable accepted facts are restored from SQL, scoped Redis/local memory supplies conversational context, and the frontend carries the current case/session. Successful fact retention in that path coexists with the cache-lifetime and subject-replacement defects above.

However, the email request returns “No exact in-catalog match right now” and the market question returns unresolved product-fit prose. Neither completes the requested task in the model-disabled profile. Requiring an accepted SKU and current stock before asserting a shortfall is appropriate; the answer should explain those prerequisites and lead to the supported action. It should not silently substitute another product-search answer. The new scenario's passing assertions establish memory continuity and absence of commercial effects, **not email or market-answer quality**.

The operator supplier journeys do pass: an accepted request produces a server-calculated shortfall; requester self-approval is rejected; a different enrolled person approves; fake dispatch occurs once across replay; partial, substituted, wrong-sender, expired and duplicate replies are handled; and a 30-to-40 amendment invalidates old quotes and approval. This is useful implemented behavior. The new enquiry panel displays request and quote metadata but does not expose the exact recipient, email subject and body for review; the backend `_effect` in [supplier_enquiry_journey.py](../src/app/services/supplier_enquiry_journey.py), around line 109, constructs those bytes. Improve the review presentation before claiming a complete draft-review experience. Real mailbox sending and supplier authentication remain separate integrations.

In the first supplier browser receipt, the current request is **30 units, 14 held and 16 short**. Its enquiry correctly uses 16 units. Amending the request to **40** retains 14 held and recalculates **26 short**, with fresh approval required. A one-unit partial quote at AUD 700 plus AUD 120 freight is assessed at **AUD 820**, rather than charging for the entire 16-unit shortfall. Five reply variants are retained and the original transport-attempt count stays at one. These are actual current-run values, not the older demonstration's assumed 15-unit stock snapshot.

The live discovery response records HTTP 200, ten results, approximately 1.69 seconds transport latency, a responding Yandex engine and a failed Privacywall engine. Research remains `publisher_resolution_required` / `publisher_not_yet_accepted`, with `identity_resolver_disabled` in this profile. Discovery succeeds; a fully researched and qualified FreeCAD machine is not established.

Browser logs also need attention. The development batch records **130 ASGI exception entries**, repeated `No response returned` stacks, 46 oversized Jaeger packet warnings and 882 file-token incident warnings. These are not 130 proven completed HTTP 500 responses; client disconnect/cancellation is a possible contributor. The configured preview batch still records 27 ASGI exception entries. Trace/browser assertions currently do not fail on these server errors. Classify expected disconnects, investigate unexpected failures, and add log/error assertions to reliability gates. The oversized telemetry warnings disappear in the preview profile that explicitly disables tracing and Jaeger; `OTEL_SDK_DISABLED` alone did not prevent them in the first profile.

There is also measurable lifecycle/request overhead in the remaining integration suite: the five-shape recommendation contract test takes **84.6 seconds** with `USE_MOCK_LLM=1` and `ROUTER_MODEL_ENABLED=0`, and a single success-shape test takes 19.8 seconds. Those tests include creating and closing an ASGI client, so these are test durations rather than isolated request latency measurements. Profile startup, shutdown, dependency retries and actual request work separately; model inference cannot explain every slow path in this profile.

A direct authority-injection request is blocked in the configured tenant, but its response lacks `terminal_outcome`. This fails the common envelope assertion; it does not demonstrate an unauthorized purchase. Standardize blocked responses while preserving the denial.

The configuration scan finds two malformed Grafana JSON files: [the provisioned ShopSquire dashboard](../config/observability/grafana/dashboards/shopsquire-dashboard.json), line 47, and [the documentation dashboard](observability/grafana_dashboard.json), line 69. Both contain an object inserted into an unfinished object. `docker-compose.observability.yml` mounts the first dashboard directory into Grafana's configured provisioning path, so this is a real configuration defect, not only a documentation typo. A Grafana browser was not started to quantify its user-facing failure. Validate dashboard JSON in CI. Helm templates were checked with Helm rather than treated as standalone YAML; `helm lint helm/shopsquire` passes.

## Test isolation defects

[inventory-scheduler.spec.ts](../frontend/e2e/inventory-scheduler.spec.ts), lines 8 and 23, hard-codes `C:/AI/ShopSquire/.artifacts/connected-shop-2026-09-28/shop.sqlite3` rather than the supervised runtime database. Both browser batches therefore fail to find the created hold in their own UI. The preparer also disables the expiry scheduler by default, and this spec does not use the authenticated buyer helper. These failures do not prove the inventory expiration service is broken.

The test wrote two synthetic probe cases into the older disposable fixture. Their exact reservation IDs were identified; both audit-created holds are now expired, and their case history was retained. [expiry-probe-cleanup.json](../.artifacts/deep-audit-2026-10-19/expiry-probe-cleanup.json) records the compensation. No production database or real supplier/payment transport was used. Repair the spec to consume the runner's database, Python executable, identity and explicitly enabled scheduler before using it as release evidence.

The security governance tests also publish into the actual `config/security/cv_playbooks.json` registry. Its pre-audit bytes were recovered from an existing checkpoint only after their SHA-256 matched the initial inventory exactly, and those exact bytes have now been restored. [registry-restoration.json](../.artifacts/deep-audit-2026-10-19/registry-restoration.json) records the matching hashes. Move these tests to a temporary registry; resetting this already-dirty file to HEAD would discard pre-existing changes.

The initial ordinary fixture lacked the fictional research enrollment required by six qualification specs. Those six first-run failures are fixture/configuration failures. A second fixture enrolls fresh fictional evidence and product observations with model endpoints disabled; that rerun exposes the case-continuity failures described above. Three image tests fail with `model_artifact_invalid_expected_digest` in the model-disabled first profile. They establish degraded/unavailable behavior, not a successful vision-model run. No GPU inference or GPU endurance pass is claimed.

## Code structure and Git hygiene

The maintainability concern is substantive, although large functions and broad handlers are indicators rather than proof that each line is wrong:

| Source | Current size | Consequence |
| --- | --- | --- |
| `routers/chat.py:_chat_query_impl` | 4,464 lines; 555 branch-like AST nodes including nested code | Routing, memory, research, case transitions, narration and response projection are concentrated in one function. |
| `main.py:create_app` | 2,223 lines | Startup, registration, middleware and ownership changes are difficult to isolate; the ratchet fails. |
| `security/email_security.py:evaluate_email_security` | 2,021 lines | Policy and evidence failures can be difficult to attribute. |
| `recommendation_core/turn_router.py:_route_turn_raw` | 1,340 lines | Subject classification and continuity need smaller independently testable decisions. |
| `recommendation_core/core.py:_recommend_turn` | 1,303 lines | A second large orchestration boundary remains despite decomposition. |
| `frontend/src/App.tsx` and `DecisionTrace.tsx` | 4,373 and 4,372 file lines | State transport, presentation and compatibility handling remain tightly coupled. |

There are **99 production Python functions over 200 lines**, **5,618 broad exception handlers**, and **2,120 handlers whose only body is `pass`**. Ruff across `src/` and `scripts/` reports **1,205 findings**, including 12 undefined-name reports and two local-before-assignment reports. Some are harmless or explicitly recovered: the local `time` reference in authentication is caught and re-imported. Others, such as the sanitizer bug, change behavior. The one-line `passive_payload_analysis_new.py` contains a bare `test` expression; it parses but fails if imported. Remove or account for abandoned source instead of treating syntax success as runtime coverage.

An absolute-import scan finds nine candidate dependency cycles, including groups of 16 and 14 modules. These include function-local imports, so they establish architectural coupling rather than nine demonstrated import-time failures. The graph receipt identifies the modules. Existing extraction work, typed case models, explicit effect contracts and person approval are useful foundations; prioritize small cuts across ownership boundaries rather than another wholesale version rewrite.

At inventory time Git contains **590 changed paths: 294 tracked changes, 296 untracked files, zero staged**. HEAD was committed on 12 September 2026. The local upstream comparison is 29 ahead and zero behind; no remote fetch was made, so this is not a current remote-sync assertion. Untracked paths include required services, UI, tests and migrations: a checkout of HEAD does not contain the tested working implementation.

The high-signal changed-file secret scan finds no matches for the four configured token/private-key patterns. It is not comprehensive secret clearance. Twenty-nine `.log` files are already in the eligible tracked/untracked inventory, including historical run output. The [roadmap index](../.artifacts/deep-audit-2026-10-19/roadmap-index.json) covers **71 roadmap Markdown files and 19,752 lines**; the March sprint document explicitly excludes B2B procurement while the newer roadmap centers it. The older production master roadmap also advocates graph/vector expansion everywhere, whereas the current benchmark roadmap conditions expansion on measured need. Choose one current roadmap and mark older scope statements historical.

All surviving inventoried files match their initial content digests after cleanup, including the restored playbook registry. The temporary cross-intent browser spec is retained with the audit evidence. A generated pytest runtime marker was removed by test cleanup; the new assessment replaces it in the final 590-path Git status count. Existing application edits are preserved, with zero staged files and no commit or push. [final-tree.json](../.artifacts/deep-audit-2026-10-19/final-tree.json) records the comparison.

## Fresh verification results

| Check | Result and interpretation |
| --- | --- |
| Primary frontend unit tests | 404 passed; zero failures or pending tests. |
| Primary frontend TypeScript and build | Both exit 0. Existing mixed static/dynamic import warning remains. |
| Admin frontend unit tests and build | 50 tests passed; TypeScript and Vite build exit 0. |
| Main Python dependency check | `pip check` passes. The separate `.venv_new` fails fixture migration because Alembic is incomplete there. |
| Python syntax scan | No syntax errors in scanned eligible Python files. |
| Configuration syntax and Helm | 1,087 JSON, 69 YAML/template and two TOML files inspected. Two malformed Grafana JSON files; Helm lint passes. |
| Source file size / function size / diff checks | Source file ratchet passes; function ratchet fails; `git diff --check` passes. |
| Initial development browser batch | 22 passed, 10 failed, zero skips/flaky; 32 executions, 381.5 seconds. Includes missing fictional enrollment and disabled vision-model cases. |
| Enrolled fictional preview browser batch | 19 passed, 10 failed, zero skips/flaky; 29 executions, 248.3 seconds. Six fail same-workload case continuity; other failures include tenant registration, selection UI, blocked envelope and the hard-coded expiry fixture. |
| Live consented discovery | One passed, 10.8 seconds. Real dispatch and results; product qualification remains unresolved. |
| Search through quantity, draft request, market question and reload | One passed, 17.2 seconds. Seven response checkpoints; facts and effect counts checked, task-completion gaps retained above. |
| API process restart | Both phases pass with different server process IDs and the same durable case facts, without shared Redis. |
| Fresh owned Redis | Four tests passed, zero skipped: exact scope, cross-instance erasure, partition behavior, separate worker processes and restart. Included in the selected backend identity total. The container was removed. These do not cover the failed-index-write reproduction. |
| Fresh owned PostgreSQL | Eleven tests passed, zero skipped, covering release/effect races and uncertain outcomes with fake effects. The private 512 MiB container was removed. |
| Browser total | 65 executions across 35 distinct scenario identities. 45 passing and 20 failing executions; three scenarios have mixed results across profiles. Do not sum overlapping runs as unique coverage. |
| Broad selected backend run | 5,208 passed and six skipped before the resource stop; exit 15. Fresh-process remainder accounting is recorded separately. |
| Deduplicated selected backend total | **6,380 passed, 32 skipped, zero assertion failures, zero unaccounted identities** across 6,412 selected cases, including fresh-process remainder runs and the owned-Redis rerun. The resource gate remains failed. See [backend-accounting.json](../.artifacts/deep-audit-2026-10-19/backend-accounting.json). |

The selected backend set comprises **6,412 tests** from services, API, security, unit, scripts, integration and observability. The eleven owned-PostgreSQL cases are additional to that set. Python browser/load suites, other unselected directories, real provider certification and long-duration browser/GPU endurance are outside that set. Browser effects use sandbox transports and disposable databases, with the expiry-test exception documented above. Final integrity checks pass on all three audit shop databases; all ten owned browser API/UI ports are closed. [final-checks.json](../.artifacts/deep-audit-2026-10-19/final-checks.json) records cleanup and the passing diff check.

## Complete active roadmap

Preserve the existing 0–13 numbering, but replace broad “complete” claims with the following gates. A useful simulated demo and production readiness are different milestones.

| Item | Current assessment | Completion gate |
| --- | --- | --- |
| **0 Reproducibility and isolation** | Main environment migrates/seeds; builds pass; alternate environment and expiry harness fail; 590-path dirty tree. | Fix test/database isolation and environment bootstrap. Review coherent source, config, migration and test commits; verify a fresh committed checkout and independently restored data. |
| **1 Conversation memory** | Quantity, budget, currency, destination, deadline, twenty turns, reload and restart pass selected cases. Erasure indexing, cache retention and selected-workload continuity fail. | Atomic index/value/erasure behavior, bounded cache lifetime, unchanged-case research, correction and category-switch tests, real Redis worker/race recovery, UI/API/trace agreement. |
| **2 Market dataset** | Synthetic operational history and merchant fixture are implemented; selected service checks exercise reconciliation. | Reconcile receiving, sale, return, cancellation, transfer, commitments and ETA against balances; preserve missing/censored observations and observation cutoffs on representative data. |
| **3 Merchant intelligence** | Persisted synthetic decision, attributable source text and wrong-tenant denial pass. Buyer prose does not answer the market question in the fallback profile. | Useful scoped buyer/operator answers, reviewed corpus and labels, current citations, explicit sparse/dense status, conflict/staleness abstention, repair remaining unscoped readers. |
| **4 Forecasting** | Implemented baseline/challenger machinery; historical 486 correlated synthetic variants do not justify promotion. No new model-quality winner is established. | Rolling held-out operational evaluation with equal information/runtime budgets, realistic lead-time variation, cost/stockout/excess/deadline metrics and calibrated uncertainty. Keep the baseline until improvement is measured. |
| **5 Positive buyer journey** | Dedicated fictional demonstrations and stock surfaces work. Ordinary selected-workload qualification fails continuity in the CPU fallback. Live discovery alone does not establish fit. | Native tenant enrollment → same case and consent → governed source acceptance → compiled requirements → exact qualified configuration → current shelf and trace. Test unavailable models and all invalidation paths. |
| **6 Inventory** | Stock acceptance, amendments, transfers, shipment/return/cancellation and person approvals pass selected browser flows. Expiry browser proof is invalid due to harness isolation. | Repaired connected scheduler test on the owned database; reservation/location reconciliation, retry/race/expiry correctness and PostgreSQL concurrency under load. |
| **7 Supplier conversations** | Fake draft/send/replay/review and shortfall corrections pass. Natural email request is not fulfilled; enquiry UI omits exact email preview. | Continue naturally from the accepted case, calculate current shortfall, preview exact recipient/content, independently approve that payload, authenticate replies and disclose partial/substitute/stale outcomes. Keep real transports gated until tested. |
| **8 Amendments and approval** | Current fake enquiry invalidation and new approval after 30→40 are exercised. Earlier approval preflight ordering is repaired in source. | Atomic approval/outbox behavior, known integer spend, current MOQ/freight/tax/landed cost/deadline, current revision and distinct-person authorization at every dispatch. Include unknown spend, enqueue failure and concurrency. |
| **9 Recovery** | Uncertain fake supplier recovery, revocation and renewal pass selected journeys. | Reconcile observed provider outcomes after lost response/crash without duplicate sends; complete authenticated operator recovery for payment/refund/order/ERP sinks and expose truthful pending/failed states. |
| **10 Bundles and cart** | Dedicated bundle/upgrade acceptance tests pass; ordinary qualification-linked accessory test is blocked upstream. | Current compatibility/benefit evidence, correct quantities and totals, explicit acceptance and permit expiry, ordinary chat/cart integration and concurrent amendment safety. |
| **11 Security and browser** | Important direct/tenant/approval boundaries pass; outbound monitoring scope, optional upload sanitization and blocked-envelope consistency need repair. | Tenant-scoped reads, sanitized stored bytes, secret review, direct/indirect/OCR/memory attacks with canary/effect counts, ordinary user success and accessibility; inspect server failures as well as page text. |
| **12 Endurance and release** | Fresh broad process exceeds resource limits; browser logs contain unresolved exceptions; architecture gate fails; historical GPU/display incident remains unresolved. | Fix resource ownership and observed browser failure modes; pass bounded API/browser endurance, then longer runs. Review host graphics before model/image endurance. Require clean-checkout CI, rollback, independent restore and deployment evidence. |
| **13 Representative benchmarks** | Useful synthetic fixtures and contract tests exist; model-disabled tests do not establish model quality. | Independently reviewed held-out tasks across unfamiliar categories, equal budgets, approved baseline publication, end-task success and groundedness metrics; add retrieval/graph/model complexity only for measured error classes. |

The older commerce/support scope also needs an explicit owner and acceptance list: warranty and purchase verification, complaint triage, escalation, repair/returns/refunds, insurer/ERP connectors, payment provider certification, reporting and legacy/admin consoles. These areas have substantial code and some selected API coverage, but this audit does not establish complete browser/provider readiness for each one. The deprecated `src/frontend/storefront-react` package explicitly directs users to the supported frontend; do not revive it as a second active storefront.

**Execution order:** preserve and review the current tree → repair erasure, tenant enrollment, case continuity and hanging bridges → repair harness isolation and resource ownership → prove ordinary buyer tasks and exact supplier draft review → complete connected approval/recovery and security gates → pass endurance and clean-checkout release gates → expand datasets and evaluate models against held-out tasks. Do not add more features or another orchestration layer to compensate for these boundary failures.
