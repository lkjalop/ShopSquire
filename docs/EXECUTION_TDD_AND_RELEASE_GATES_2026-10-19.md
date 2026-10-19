# ShopSquire execution, TDD and release gates — 19 October 2026

Started 19 October and finalized 20 October 2026, Australia/Sydney. This is the execution follow-up to [the original assessment](CODEBASE_BROWSER_MEMORY_AND_ROADMAP_ASSESSMENT_2026-10-19.md). The user's request authorized assessment, execution, repairs and safe local commits. Recommendations inside supplied documents were treated as evidence to assess, not independent authority to publish, send mail, execute purchases or certify the roadmap.

**Verdict: useful verified repairs, substantial remaining work, no platform-wide green or release approval.** Memory retention and selected simulated procurement journeys work. Broader browser tests still expose workflow failures. The installed Python environment differs from the locked deployment profile, and both have dependency advisories. Historical passing runs do not certify this working tree.

## Scope and limits of “all files and lines”

The final inventory and execution accounting appear below. Every eligible tracked or nonignored untracked file was read mechanically, fingerprinted and counted; eligible Python source, scripts, tests, migrations and SDK files were parsed and structurally scanned. Primary and admin UI source received TypeScript checks, tests and builds. Configuration parsing, architecture ratchets, dependency checks and real browser journeys supplement that inventory.

This is **not a claim of a manual semantic review of nearly one million lines**, proof of every branch, or execution of every possible provider/deployment combination. Ignored credentials, virtual environments, dependencies and runtime databases are outside the source inventory. Binary assets were fingerprinted, not interpreted as source. The deprecated storefront is not a supported build target. The per-file ledger distinguishes mechanical coverage from detailed review; passing a parser does not establish correctness.

Evidence is retained under [`.artifacts/execution-2026-10-19`](../.artifacts/execution-2026-10-19/). Full browser traces, runtime-private configuration and database fixtures remain ignored. The committed report and summary contain no runtime credentials. Repeated runs overlap; their counts must not be added together as unique coverage.

## Repairs and evidence

