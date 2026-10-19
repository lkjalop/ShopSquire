# ShopSquire roadmap and implementation plan for 20 October 2026

ShopSquire has working parts of a governed procurement system, but the complete conversational procurement journey and release gates remain open. The immediate objective is a reproducible checkout that completes external research, quantity amendments, an exact shortfall draft and cited market intelligence within one owned case. Database stalls, Python dependency findings and incomplete integration commits must be resolved alongside those user workflows.

This plan uses the execution completed on 20 October 2026 in Australia/Sydney. Source anchors refer to the working tree based on `b3ac5d62a68bd97e4e46330d1b232392cc43b51a`, with **302 modified/deleted tracked paths, 307 untracked paths and no staged paths** before this document was added. Many anchors therefore describe uncommitted code. Line numbers identify current entry points; they are not proposed replacement line counts.

The [execution report](EXECUTION_TDD_AND_RELEASE_GATES_2026-10-19.md), [machine-readable results](audits/2026-10-19-execution-summary.json), [per-file inventory](audits/2026-10-19-file-inventory.csv) and [browser case ledger](audits/2026-10-19-browser-cases.csv) are the supporting evidence. The companion [source map](audits/2026-10-20-roadmap-source-map.csv) records the referenced paths, line numbers, file sizes, Git state and byte hashes so later edits cannot silently inherit this assessment. Earlier roadmap documents remain historical records. Their instructions and completion claims do not override the user's request or these newer results.

## Overall progress and its limits

Five scoped repair commits changed **26 distinct files, with 746 insertions and 281 deletions**, including tests and dependency lockfiles. Each received verification from an exported candidate. A sixth commit, `b3ac5d62`, recorded the assessment. Current tracked work outside those commits contains **5,938 insertions and 3,514 deletions across 302 paths**; this excludes the contents of 307 untracked paths. These figures measure source changes, not completed product scope.

| Area | Earlier observed state | Latest verified delta | What remains |
| --- | --- | --- | --- |
| Memory erasure | Failed index registration could leave shared values outside the erasure index; local expiry left stale subject entries. | Atomic Redis write/index and subject erasure, bounded local retention, failed-erasure protection; six owned-Redis checks pass, including worker restart and concurrent write/erase. | Load-balanced API semantics, durable failed-erasure recovery and the complete privacy retention policy. |
| Application lifetime | Twenty application lifetimes retained apps; controlled RSS increased from approximately 303 to 798 MB. | Weak tracing ownership and logging reuse; a later controlled diagnostic retained zero apps and increased approximately 293 to 309 MB. | Scheduler/SQL ownership and production endurance. These diagnostics are not a matched production benchmark. |
| Frontend dependencies | Storefront audit had four findings; admin had three. | Patched toolchain and lockfiles; both audits reported zero. Current UI has 407 storefront and 50 admin passing tests, types and builds. | Python dependency remediation and verification of the complete source candidate. |
| Image storage and responsiveness | Optional storage could receive original metadata; slow synchronous work delayed unrelated async requests. | Sanitized bytes only, fail-closed storage on sanitizer failure, slow work offloaded; controlled health request stays below 350 ms. | Enabled OCR security projection, hostile-input breadth and sustained service behavior. |
| Qualified buyer journey | Six normal fictional qualification cases failed during assessment. | All six now pass with selected-contract continuity and consistent presentation. | PDF/plain-text continuity, the wider transition matrix and live official-source qualification. |
| Cross-intent memory | A market question could disturb continuity in the search/quantity/draft sequence. | Same case, amended quantity 40, AUD 1,500 per unit and Sydney destination survive the tested sequence and reload. | The same generic conversation still has null email-draft and market-evidence fields. |
| Supplier review | Exact approval message was not fully visible in the enquiry screen. | Recipient, subject and body now match the simulated effect reviewed for approval. | General chat handoff, real authenticated mailbox integration and purchasing continuation. |
| Anomaly API | Later duplicate definitions shadowed the public mapping-based scorers. | Four new red regressions; seven focused checks pass after duplicate removal. | Statistical detection quality is a separate evaluation. |
| Broad execution | Earlier runs stopped on process memory/handle limits. | A 55.2-minute process completed within sampled limits. | It still exited 1 with 36 failures and eight setup errors; SQLite stalls remain open. |
| Git integration | 590 dirty paths, no staged work, before the assessment. | Five verified repair commits plus the assessment; recovery snapshots retained. | 609 dirty paths remain. More dirty paths do not imply more defects; coherent dependency groups still need committing. |

There is **no defensible single completion percentage**. Tests overlap across source versions and profiles, roadmap items have different sizes, and several passing checks cover simulation boundaries. The release gate is red; selected behavior gates are green.

| Evidence set | Recorded result | Consequence |
| --- | --- | --- |
| Full Python process | 7,836 passed, 36 failed, eight errors, 124 skipped out of 8,004 selected. | Functional failure. The run started during remediation and is not certification of the final source. |
| Eighty fresh Python cohorts | 7,843 passed, 29 failed, 119 skipped. Original failures later retested as 28 passes and one OCR skip. | Useful isolation and repair evidence; the skipped defect and single-process failure remain open. |
| All selected TypeScript browser specs | 161 unique cases across 76 spec files: latest observations are 49 passes, 80 failures and 32 skips. | Broad browser gate remains red. Failures include fixture/prerequisite/oracle problems and actual workflow defects. |
| Latest critical browser cases | 25 pass; a separate read-only live retention replay also passes. | Supports the named qualification, memory, inventory, approval/recovery and artifact boundaries. |
| Separate services | Six owned-Redis and eleven owned-PostgreSQL checks pass. | Supports those bounded service profiles. |
| Default Python browser and load directories | Five pass, two fail, 127 skip. The load failures return 503. | No successful-load latency or throughput claim. |
| Python dependency audit snapshot | Locked API: 94 package-advisory matches in seven packages. Installed environment: 105 in eighteen. | Remediate and re-audit the declared installation. Counts include advisory aliases and are not independent exploit demonstrations. |