| Area | Change and observed result | Scope |
| --- | --- | --- |
| Conversation privacy | Redis registration precedes value storage inside one Lua operation; subject erasure snapshots and deletes atomically. Replacement-worker, index-failure and concurrent write/erase checks pass against an owned Redis. Failed erasure raises; local stale copies are suppressed. | Redis single-server semantics; not a Redis Cluster or load-balanced API certificate. |
| Retention | Expired local values and index entries are reclaimed across idle subjects. Local payload retention is bounded by key count and bytes. | Defaults: 1,024 keys and 64 MiB serialized payload; Python object overhead is additional. Eviction can shorten local continuity. |
| Worker hangs | The legacy executor-context bridge now uses the common bounded bridge. Caller tenant/request context crosses the thread boundary; coroutine errors are propagated once. | A caller deadline does not forcibly terminate a running thread. Async callers should await or offload. |
| Tracing and logging | A strong OpenTelemetry application registry prevented discarded apps from being collected. Compatibility handling uses weak ownership; tracing disable flags are respected. Repeated logging initialization reuses handlers and filters. | Twenty fresh application lifetimes left zero retained apps in the controlled diagnostic; this does not prove eight-hour endurance. |
| Metrics | Request/error counters use registered route templates; latency buckets share API resource families. This reduces Windows semaphore pressure while retaining route-level error counters. | Current working-tree integration; latency dashboards must use the documented family labels. |
| Native tenant onboarding | Login and registration carry the same storefront tenant headers as subsequent calls. Server membership uses recorded native enrollment; explicit deployment revocation remains authoritative. | Own tenant allowed, foreign/default tenant denied, explicit revocation denied in the working-tree tests and configured-tenant browser check. This group has broader uncommitted dependencies. |
| Outbound monitoring | List, analysis and provider callers bind tenant scope. Authenticated foreign-tenant reads/simulations are denied; database read failure returns an error rather than an empty success. | Tested local database and authenticated HTTP boundaries; no real email sent. |
| CV privacy and responsiveness | Optional storage receives only successfully sanitized bytes and MIME. Sanitizer failure does not upload original bytes. Tier-two analysis and storage I/O are off the async event loop. | Private EXIF canary and forced sanitizer failure; controlled slow work must not delay an unrelated health request beyond 350 ms. |
| Owned database transaction | Order creation uses the catalog repository bound to its supplied database session. A regression injects a conflicting ambient request engine. | Focused attribution/order tests; no real payment. |
| Selected-case research | Research for a persisted, unchanged selected requirement scope preserves the case and independently compiles accepted claims. Completed evidence reaches the atomic read model and narration. | Six normal fictional qualification scenarios pass, including invalidation and simulated shortfall/enquiry branches. No real workload qualification is inferred. |
| Read-only recall | Quantity/budget summaries without a selected SKU retain the owned case. A bounded market-intelligence question explicitly retaining the current request follows that case. | Multi-turn corrections, reload and the live read-only cross-intent test pass. This does not create research evidence or purchase authority. |
| Canonical presentation | The committed read model receives current execution failure evidence and retained facts. Top-level chat presentation adopts the committed message, panel and products. | Message/panel agreement is repaired for tested turns. The broader transition matrix still finds a wrong subject transition on another turn. |
| Supplier review | The supplier-enquiry screen shows the exact recipient, subject and body used by approval/dispatch. | Independently approved fake enquiry and reviewed partial reply pass; live mailbox negotiation remains unproved. |
| Anomaly API | Later duplicate functions shadowed the feature-mapping scorers and broke fraud, inventory and agent-behavior callers. Removing those incompatible duplicates restores the existing mapping API. | Four new red regressions; seven focused tests pass. This repairs invocation/return contracts, not statistical detection quality. |
| Blocked corroboration | Accepted upload claims now retain per-claim unresolved/preference results when research is blocked. | Blocked evidence stays provisional; no authority is manufactured. |
| Static and tooling | Undefined-name findings were repaired; two malformed Grafana JSON files parse; a missing generated Windows vision profile was produced. Vitest/coverage and source-map-js lockfile findings were patched. | Separate-checkout frontend installs, tests, builds and npm audits pass. Python dependency advisories remain open. |

The new failures were retained before repairs: see `red-boundaries`, `red-scripted-erasure`, `red-blocked-review`, `red-cv-storage-responsiveness` and the earlier qualification/browser artifacts. The initial native-auth test using an invalid example email was a fixture mistake, not proof of the tenant bug; the real configured-storefront 403 and later authenticated regressions establish that boundary. Encoding damage introduced during editing was detected against the original archive and corrected in CV and turn-router source before final targeted verification.

## Retention is different from completing the requested task

The live browser sequence uses a signed buyer and configured tenant, public read-only discovery through the existing local search service, 30 laptops at AUD 1,500 per unit for FreeCAD, Sydney delivery, correction to 40, a supplier shortfall email request, a market question, a summary, and reload recall. Case identity, corrected quantity, currency/budget scope and destination are checked, along with commercial effect snapshots.

That sequence now passes its retention assertions. Its completion attachment separately records the actual email-draft and market-evidence fields and assistant replies. The generic chat path does **not** produce a completed supplier email draft or cited market analysis in this unresolved-product conversation. Generic refusal or retained facts are not task completion. A concrete shortfall also needs a selected configuration and current availability; “40 requested” alone does not identify how many units a supplier must quote.

The positive simulated supplier workflow is separate evidence: a qualified fictional configuration, accepted quantity, held stock and measured shortfall lead to a reviewable exact draft, independent approval, fake dispatch, a structured reply and review. It does not prove that every natural-language draft request reaches that workflow, that a real mailbox works, or that market intelligence is useful and fresh.

## Remaining defects and release blockers

| Priority | Finding | Evidence / next acceptance gate |
| --- | --- | --- |
| P1 | PDF/plain-text requirement review can bind a proposal to the earlier case while routing has installed another active case. The UI refuses the review as belonging to an earlier case. | `browser-matrix-repaired/uploaded-requirements-journey`: retain the owned case for evidence intake, distinguish explicit subject replacement, then accept/corroborate in the same case. Do not remove the stale-case check. |
| P1 | The conversational transition matrix classifies a small/large PLC-model refinement as `REPLACE_WORKLOAD`. | `browser-matrix-terminal/turn-transition-revision-matrix`: the repaired message/panel assertions pass earlier turns, but the third turn still fails its transition assertion. Preserve workload identity and prior material facts without carrying authority into a genuine replacement. |
| P1 | Generic chat does not complete the requested email draft or cited market-intelligence task. | The live cross-intent attachment explicitly separates retention from output completion. Add an explicit governed draft/intelligence handoff, missing-input states and output/effect assertions. |
| P1 | Python deployment and installed environments have known dependency advisories, and the tested environment is not the locked environment. | Audit manifests identify packages, exact versions, advisory IDs and available fixes. Plan a compatible FastAPI/Starlette and dependency migration; regenerate Linux/Windows locks, install cleanly, and repeat the security/API/browser gates. Advisory counts are findings, not proof of exploitability. |
| P1 | The full-process run develops SQLite locking failures and very slow security requests. | A request took 151.56 seconds; a read-only stack capture shows synchronous observer persistence/incident creation on the async portal and several scheduler threads waiting in SQL. Later storefront/narration setup writes fail with `database is locked`. Fresh-process passes do not close this transaction/lifecycle problem. Trace database ownership and scheduler shutdown; do not simply enable the threaded flag on a shared SQLite connection. |
| P1 | One image-security consistency case fails in a cohort because the recommendation response omits the expected security projection. | `batch-070` records the missing `policy_route`; the final focused run skips this case when OCR is unavailable. Keep the original assertion and verify it under an enabled, controlled OCR profile before closing the finding. |
| P1 | Overall browser and broad-run results remain red; no final current-tree release certificate exists. | Fix or explicitly retire obsolete contracts with evidence. Required provider profiles cannot be silently replaced by offline success. Verify the complete frozen candidate and remote CI. |
| P2 | Some browser assertions demand historical wording or provisional shelves that current authority rules withhold. | Unresolved-workload and fast-lane tests need reviewed contracts that assert evidence/authority and truthful blockers. Do not make positive-fit checks pass by accepting arbitrary degraded text. |
| P2 | Legacy load tests return 503 instead of exercising successful requests in the offline test profile. | Separate readiness/authentication prerequisites from throughput. Their failures provide no latency certificate. |
| P2 | Test doubles without indexing methods were being treated as authoritative shared Redis. | Local-only adapters are now declared explicitly; the shared postflight adapter implements index registration. No production fallback was weakened to accommodate incomplete fakes. |
| P2 | A test named `test_recent_retrieval_expires` previously asserted only immediate availability. | It now advances a controlled clock and asserts actual expiry. Other “green” tests need the same review of their oracle and prerequisites. |
| P2 | Architecture remains costly to reason about. | The final AST ledger identifies 99 production functions over 200 lines and thousands of broad exception handlers. These are review signals, not automatically thousands of defects. Prioritize chat orchestration, turn routing, main lifecycle, security evaluation and duplicated terminal projection. |
| P2 | Endurance remains unproved. | Resource fixes and a bounded Python process are different from an eight-hour browser/API/model run. Preserve original 2 GiB/process, 5,000-handle and 1 GiB host-headroom limits. Current diagnostics used GC every 25 teardowns; production does not inherit that test intervention. |

## TDD and what green means

TDD requires a failing behavior test that reaches the intended boundary, the smallest repair, and a passing rerun with the original assertion intact. A collection error, malformed email fixture, omitted tenant header, disabled provider or absent browser executable is not a valid red test for a business requirement. Regression tests were added for privacy, tenant boundaries, responsiveness, case continuity, exact supplier preview and resource ownership; this is not a claim that all existing code was developed with TDD.

Use the following levels when reporting green:

1. **Syntax/type/configuration green:** eligible files parse, UI types/builds work, and generated dependency files match their declared source. This says nothing about user task completion.
2. **Scoped behavior green:** a named test set exits zero under recorded fixtures. Skips remain uncovered; mocks establish only the boundary they simulate.
3. **Connected journey green:** real browser clicks traverse real APIs and a migrated database, checking durable case/revision, evidence, inventory, exact effects and truthful UI. Simulation remains labelled.
4. **Provider green:** separately verified live search, official origin compilation, models, mailbox, payment or ERP behavior with its own prerequisites. A successful discovery attempt is not accepted official evidence.
5. **Release green:** the exact frozen source, declared installed dependencies, migrations/restore, required security and browser gates, resource/endurance checks and current CI all pass. No untracked import or missing migration is required to make the checkout work.

`pytest` exit zero with skipped cases is scoped success. A resource-killed run is failed even if every completed assertion passed. Splitting tests into fresh processes can establish additional behavior coverage but does not turn a failed single-process resource gate green. Later focused reruns do not change the exit code or source version of an earlier broad run. Counts below preserve these distinctions.

The source growth ratchets now pass without raising their ceilings. They grandfather existing large files; that is not architectural cleanliness. The AST import graph contains 1,210 Python application modules, 3,300 observed edges and ten possible dependency cycles, the largest containing sixteen modules. Deferred imports are included, so these are coupling signals rather than proof of import-time errors. Break the database/security/metrics coupling through explicit transaction and context interfaces, then extract coherent turn-handling slices from the 4,473-line chat function. Avoid moving the same shared mutable state into more files and calling that a refactor.

One concrete false-green oracle remains in `scripts/check_agent_connectivity.py`: it treats any status below 500, including 404, as `OK`. Its result is not proof that the named route exists or that a business journey works. Duplicate endpoint-checking definitions and repeated script bodies also warrant cleanup. The general Ruff run still reports substantial hygiene debt; the zero-result undefined-name check is a narrower, separately named gate.

## Roadmap 0–13 reassessment

The latest 0–13 evidence document is [ROADMAP_ALL_EXECUTION_2026-10-05.md](ROADMAP_ALL_EXECUTION_2026-10-05.md), including its 7 October failure correction. Older roadmap documents describe different product scopes and historical states; their completion language must not override current receipts. No defensible completion percentage follows from test counts.

| Item | Current assessment | Gate to close the broader item |
| --- | --- | --- |
| 0 Reproducibility | Local backup and selected exact-commit exports verified. | Clean declared Python installation, independent-machine restore, current Linux/Windows CI and deployment rollback. |
| 1 Memory | Scoped retention, corrections/reload, owned Redis worker/partition/restart and concurrent erase/write checks pass in bounded profiles. | Load-balanced API behavior, durable failed-erasure recovery and longer ambiguous interdependent tasks. |
| 2 Market data | Reconciled fictional operational dataset exists. | More independent SKU/tenant/cutoff/lateness scenarios; ingestion identity across migrations. |
| 3 Merchant intelligence | Cited scoped read-only fixture decisions and fallback paths exist. | Useful current sources, independently checked relevance, exact-SKU mapping and a completed buyer-chat intelligence handoff. |
| 4 Forecasting | Held-out synthetic comparisons and operational metrics exist. | Independent scenarios, calibrated uncertainty and demonstrated gains over baseline. Correlated variants do not establish a winner. |
| 5 Positive buyer journey | Six fictional qualification browser cases pass after continuity repairs. | Uploaded-evidence case continuity, additional contracts/categories and successful live official-source compilation. Real Blender suitability remains unproved. |
| 6 Inventory | Transaction, hold, amendment, receipt/transfer and controlled expiry machinery is implemented and exercised. | More concurrent worker/scheduler/restart and existing-record migration journeys. |
| 7 Supplier conversations | Same-case fake shortfall enquiry, exact preview, independent approval and reviewed reply pass. | Generic chat draft handoff, authenticated live mailbox and operator purchasing continuation. |
| 8 Amendments/approval | Typed budget/deadline and selected person-bound exact-effect workflows exist. | Full-order landed costs, unresolved shortfalls and legacy PO/refund/order/connector approval coverage. |
| 9 Recovery | Unknown fake-send outcomes block unsafe retry; selected reconciliation/reapproval paths pass. | Complete legacy effect recovery with trusted observations and independent completion checks. |
| 10 Bundles/upgrades | Reviewed fictional offers and explicit acceptance are exercised. | Broad configuration compatibility, discounts and concurrent quantity/price changes. |
| 11 Security/browser | Selected tenant, privacy, malicious-artifact and effect-boundary tests pass. | Current dependency remediation, systematic mixed-input/benign controls, accessibility and network/concurrent-tab matrix. |
| 12 Endurance/release | Application-retention and metrics-handle mechanisms were reproduced and repaired; historical failures remain preserved. | Frozen complete candidate, unchanged resource limits, full endurance, restore/rollback and current CI. |
| 13 Benchmark credibility | Several held-out evaluations exist. | Independent labels/categories, equal budgets and reproducible quality gains. No V3/graph/model winner is established. |