Of 8,143 collected Python identities, receipts show 7,927 executed at least once and 216 unexecuted under their gates. This identity accounting includes earlier source versions. It is neither branch coverage nor a percentage of the final source proved correct.

## Source size and where to work

The captured inventory contains **5,635 eligible files and 971,931 text lines**. That includes documentation, fixtures, configuration and some nonignored logs; it is not 971,931 lines of application logic. Files were mechanically read and fingerprinted. The inventory records where semantic review was partial; it does not certify every line manually.

| Captured path group | Files | Text lines |
| --- | ---: | ---: |
| `src/app/` | 1,213 | 311,177 |
| `tests/` | 1,498 | 263,823 |
| `frontend/src/` | 233 | 35,087 |
| `frontend/e2e/` | 79 | 7,842 |
| `src/frontend/admin-react/` | 84 | 19,790 |
| `scripts/` | 281 | 26,500 |
| `docs/` | 513 | 151,161 |

These are disjoint selected path groups, not a partition of the whole repository. Frontend package groups can include manifests and lockfiles. The browser spec count is smaller than the e2e directory file count because that directory also contains helpers.

| High-risk entry point | Current size | Reason to prioritize |
| --- | --- | --- |
| [`chat.py:288`](../src/app/routers/chat.py#L288), `_chat_query_impl` | Function 4,473 lines; file 4,836. | Intake, routing, case updates, research and presentation can disagree about one turn. |
| [`main.py:271`](../src/app/main.py#L271), `create_app` | Function 2,205 lines; file 2,485. | Middleware, database access, background workers and lifecycle share ownership. |
| [`turn_router.py:1451`](../src/app/services/recommendation_core/turn_router.py#L1451), `_route_turn_raw` | Function 1,343 lines; file 2,820. | Model suggestions, deterministic rules and continuity decisions overlap. |
| [`email_security.py:836`](../src/app/security/email_security.py#L836), `evaluate_email_security` | Function 2,021 lines; file 2,856. | Detection, persistence and side effects need separate failure boundaries. |
| [`core.py:183`](../src/app/services/recommendation_core/core.py#L183), `_recommend_turn` | Function 1,303 lines; file 2,797. | Evidence, qualification and recommendation projection are highly coupled. |
| [`db.py:164`](../src/app/models/db.py#L164), `_ensure_minimal_sqlite_tables` | Function 998 lines; file 1,465. | Runtime schema repair complicates migration and transaction ownership. |

The assessment found 99 production functions over 200 lines, 5,609 broad exception handlers and 2,116 handlers containing a bare `pass`. These are review signals. The observed import graph has ten possible cycles, including deferred imports; it does not prove ten import failures. Undefined-name gates pass, while the broader Ruff gate remains red. Existing size ratchets grandfather large functions, so passing those ratchets does not establish maintainability.

## Delivery order and completion levels

P0 below means work that enables trustworthy integration and testing. P1 means a demonstrated workflow defect or a required pilot/release boundary. P2 means broader coverage, maintainability or a capability expansion. These priorities order work; they do not assign a security severity score.

| Work package | Priority | Current state | Main dependency | Completion level |
| --- | --- | --- | --- | --- |
| W00 Reproducible integration commits | P0 | Open; narrow commits verified, wider candidate failed. | None. | All subsequent gates. |
| W01 Database and worker ownership | P1 | Demonstrated stalls and locking remain. | W00 candidate boundary. | Reliable local operation and pilot. |
| W02 Declared Python dependencies | P1 | Advisory findings and environment drift remain. | W00 manifest. | Pilot and release. |
| W03 Same-case evidence intake | P1 | PDF/plain-text workflow defect remains. | W00, W01 for broad execution. | Complete local journey. |
| W04 Turn continuity and amendments | P1 | PLC refinement still replaces workload. | W00; coordinate with W03. | Complete local journey. |
| W05 Chat to shortfall draft | P1 | Narrow simulated workflow works; general handoff missing. | W03, W04, current stock acceptance. | Complete local journey, then mailbox pilot. |
| W06 Chat to cited market intelligence | P1 | Scoped services exist; general task output missing. | W04, W14 data admission. | Complete local journey and useful pilot. |
| W07 Distributed memory and privacy | P1 for privacy obligations | Redis repairs verified; broader recovery open. | W00, W01. | Pilot and release. |
| W08 Inventory and migrations | P1 | Selected transactions work; wider restart/concurrency open. | W01, W04. | Pilot and release. |
| W09 Exact approvals and landed costs | P1 | Selected person-bound effects work; legacy paths remain. | W05, W08. | Pilot and release. |
| W10 Recovery across effect sinks | P1 | Selected simulated recovery works; sink matrix incomplete. | W09. | Pilot and release. |
| W11 Bundles and upgrades | P2 | One reviewed fictional accessory path works. | W04, W08, W09. | Broader product scope. |
| W12 Browser contracts and security profiles | P1 | Broad browser gate red; OCR check skipped. | Runs throughout W00–W10. | Trustworthy journey and release gates. |
| W13 Architecture and error handling | P2, targeted P1 slices | Large coupled functions remain. | Characterization tests for each extraction. | Maintainability; unblock W01/W03/W04. |
| W14 Data and benchmark credibility | P1 for intelligence inputs; P2 for advanced claims | Synthetic baselines exist; generalization unproved. | W00, W02. | Useful intelligence; separately, comparative quality claims. |
| W15 Frozen release and endurance | P1 | No final complete candidate or eight-hour pass. | Required W00–W14 pilot gates. | Release. |

W01 and W02 can proceed independently after the candidate and environment manifests are defined. W03/W04 establish case semantics before W05/W06 are certified. Targeted extractions in W13 should accompany fixes; a wholesale rewrite is unnecessary for the next complete local journey. Advanced forecasting/model comparisons are separate from proving that the user can complete that journey.

## W00 Assemble reproducible integration commits

**Code to work:** [`buyer_principal.py:41`](../src/app/security/buyer_principal.py#L41), [`LoginModal.tsx:30`](../frontend/src/components/LoginModal.tsx#L30), [`api.ts:45`](../frontend/src/lib/api.ts#L45), [`main.py:271`](../src/app/main.py#L271), [`cart.py`](../src/app/routers/cart.py), [`outbound_email_monitor.py:195`](../src/app/services/outbound_email_monitor.py#L195), [`clean-checkout-smoke.yml:40`](../.github/workflows/clean-checkout-smoke.yml#L40), and the imports/migrations needed by those paths.

**Change:** classify all 609 dirty paths by dependency group and intended commit. Preserve the existing mixed work and recovery snapshots. Assemble native tenant identity, route registration, headers, schema and tests together; assemble case/research/UI continuity as another coherent group. Export each candidate into a clean directory, install declared dependencies and test without reading untracked files from the original checkout. Add all required new modules and migrations explicitly.

**Tests:** [`test_native_buyer_tenant_enrollment.py:8`](../tests/api/test_native_buyer_tenant_enrollment.py#L8), [`test_native_buyer_surface_auth.py:21`](../tests/api/test_native_buyer_surface_auth.py#L21), [`test_outbound_monitor_tenant_boundary.py:13`](../tests/api/test_outbound_monitor_tenant_boundary.py#L13), LoginModal tenant-header tests, and the clean-checkout workflow. Run both frontend type checks separately from builds; the storefront build script currently only runs Vite at [`package.json:8`](../frontend/package.json#L8).

**Done when:** each new commit passes from its own exported source with no missing imports/routes/headers/migrations, foreign-tenant denial and explicit revocation intact, and a documented dependency profile. The prior wider candidate failed backend boundaries, UI headers and type checking; passing in the original tree cannot close this package. A source checkpoint protects work but does not make that work a release candidate.

## W01 Remove database stalls and own worker lifetimes

**Code to work:** observer middleware at [`main.py:1441`](../src/app/main.py#L1441), security persistence at [`observer.py:833`](../src/app/security/observer.py#L833) and [`escalation_room.py:1771`](../src/app/routers/escalation_room.py#L1771), SLA transactions at [`incident_sla_scheduler.py:66`](../src/app/services/incident_sla_scheduler.py#L66), shutdown at [`incident_sla_scheduler.py:165`](../src/app/services/incident_sla_scheduler.py#L165), lifecycle at [`business_background_lifecycle.py:14`](../src/app/bootstrap/business_background_lifecycle.py#L14), and session routing at [`db.py:1165`](../src/app/models/db.py#L1165).

**Change:** trace the actual session/connection owner through incident creation, alert dispatch and trace logging. Shorten write transactions; remove nested independent writes while an outer SQLite writer holds the database. Give each app explicit start/stop ownership and report a worker that fails to stop. Separate the security decision from persistence/alert delivery with explicit durability and failure contracts. Offload blocking work only after its connection ownership is safe; a timeout on `to_thread` does not stop the worker or its writes.

**Tests:** extend [`test_business_background_lifecycle.py:20`](../tests/bootstrap/test_business_background_lifecycle.py#L20) with real file-backed SQLite contention, repeated startup/shutdown, an incident-producing request and an unrelated health request. Exercise PostgreSQL with independent sessions. Assert no orphan schedulers, no hidden failed writes, bounded request/shutdown behavior and no cross-request session reuse. Include [`test_http_metric_cardinality.py:9`](../tests/observability/test_http_metric_cardinality.py#L9) to protect the handle repair.

**Done when:** the reproduced request no longer takes 151.56 seconds, required requests meet their recorded budgets, worker shutdown is observed rather than assumed, and the full process has no lock/setup failures within unchanged resource limits. The captured stack identifies the blocked path; a single definitive root cause has not yet been established. Merely setting `OBSERVER_THREADED=1` on shared SQLite would leave the ownership defect unresolved.

## W02 Align dependencies with the tested installation

**Code to work:** [`pyproject.toml`](../pyproject.toml), [`generate_runtime_requirements.py:132`](../scripts/generate_runtime_requirements.py#L132), [`requirements/api-runtime.txt`](../requirements/api-runtime.txt), [`requirements/vision-runtime-windows.txt`](../requirements/vision-runtime-windows.txt), and CI installation at [`clean-checkout-smoke.yml:40`](../.github/workflows/clean-checkout-smoke.yml#L40).

**Change:** choose a compatible FastAPI/Starlette and transitive dependency set; resolve the recorded cryptography, Pillow, protobuf, PyJWT, python-multipart, Starlette and urllib3 findings. Regenerate all supported Linux/Windows profiles from their declared sources. Install each relevant profile into a fresh environment and retain installed-version and advisory manifests. Select exact upgrades against current upstream compatibility and advisory evidence when implementing; this plan does not prescribe unverified version pins.

**Tests:** requirement-generation regressions, `--check` for each generated profile, `pip check`, advisory audit, native authentication, multipart uploads, streaming chat, ORM/migration behavior, sanitized images and the critical browser journey. Confirm that tools/test dependencies are separated from the deployed API profile.

**Done when:** a clean declared installation reproduces required behavior and the security gate has no unresolved applicable findings or unexplained environment drift. Frontend audit zero and `pip check` zero do not establish this Python security gate.

## W03 Keep uploaded and pasted evidence in the owned case

**Code to work:** intake/proposal creation at [`chat.py:2768`](../src/app/routers/chat.py#L2768), source resolution at [`shopping_cases.py:1323`](../src/app/routers/shopping_cases.py#L1323), proposal acceptance at [`shopping_cases.py:693`](../src/app/routers/shopping_cases.py#L693), [`source_requirement_review.py:31`](../src/app/services/source_requirement_review.py#L31), [`case_binding.py:65`](../src/app/services/recommendation_core/case_binding.py#L65), and the UI guard at [`App.tsx:3063`](../frontend/src/App.tsx#L3063).

**Change:** decide whether evidence continues the existing subject before creating its proposal; bind the owned case, proposal version and response installation to the same case revision. Keep explicit new-subject replacement separate. Preserve the UI's earlier-case rejection rather than bypassing it. Acceptance must keep unresolved per-claim corroboration visible when research is unavailable, using [`requirement_claim_reconciliation.py:127`](../src/app/services/requirement_claim_reconciliation.py#L127).

**Tests:** PDF at [`uploaded-requirements-journey.spec.ts:94`](../frontend/e2e/uploaded-requirements-journey.spec.ts#L94), plain text at [line 138](../frontend/e2e/uploaded-requirements-journey.spec.ts#L138), screenshot at [line 45](../frontend/e2e/uploaded-requirements-journey.spec.ts#L45), manual entry at [line 188](../frontend/e2e/uploaded-requirements-journey.spec.ts#L188), and API acceptance at [`test_shopping_case_requirement_acceptance.py:91`](../tests/api/test_shopping_case_requirement_acceptance.py#L91). Add genuine replacement, stale response, double acceptance, foreign owner and reload cases.

**Done when:** all formats can review, correct and accept in the same owned case, while a stale proposal still fails safely. Blocked corroboration must show a truthful blocked state; successful official research requires a separate enabled-provider test. An offline test expecting completed research needs an explicit contract correction, not manufactured evidence.

## W04 Resolve refinement and amendment transitions consistently

**Code to work:** [`turn_router.py:1451`](../src/app/services/recommendation_core/turn_router.py#L1451), [`turn_transition.py:124`](../src/app/services/turn_transition.py#L124), [`conversation_case_state.py:746`](../src/app/services/conversation_case_state.py#L746), [`case_binding.py:136`](../src/app/services/recommendation_core/case_binding.py#L136), and [`research_outcome.py:231`](../src/app/services/research_outcome.py#L231).

**Change:** trace why the PLC size answer supplies a switch/supersede signal. Require explicit, bounded evidence of subject replacement; use the owned pending question and accepted subject for refinement. Do not globally prioritize pending questions over genuine replacement. Keep quantity, money scope, currency, destination and deadlines in the atomic committed state; render message, trace and panel from that one revision.

**Tests:** the failing third turn in [`turn-transition-revision-matrix.spec.ts:38`](../frontend/e2e/turn-transition-revision-matrix.spec.ts#L38); transition priority at [`test_turn_transition.py:9`](../tests/services/test_turn_transition.py#L9); case binding at [`test_case_contract_binding.py:53`](../tests/services/test_case_contract_binding.py#L53); literal/canonical provenance at [`test_chat_case_continuity.py:39`](../tests/services/test_chat_case_continuity.py#L39). Cover refinement, answer, additive workload, explicit replacement, category change and commercial amendment, including out-of-order responses.

**Done when:** “Mostly small PLC models, but occasionally a large factory model” refines/answers the active workload, explicit replacements still invalidate old authority, and every projection reports the same case/revision and retained commercial facts. Earlier message/panel agreement is repaired; that did not repair this remaining classification.

## W05 Complete the chat to shortfall email draft handoff

**Code to work:** chat dispatch at [`chat.py:288`](../src/app/routers/chat.py#L288), case operations at [`turn_router.py:1032`](../src/app/services/recommendation_core/turn_router.py#L1032), shortfall calculation at [`supplier_enquiry_journey.py:69`](../src/app/services/supplier_enquiry_journey.py#L69), creation at [line 82](../src/app/services/supplier_enquiry_journey.py#L82), exact preview at [line 188](../src/app/services/supplier_enquiry_journey.py#L188), and [`SupplierEnquiryPanel.tsx:53`](../frontend/src/components/SupplierEnquiryPanel.tsx#L53).

**Change:** add a governed conversational operation that opens/reuses the current enquiry draft. Return structured recipient, subject, body, SKU/configuration, requested units, covered units, shortfall, current revision and missing inputs. Derive shortfall from the accepted selection and current reservations/fulfillment state. Resolve supplier contact through a trusted adapter. If the product or stock is unresolved, collect that input and allow a clearly provisional draft without claiming an exact shortfall. Drafting must not grant dispatch approval.

**Tests:** extend [`live-research-memory-assessment.spec.ts:44`](../frontend/e2e/live-research-memory-assessment.spec.ts#L44), which currently attaches completion fields without asserting they exist. Add a controlled positive browser test with 40 requested and 25 valid covered units: the exact draft must request 15, remain in the same case and create no send/payment/order effect. Verify expired holds, fulfilled/returned units, quantity amendment, missing product, missing supplier and stale revision. Reuse [`test_supplier_enquiry_journey.py:47`](../tests/services/test_supplier_enquiry_journey.py#L47) and its expiry checks at [line 115](../tests/services/test_supplier_enquiry_journey.py#L115).

**Done when:** ordinary language produces a reviewable draft or precise missing-input state; the qualified positive fixture produces the correct exact draft. A 40-unit request with no known stock must never invent a 15-unit shortage. Dispatch requires a separate current approval. Live mailbox credentials, inbound authentication and reply handling form a subsequent explicitly configured integration gate.

## W06 Complete cited market intelligence in the same conversation

**Code to work:** bounded recall grammar at [`case_read_operations.py:4`](../src/app/services/recommendation_core/case_read_operations.py#L4), [`turn_router.py:1032`](../src/app/services/recommendation_core/turn_router.py#L1032), [`market_intelligence_agent.py:200`](../src/app/services/market_intelligence_agent.py#L200), admission at [`market_evidence_admission.py:13`](../src/app/services/market_evidence_admission.py#L13), retrieval at [`merchant_evidence_retrieval.py:97`](../src/app/services/merchant_evidence_retrieval.py#L97), [`market_pipeline.py:20`](../src/app/services/market_pipeline.py#L20), and [`MarketIntelligencePanel.tsx:25`](../frontend/src/components/decision-trace/MarketIntelligencePanel.tsx#L25).

**Change:** retain the recall route's case continuity and add an explicit intelligence execution/result contract. Retrieve admitted observations for the case's tenant, SKU or clearly labelled broader category. Return source citation, observation/fetch time, expiry, subject scope, relevant claim and conflicts/unknowns. Surface provider failure separately from empty results; `gather_market_context` currently catches exceptions and can return its default empty shape. Search snippets and a successful discovery call must not become accepted official requirements or supplier commitments.

**Tests:** replace passive completion attachment with explicit positive/blocked output checks beside [`live-research-memory-assessment.spec.ts:48`](../frontend/e2e/live-research-memory-assessment.spec.ts#L48). Extend scope/freshness tests at [`test_merchant_evidence_retrieval.py:35`](../tests/services/test_merchant_evidence_retrieval.py#L35), market pipeline tests and evidence-admission tests. Include stale, future, foreign-tenant, wrong-SKU, conflicting and injection-bearing sources. Test benign relevant evidence too. Verify unchanged quantity, budget, destination and commercial effect snapshots.

**Done when:** an enabled controlled source produces a useful cited answer in the same case; unavailable sources produce a specific blocked/partial result. Run a separately labelled live read-only source test for freshness/relevance. A generic retained-facts response with null evidence does not close the user task.

## W07 Extend memory guarantees across API workers and recovery

**Code to work:** atomic scripts at [`memory.py:53`](../src/app/services/memory.py#L53), writes at [line 253](../src/app/services/memory.py#L253), erasure at [line 367](../src/app/services/memory.py#L367), [`conversation_case_state.py:746`](../src/app/services/conversation_case_state.py#L746), and shared-cache consumers.

**Change:** keep the verified Redis atomicity. Define and implement the persistent recovery contract for failed erasure and worker replacement, including ownership of retry/tombstone state. Inventory all retained data planes: conversation/cache, SQL cases/events, traces, uploads, search/evidence records and backups; assign retention/erasure behavior rather than equating Redis deletion with complete privacy erasure. If Redis Cluster is a deployment target, separately design key-slot compatibility; current scripts are verified on a single Redis server.

**Tests:** [`test_owned_redis_semantic_scope.py:158`](../tests/integration/test_owned_redis_semantic_scope.py#L158) already exercises real process partition/restart. Add load-balanced HTTP workers, deletion during backend failure, worker replacement before recovery, and service restart after acknowledged erasure. Preserve regression tests at [`test_memory_retention_regressions.py:15`](../tests/services/test_memory_retention_regressions.py#L15). Extend the twenty-turn browser case at [`platform-audit-memory.spec.ts:119`](../frontend/e2e/platform-audit-memory.spec.ts#L119) with interdependent amendments and ambiguity.

**Done when:** the defined erasure acknowledgement cannot be followed by stale disclosure through a fresh API worker, and failed operations remain visible/recoverable under the declared policy. Retention tests must assert expiry and capacity, not just successful immediate reads. The local 64 MiB bound covers serialized payload, not all Python memory overhead.

## W08 Verify inventory under concurrency and existing data

**Code to work:** [`inventory_transactions.py:37`](../src/app/services/inventory_transactions.py#L37), reservations at [line 134](../src/app/services/inventory_transactions.py#L134), expiry at [line 193](../src/app/services/inventory_transactions.py#L193), [`inventory_expiry_scheduler.py:13`](../src/app/services/inventory_expiry_scheduler.py#L13), [`case_inventory_acceptance.py:52`](../src/app/services/case_inventory_acceptance.py#L52), Alembic migrations and existing-record reconciliation.

**Change:** complete multi-worker reservation/amend/release/expiry/restart behavior and migrate pre-existing records into the current identities. Keep stock movements and accepted-case selection in the intended transaction. Reconcile scheduled expiry, late receipts, transfers, shipment, cancellation and returns without creating stock twice. Preserve explicit distinctions between original fulfilled demand and separately accepted replacement demand.

**Tests:** [`test_inventory_transactions.py:32`](../tests/services/test_inventory_transactions.py#L32), [`test_inventory_expiry_scheduler.py:11`](../tests/services/test_inventory_expiry_scheduler.py#L11), stock-movement/reconciliation tests, PostgreSQL simultaneous allocator tests and browser accepted-stock/expiry journeys. Add restart between claim and commit, duplicate delivery, competing amendments and upgrade from an existing database snapshot.

**Done when:** stock conservation and available-to-promise invariants hold through each failure window, stale revisions lose, replays have no extra effect, and a migrated existing database produces the same truthful read model as a fresh database. Selected fresh-fixture checks already pass; they do not cover every existing-record and scheduler transition.

## W09 Complete approval binding and landed cost coverage

**Code to work:** [`person_approval.py:72`](../src/app/services/fulfillment/person_approval.py#L72), validation at [line 93](../src/app/services/fulfillment/person_approval.py#L93), [`approval_policy.py:41`](../src/app/services/fulfillment/approval_policy.py#L41), [`purchase_order.py:52`](../src/app/services/fulfillment/purchase_order.py#L52), [`commercial_terms.py:59`](../src/app/services/commercial_terms.py#L59), [`refund_execution.py:181`](../src/app/services/refund_execution.py#L181) and all reachable legacy order/payment/connector execution paths.

**Change:** inventory every effect sink and its trusted person, tenant, case/revision, payload hash, value, currency, expiry and revocation checks. Make full-order landed cost explicit, including freight, tax/fees where known, MOQ and unresolved quantities. A partial quote cannot silently satisfy the whole order. Amendments must invalidate incompatible grants and exact message previews must match dispatched bytes.

**Tests:** [`test_person_approval.py:37`](../tests/services/fulfillment/test_person_approval.py#L37), [`test_effect_sink_postgres.py:12`](../tests/chaos/test_effect_sink_postgres.py#L12), supplier amendment checks at [`test_supplier_enquiry_journey.py:93`](../tests/services/test_supplier_enquiry_journey.py#L93), and legacy payment/PO tenant tests. Race revocation and amendment against final dispatch; use two credentials for one person as a self-approval negative control.

**Done when:** every enabled sink has an independent current approval for its exact effect, full and partial coverage are explicit, and budget/quantity/delivery changes cannot reuse stale authority. The selected simulated supplier and PO checks establish part of this matrix, not all legacy routes.

## W10 Recover uncertain effects without duplicates

**Code to work:** [`outbound_queue.py:258`](../src/app/services/fulfillment/outbound_queue.py#L258), [`operator_recovery.py:23`](../src/app/services/fulfillment/operator_recovery.py#L23), [`supplier_enquiry_recovery.py:25`](../src/app/services/supplier_enquiry_recovery.py#L25), [`purchase_order.py:122`](../src/app/services/fulfillment/purchase_order.py#L122), [`refund_completion.py:5`](../src/app/services/refund_completion.py#L5) and payment/ERP provider adapters.

**Change:** enumerate crash windows before send, after provider acceptance, before local receipt and during recovery. Persist intent and trusted observation; distinguish unknown, submitted, acknowledged and independently completed states. Require reconciliation before replacement, and fresh approval where the payload or scope changes. A local timeout must not authorize a second provider effect.

**Tests:** [`test_operator_recovery.py:17`](../tests/services/fulfillment/test_operator_recovery.py#L17), [`test_supplier_enquiry_recovery.py:38`](../tests/services/test_supplier_enquiry_recovery.py#L38), [`supplier-recovery.spec.ts:15`](../frontend/e2e/supplier-recovery.spec.ts#L15), PostgreSQL effect-sink checks and fake provider counters. Repeat the failure-window matrix for email, PO/ERP, payment, refund and inventory movement. Assert one observed effect and accurate UI status across restart.

**Done when:** every enabled effect path either completes with an independently meaningful receipt or stays visibly uncertain without duplicate retry. Blocking an unsafe purchase order is correct boundary behavior; it is not a completed purchasing workflow.

## W11 Broaden reviewed bundles and upgrades

**Code to work:** [`governed_product_offers.py:31`](../src/app/services/governed_product_offers.py#L31), acceptance at [line 126](../src/app/services/governed_product_offers.py#L126), product relationship evidence and recommendation/UI offer projection.

**Change:** broaden reviewed compatibility to additional configurations, accessories, substitutions, discounts and upgrades. Revalidate current stock, price, quantity, fit evidence and budget at acceptance. Keep explicit acceptance and idempotency; relationship similarity alone cannot create compatibility evidence.

**Tests:** [`test_governed_product_offers.py:41`](../tests/services/test_governed_product_offers.py#L41) and [`conversational-qualification.spec.ts:79`](../frontend/e2e/conversational-qualification.spec.ts#L79). Add incompatible hardware, expired evidence, concurrent price/quantity changes and partial stock with amendment/reapproval.

**Done when:** supported combinations have independently reviewed evidence, stale offers fail safely, and accepting an offer updates the same case and exact cost once. One fictional accessory case is the current positive evidence.

## W12 Make browser and security gates trustworthy

**Code to work:** [`frontend/playwright.config.ts`](../frontend/playwright.config.ts), [`tests/conftest.py`](../tests/conftest.py), [`run_playwright_memory_safe.py:17`](../scripts/run_playwright_memory_safe.py#L17), [`check_agent_connectivity.py:28`](../scripts/check_agent_connectivity.py#L28) and its duplicate at [line 110](../scripts/check_agent_connectivity.py#L110), [`recommendation_facade.py:1216`](../src/app/services/recommendation_facade.py#L1216), [`legacy_adapter.py:215`](../src/app/services/recommendation_core/legacy_adapter.py#L215) and the complete browser-case ledger.

**Change:** classify every remaining browser failure as a reproduced defect, broken fixture, unavailable prerequisite or obsolete contract. Bind fixtures to authenticated tenant identities; retire assertions only with a reviewed replacement contract. Give offline, owned-service, live-search, OCR/model and external-effect profiles explicit prerequisites and required-case manifests. Connectivity probes must assert the expected status and response schema; HTTP 404 cannot count as route success. Remove repeated script bodies before relying on this probe, which also contains mutation requests.

**Tests:** preserve [`test_fixed_image_security_pack.py:112`](../tests/test_fixed_image_security_pack.py#L112) under an enabled controlled OCR profile; the last skip leaves it open. Preserve malicious-artifact effect snapshots at [`artifact-security-boundary.spec.ts:42`](../frontend/e2e/artifact-security-boundary.spec.ts#L42). Add mixed search/OCR/supplier/memory attacks and benign controls, network loss, duplicate submission, concurrent tabs, keyboard navigation and accessibility checks. Load tests must first prove successful authenticated readiness, then measure throughput with stated budgets.

**Done when:** all required case identities execute and pass on the frozen candidate, skipped optional cases remain separately labelled, and each retired expectation has an approved successor. Report attack success and false positives on defined samples. The 80 recorded browser failures are neither 80 proven independent product defects nor disposable test noise.

## W13 Reduce coupling through tested extraction

**Code to work:** the six large entry points in the source-size table, [`turn_transition.py:183`](../src/app/services/turn_transition.py#L183), [`research_outcome.py:231`](../src/app/services/research_outcome.py#L231), and shared database/security/metrics interfaces.

**Change:** extract coherent steps with explicit typed input/output and session ownership: intake, case binding, interpretation, evidence execution, atomic commit and presentation. Consolidate terminal read-model generation. Separate email detection from persistence/alerts and lifecycle registration from app construction. Review swallowed exceptions first at authority, storage and effect boundaries; return explicit failure states and observable error categories. Keep intentional best-effort telemetry distinct from required business persistence.

**Tests:** characterize current accepted/rejected payloads, source provenance, side effects, transaction rollback and presentation before each extraction. Retain browser trace/case/revision assertions. Run existing function/file growth checks without raising ceilings; require the changed function's complexity and ownership to improve. Use Ruff findings as a review backlog, not an automatic bulk rewrite.

**Done when:** each extracted slice has one clear owner, independently testable behavior and unchanged required contracts; no second mutable case state or hidden ambient session is introduced. The initial target is the slice needed for W01/W03/W04, not an arbitrary percentage reduction in total lines.

## W14 Expand data quality and establish benchmark credibility

**Code to work:** [`synthetic_canonical_replay.py:205`](../src/app/services/synthetic_canonical_replay.py#L205), [`merchant_decision_dataset.py:26`](../src/app/services/merchant_decision_dataset.py#L26), [`merchant_evidence_retrieval.py:97`](../src/app/services/merchant_evidence_retrieval.py#L97), [`forecast_intelligence.py:119`](../src/app/services/forecast_intelligence.py#L119), calibration at [line 26](../src/app/services/forecast_intelligence.py#L26), and [`heldout_inventory_benchmark.py:17`](../src/app/services/heldout_inventory_benchmark.py#L17).

**Change:** add independent SKU/tenant/category/time scenarios, late and corrected observations, identity migration, receipts/transfers/returns and demand censoring. Preserve the distinction between observation time and information available at the decision cutoff. Independently judge evidence relevance and source-to-SKU linkage. Compare forecasting/retrieval/model alternatives with the same data, budgets, held-out periods and operating-cost assumptions; retain the baseline when the new method does not win.

**Tests:** [`test_market_decision_dataset.py:7`](../tests/services/test_market_decision_dataset.py#L7), [`test_merchant_decision_dataset.py:15`](../tests/services/test_merchant_decision_dataset.py#L15), [`test_heldout_inventory_benchmark.py:13`](../tests/services/test_heldout_inventory_benchmark.py#L13), and [`test_forecast_interval_calibration.py:7`](../tests/services/test_forecast_interval_calibration.py#L7). Check conservation, future-data leakage, scope isolation, uncertainty coverage, stockout/service metrics and independently labelled relevance. Zero-demand and missing-data windows must remain explicitly undefined where appropriate.

**Done when:** W06 has admitted useful evidence for the supported pilot scope. Broader comparative claims additionally require independent scenarios, uncertainty estimates and reproducible gains over baseline. Hundreds of correlated synthetic variants do not establish a graph/model/V3 winner or real-market generalization.

## W15 Freeze and verify the complete release candidate

**Code to work:** [`clean-checkout-smoke.yml`](../.github/workflows/clean-checkout-smoke.yml), [`ci.yml`](../.github/workflows/ci.yml), [`playwright-ui-smoke.yml`](../.github/workflows/playwright-ui-smoke.yml), [`soak_portfolio_browser.py:29`](../scripts/soak_portfolio_browser.py#L29), [`soak_resource_sample.py:7`](../scripts/soak_resource_sample.py#L7), migration/restore tooling and deployment manifests.

**Change:** freeze source commit, dependency hashes, environment profile, database schema and fixtures. Run without changing imported source midway. Require clean install, migrations from empty and existing databases, backup/restore, application rollback, required security gates, all declared behavior/browser profiles and current Linux/Windows CI. Run endurance only after functional blockers are resolved; preserve full failure receipts and automatic cleanup.

**Tests:** [`test_release_integrity.py:11`](../tests/services/test_release_integrity.py#L11), [`test_browser_soak_runner.py:4`](../tests/services/test_browser_soak_runner.py#L4), [`test_roadmap_browser_spec_selection.py:7`](../tests/test_roadmap_browser_spec_selection.py#L7), complete required Python/UI/browser profiles and independently observed restore/recovery checks. Keep the original 2 GiB/process, 5,000-handle and 1 GiB host-headroom bounds. Record process-tree and host behavior, latency, errors and complete successful-cycle counts over the required duration.

**Done when:** the exact complete candidate passes all required gates and the full requested endurance duration, with no untracked dependency, hidden skip, source change or raised resource ceiling. The 55.2-minute run used diagnostic GC every 25 teardowns; production behavior must be measured with that intervention explicitly accounted for. Historical eight-hour work failed early and cannot be relabelled a pass. GPU/model endurance requires its own deliberately configured profile; CPU/offline receipts do not certify it.

## Original roadmap mapping

| Original item | Current progress | Remaining closure | Work packages |
| --- | --- | --- | --- |
| 0 Reproducibility | Local before/after recovery snapshots and selected exact-commit exports verified. | Coherent complete checkout, declared install, independent restore and current CI. | W00, W02, W15 |
| 1 Memory | Scoped retention, correction/reload and owned Redis recovery checks pass. | Distributed API erasure/recovery and longer ambiguous tasks. | W04, W07 |
| 2 Market data | Reconciled fictional dataset and cutoff/tenant guards exist. | Independent scenarios, late data and migration identities. | W14 |
| 3 Merchant intelligence | Scoped cited fixture retrieval and read-only decisions exist. | Useful current evidence and completed buyer-chat handoff. | W06, W14 |
| 4 Forecasting | Synthetic held-out and operational baseline evaluation exists. | Independent generalization, calibrated uncertainty and reproducible gains. | W14 |
| 5 Positive buyer journey | Six fictional conversational qualification cases pass. | Same-case uploads, transition matrix and live official-source qualification. | W03, W04, W12 |
| 6 Inventory | Holds, changes, stock movements and controlled expiry are exercised. | Worker/scheduler restart, contention and existing-data migration. | W01, W08 |
| 7 Supplier conversations | Exact fake enquiry, independent approval and reviewed reply pass. | Chat draft handoff, authenticated mailbox and purchasing continuation. | W05, W09, W10 |
| 8 Amendments and approval | Selected typed commercial amendments and person-bound effects work. | Full landed cost, unresolved quantities and legacy sink coverage. | W04, W08, W09 |
| 9 Recovery | Selected unknown-send reconciliation/reapproval is exercised. | Trusted observations and independent completion across legacy sinks. | W10 |
| 10 Bundles and upgrades | One reviewed fictional accessory acceptance path passes. | Broader compatibility, discounts and concurrent changes. | W11 |
| 11 Security and browser | Selected privacy, tenant and malicious-artifact boundaries pass. | Python migration, OCR projection, broader attacks/benign controls and complete browser contracts. | W02, W07, W12 |
| 12 Endurance and release | Several retention/resource mechanisms repaired; bounded run completed. | Functional green, frozen candidate, full endurance, restore/rollback and current CI. | W00, W01, W15 |
| 13 Benchmark credibility | Held-out evaluation machinery exists. | Independent labels, equal budgets and reproducible quality improvements. | W14 |

Every broader item has an open closure gate. This does not mean no useful work is complete: the delta table names the verified capabilities. It means the roadmap's full milestone scope must not inherit the green status of one narrow fixture.

## TDD and the meaning of green

For each defect, first reproduce the behavior with valid identity, source and provider prerequisites. Preserve the failing assertion and receipt, make the smallest coherent repair, then rerun that test and the affected contract/journey from the proposed commit. A setup error, disabled OCR or malformed fixture is not a business-behavior red. A later skip is not a repair.

| Gate | Required evidence | Insufficient substitute |
| --- | --- | --- |
| Parse and type | Python/configuration parse; both UI type checks; both builds; generated profiles match. | Storefront Vite build alone. |
| Scoped behavior | Named cases execute and exit zero against recorded source and fixtures. | A passing collection or a skip. |
| User task | Browser traverses real API/database and asserts exact output, case/revision, evidence and effects. | Retaining facts while draft/evidence fields remain null. |
| Provider | Enabled provider fulfills its specific contract, with freshness/authentication and failure controls. | A mock transport or successful discovery without accepted evidence. |
| Resource and endurance | Full required duration, unchanged budgets, successful workload and no orphan resources. | Short repeated passes, a resource-killed process, or a functionally failed bounded run. |
| Release | One frozen complete source/dependency candidate passes required profiles, restore/rollback and current CI. | Historical green, local targeted passes or a dirty checkout with missing tracked dependencies. |

Two concrete oracle repairs illustrate the standard. [`test_context_rot.py:30`](../tests/test_context_rot.py#L30) now advances time and tests actual expiry. The live memory test still only records the draft/evidence completion fields; W05/W06 must add task-output assertions. Connectivity checks currently accepting 404 need expected-status/schema assertions before their green label is meaningful.

## Next complete acceptance journey

1. Register/login in the configured tenant; deny foreign-tenant and impersonated access.
2. Create a request for 30 units at AUD 1,500 per unit for Sydney, with a clearly identified workload and explicit research consent.
3. Attach PDF/plain-text evidence, review/correct it in the same case, and show accepted versus unresolved claims without invented suitability.
4. Refine workload size, then amend quantity to 40; retain money scope, destination and workload, and invalidate incompatible approvals.
5. Qualify an evidenced configuration under an enabled controlled source, explicitly accept current stock, and compute the shortage from current valid coverage.
6. Ask for a shortfall email in ordinary chat. Show the exact reviewable draft with the calculated shortage; assert no dispatch or purchase effect.
7. Ask for market intelligence while retaining this request. Show admitted cited observations or a specific blocked state, and leave quantity/budget/case unchanged.
8. Reload and recall the current request. In another tab, submit an amendment; reject stale actions and show the current revision consistently.
9. In a separately labelled fake-effect profile, obtain independent approval, dispatch once, ingest/review a reply, simulate uncertainty and recover without duplicate effects.
10. Repeat from the complete exported candidate with declared dependencies and migrated existing data; then run broad and endurance gates.

The first delivery is this complete controlled journey plus W00–W04 runtime/reproducibility gates. A pilot adds current live sources, the required mailbox/operational adapters, complete approval/recovery coverage and declared privacy behavior. Production release additionally requires W15. Comparative forecasting/model claims require the independent W14 benchmark gate.

Implementation effort should be estimated per coherent package after W00 exposes its full dependency group. Exact remaining line counts or a calendar completion date would be speculative: database causality, legacy sink coverage and provider contracts are still discovery work. Existing source sizes and explicit acceptance gates above provide a reviewable basis for that estimation.