First close the remaining case/evidence and dependency blockers, then freeze a coherent source/dependency candidate, verify it, and run endurance. Adding more agents, graph layers or benchmark variants before those gates closes neither correctness nor user task completion.

## Git, source preservation and commits

The starting tree had 590 changed/untracked paths and no staged changes. HEAD was `c7daafaa5b7d4248ca97abffd7a9b3e8a031e457`; local tracking was 29 ahead and zero behind without a fresh fetch. This was already a large mixed worktree. Logs, scratch data, credentials, generated databases and unrelated user work were not blindly staged or deleted.

Before repairs, `C:\AI\ShopSquire-checkpoints\20261019-before-execution.zip` preserved 5,267 source files with SHA-256 `3628ee97264c54adec5d5b5a962d67d075df79cb61d9ff8f73be920d1ac2a862`. Its independent SQLite backup passed integrity checking. This is a local recovery copy, not an off-machine backup.

Five verified local commits are recorded:

- `3d815bb7475f55822369bfac10e8a26e902dbb74`: scoped memory erasure/retention, bounded coroutine/context handling, tracing ownership and logging lifecycle. The exported candidate passed 27 targeted tests.
- `7999834f1cc7ecdd140ac645c6073517828f2a37`: patched frontend test tooling and lockfiles. Clean exported installs, 381 storefront tests, 47 admin tests, both builds and both npm audits passed.
- `ed878c948b396bad9bd9c478738e15654d38fd90`: sanitized optional image storage and responsive CV/storage work, plus explicit memory adapters and actual expiry assertions. Its exact exported candidate passed 61 tests.
- `5dc38e364b58558989cddd15d4e0fc97c3e49f2d`: explicit local-only no-op Redis fallback and isolated episodic-memory tests. Its exact exported candidate passed 81 tests.
- `929ba5e6b3fd84a6af355f02a424ca6359f11c2e` removes the incompatible shadowing scorers and adds four regression cases; its exact exported candidate passed seven tests. Its hash is recorded in the final execution summary and Git history.

The current working UI has more tests than those committed exports: 407 storefront and 50 admin tests pass, with types/builds, against the patched toolchain. These are separate receipts.

A wider tenant/security candidate was exported and tested before staging. It failed two backend boundaries and the two frontend tenant-header tests because other routing/header dependencies are still in the mixed tree; its frontend type check also failed. That candidate was **not committed**. Passing tests only in the original dirty tree would have concealed these missing dependencies. The remaining integration changes must be assembled into coherent, reviewed commits and retested from their resulting checkout. A local commit is not a release or remote backup.

## Final execution accounting

<!-- EXECUTION_ACCOUNTING_START -->
Source inventory: **5,635 eligible files and 971,931 text lines**, excluding the generated audit ledgers themselves. All 3,062 Python files compile to an AST; 1,087 eligible JSON files parse. Sixty non-template YAML files and 44 PowerShell scripts parse; Helm lint and the base Compose configuration pass. Source/function growth, generated Linux/Windows requirements, `pip check` and F821/F823 gates pass. The general Ruff hygiene run remains red.

| Execution | Native result | Meaning |
| --- | --- | --- |
| General Python, 80 fresh-process cohorts | 7,843 passed; 29 failed; 119 skipped / 7,991 selected | Genuine original failures retained; no resource violations in the cohorts. |
| Original cohort failures, after repairs | 28 passed; one OCR-dependent case skipped | The skipped image-security case remains unverified. |
| Full Python process, 55.2 minutes | 7,836 passed; 36 failed; eight setup errors; 124 skipped / 8,004 selected | Exit 1. Contains earlier imported source and order-dependent database failures. |
| Additional full-process failing/erroring identities | Seven passed, then ten passed in separate fresh processes | Isolation evidence, not closure of the full-process locking problem. |
| Python browser/pw/playwright/e2e/load directories under their default gates | Five passed; two failed; 127 skipped / 134 selected | The two load tests return 503. Skipped browser/provider cases were not counted as executed. |
| Explicit CPU slow/image/security/market profile | 52 passed; nine model-dependent skips / 61 selected | No GPU/model-quality certificate. |
| Separately owned Redis and PostgreSQL | Six and eleven passed, respectively | Owned services removed after use. |
| Current storefront and admin | 407 and 50 tests passed; types and builds passed | Patched frontend tooling; npm audit zero findings in both profiles. |
| Browser identity ledger | 49 latest passes; 80 failures; 32 skips / 161 cases across 76 spec files | Broad battery remains red; authentication fixtures, provider prerequisites, stale assertions and real workflow defects need separate treatment. |
| Latest critical browser cases | 25 passed, plus the separate live retention replay | Qualification, recall, onboarding, inventory, expiry, supplier review/recovery and attachment boundaries; simulated effects labelled. |

The browser evidence contains 257 overlapping observations (118 passes, 106 failures and 33 skips). These are **not 257 unique cases**. The broad remaining-spec battery alone selected 119 cases across 54 files: fourteen passed, 73 failed and 32 skipped, in 48.6 minutes. Its requested global-timeout wrapper did not match the Windows CLI path; actual execution used individual test deadlines, and the metadata was corrected. It completed rather than being labelled a 20-minute bounded run.

The final collection contains **8,143 Python identities**. Retained receipts show **7,927** of those identities executed at least once; 216 remained unexecuted under their recorded gates. Earlier source versions are included in this identity coverage; it is not a final-source correctness percentage. See the committed summary for the uncovered identities and the artifact receipts for skip reasons.

The full process's sampled peak was **1.406 GiB RSS, 4,910 handles and 65 threads**. It crossed neither the original 2 GiB/5,000-handle limits nor host-headroom guard, with diagnostic GC every 25 teardowns. The process still failed functionally. Earlier memory/handle stops remain preserved separately. Neither this run nor repeated short browser tests closes eight-hour endurance.

The Python advisory audit reports **94 package-advisory findings in seven locked API packages**, and 105 in eighteen installed packages. These are advisory-database matches, not 94/105 demonstrated exploitable paths. The locked affected packages are cryptography, Pillow, protobuf, PyJWT, python-multipart, Starlette and urllib3. Versions and advisory IDs are in the summary. The Vitest patch is supported by [the maintainer advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9); installed and clean-checkout npm audits both return zero findings after the lockfile repair.

The [per-file ledger](audits/2026-10-19-file-inventory.csv), [browser-case ledger](audits/2026-10-19-browser-cases.csv) and [execution summary](audits/2026-10-19-execution-summary.json) are committed review artifacts. File hashes describe captured working-tree bytes; Git newline normalization can change byte hashes across platforms. The ledger marks partial semantic path reviews separately from mechanical scanning.

The remaining mixed source is preserved in `C:\AI\ShopSquire-checkpoints\20261019-after-assessment-source.zip`: **5,283 files**, SHA-256 `bec779852b5648ee53fabebd9e134a184f362d01fc57be01df6bb4207c60d7b4`, with every archived source hash verified. This snapshot excludes the audit's own output files and runtime-private artifacts. Source feature flags and CV playbooks still match the pre-work backup; the intentional Grafana repair is the only changed existing configuration in that comparison. No push, live supplier message, purchase, ERP dispatch or payment was performed.
<!-- EXECUTION_ACCOUNTING_END -->
