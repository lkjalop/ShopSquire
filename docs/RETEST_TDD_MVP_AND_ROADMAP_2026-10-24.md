# ShopSquire: fresh tests, TDD meaning, MVP and remaining roadmap

Assessed **24 October 2026**. Published/local HEAD: `9da621d1f4751669ce836c2844939b0e4eb2372b`. Tests used an exact private snapshot of the current authored working tree, including **327 pre-existing dirty paths**. No application implementation or existing test was changed for this assessment. Existing local changes are part of the tested candidate, not newly published capabilities.

**Assessment:** case retention, exact fictional shortfall drafting and the sandbox supplier journey work in the tested scope. Ordinary buyer usefulness, bulk price/candidate consistency, completed approved-source research and relevant cited market answers still prevent calling the proposed procurement MVP complete. New fault-injection tests also identify a semantic-cache erasure gap. More RAG components should not precede those repairs.

Evidence: [execution summary](audits/2026-10-24-reassessment-summary.json), [individual case observations](audits/2026-10-24-reassessment-cases.csv), [all-file inventory](audits/2026-10-24-reassessment-files.csv), [refreshed W00–W15 source map](audits/2026-10-24-reassessment-roadmap-source-map.csv), [research assessment](RESEARCH_MEMORY_MARKET_AND_SUPPLIER_REASSESSMENT_2026-10-24.md).

## Scope: what was and was not reviewed

The snapshot contains **5,858 authored files**, **1,175,532 text lines**, and **3,657 code files / 573,779 physical code lines**. The inventory includes tracked and nonignored untracked files; ignored generated artifacts and installed dependencies are excluded. Every inventoried file has a byte hash and line count where decodable. All Python files parsed without a syntax error; the AST inventory contains 19,878 functions. Both maintained frontend applications passed their TypeScript checks.

This is complete mechanical inventory coverage, **not semantic approval of every line**. Manual inspection concentrated on case-task delivery, shortfall calculation, market admission/narration, supplier effects and review, memory/cache failure boundaries, temporal/graph selectors, browser actor setup and the failing scenarios. Historical/optional modules and every branch of the 573,779 code lines were not individually proven correct. The inventory explicitly labels that distinction.

The original limits remained in place: per-test hang backstop, supervised profile deadlines, 2GiB per-process RSS, 5,000 handles and at least 1GiB host headroom. Completed supervised checks reported no resource-limit violation. This is not an endurance or latency-SLO certification, and it does not close the historical 151.56-second request observation.

## Fresh execution results

| Profile | Passed | Failed | Skipped | What it establishes |
|---|---:|---:|---:|---|
| Memory, temporal and graph tests, 41 files | 226 | 0 | 13 | Existing correction, scope, temporal and retrieval contracts; initial native DB prerequisites skipped. |
| Market and forecasting tests, 45 files | 371 | 0 | 19 | Existing source, projection, evidence and forecast contracts; initial native/live prerequisites skipped. |
| Supplier, authorization and privacy tests, 46 files | 267 | 0 | 7 | Existing supplier, privilege and privacy contracts; initial native Redis prerequisites skipped. |
| Owned PostgreSQL and Redis | 33 | 0 | 0 | Native ownership, temporal projection, scope erasure and worker partition/restart cases. |
| Live official USGS protocol | 1 | 0 | 0 | Actual ScienceBase source fetch yields attributable advisory observations; no mocked transport. |
| Integration seams, eight files | 206 | 0 | 0 | Stage coordination, recommendation/evidence seams, case intake, cancellation/timeouts and selected release-integrity contracts. |
| New assessment-only contract probes | 3 | **4** | 0 | Missing test coverage exposed; no implementation repair was made. |
| Storefront unit tests | 408 | 0 | 0 | Local working-tree frontend scope; type check/build also pass. |
| Admin unit tests | 63 | 0 | 0 | Admin component scope; type check/build also pass. |
| Playwright, ten specs / 20 cases | 15 | **5** | 0 | Browser/API scenarios described below; one attempt each, zero flaky results. |
| Additional live-enabled conversation | 1 | 0 | 0 | Consented research attempt, correction, provisional email, blocked market answer and reload retention; task completion remains qualified below. |

The existing Python profiles contain **1,143 observations over 1,078 distinct case identities**. Every selected existing identity has a pass in at least one appropriate profile after native/live prerequisites were exercised. There are still 39 skipped observations in the earlier overlapping profiles; they were not relabelled as passes. The new seven acceptance probes are separate and have four failures.

Dependencies were reused from the previously qualified Python 3.11 and exact-lock Node 22 installations. `pip check` passes. This was not a new default Poetry installation or a fresh vulnerability audit. Neither the complete Python suite nor the full broad browser matrix was rerun. The earlier full Python and broad browser results remain historical evidence, with their original failures and scope, in the [23 October report](REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md).

Setup failures were retained separately: the first native run had 32 passes and one failure caused by Windows multiprocessing re-importing an unguarded assessment wrapper. Adding a main guard to the private wrapper produced the unchanged application's 33-pass rerun. The public-link checker also excludes any absolute path containing `.artifacts`; running it inside the private snapshot therefore gave exclusions, not broken public links. Its proper workspace run checked all 50 links successfully. No application policy or assertion was weakened to resolve either setup issue.

## What the browser actually did

| Spec | Result | Interpretation |
|---|---|---|
| Ordinary chat shortfall | 1 pass | Accepted fictional demand of 40, coverage of 15, draft for 25; retained through a market request and reload. Market absence is an expected limitation in this fixture. |
| Platform audit memory | 7 passes | Quantity, budget/currency/destination/deadline and authority-boundary scenarios. These use the shared operator-assisted fixture. |
| Native tenant procurement | 1 pass | Signed buyer retains its selected tenant and 40/15/25 draft, with an explicit zero-operator-header assertion. Qualification/stock remain fictional. |
| Trace navigation | 2 passes | UI navigation over mocked trace data, not proof of genuine backend event production. |
| Attachment boundary | 2 passes | Rejected/malicious-or-incompletely-inspected uploads stay blocked and expose trace/monitoring disposition; no commercial-effect change. This is not universal attack-detection or SIEM-delivery proof. |
| Bulk economics | **2 failures** | Expected fitting/underfunded totals differ from the candidate's price basis; see findings below. |
| Context retention | 1 pass / **1 failure** | Quantity correction survives. The useful product-positive budget journey still returns zero candidates after clarification. |
| Supplier enquiry journey | 1 pass | Case-bound shortfall, distinct-person approval, fake send/replay, reviewed/quarantined replies and amendment invalidation. No real email was sent. |
| Spatiotemporal certificate showcase | **1 failure** | Initial evaluate requests return 401 and the showcase never appears. This run does not assess the domain certificate's invariants. |
| Market adaptation | **1 failure** | Demo signal request returns 401 before the adaptation assertion. This is an actor/setup blocker, not proof that adaptation ran incorrectly. |

Both browser runs used disposable databases, configured owned Redis, offline models and disabled/sandbox commercial effects. Input manifests remained unchanged, independent Redis canaries survived, servers stopped and owned containers/networks were removed. An inner generic runner receipt retains its hardcoded fallback-cache label; the outer supervisor supplies the actual owned Redis connection. Do not infer every browser read was served by Redis solely from configuration.

On the seven specs shared with the 22 October focused review, observed results move from **12 pass / 5 fail to 14 pass / 3 fail**. Three spec files have local actor/fixture changes, including authenticated upload requests and explicit merchant headers. Their positive assertions were preserved, and the upload fixture adds effect snapshots. This is useful improved execution coverage; it is not a controlled measurement of two production code fixes. The additional three specs broaden the scope to 15/5. The separate live workflow is another observation, not an extra unique product requirement completed.

The live-enabled conversation retained a single case through 30 requested units, a correction to 40, an AUD 1,500 per-unit budget, Sydney delivery, draft request, market question and reload. Its recorded task outcomes were:

- Research: `publisher_not_yet_accepted`, `fetch_status=not_attempted`, zero accepted claims; the response also reports an unavailable workload interpreter. Search consent did not complete approved-source research.
- Email: an actual provisional draft describing 40 units, with `shortfall=null`; missing supplier contact and accepted selection/coverage are explicit. It does not invent a 25-unit shortage.
- Market: `blocked`, `no_current_scoped_evidence`, no citations.
- Effects: no new commercial effects; draft/advisory turns keep the current revision.

The [retained browser screenshot](audits/2026-10-24-reassessment-memory-reload.png) demonstrates the final displayed recall, not completion of the missing research/market tasks.

## Concrete findings before the roadmap

1. **Semantic-cache erasure can miss an unindexed shared value.** [SemanticCache](../src/app/services/semantic_cache.py#L258) writes the value before registering the shared erasure index, then suppresses registration failure. A new fault-injection probe makes the value write succeed and index registration fail. A replacement instance reports zero indexed entries erased and still reads the synthetic canary. This is a reproduced failure boundary, not a reported production incident. Atomic registration/write or an equally explicit rollback/incomplete-write protocol needs proof. Conversation memory's separate atomic mechanism and passing Redis tests do not close this cache path.
2. **Malformed explicit validity is admitted.** [Market admission](../src/app/services/market_evidence_admission.py#L13) uses a parsed start or the observation time. Two malformed supplied start strings therefore pass. Preserve the valid missing-start fallback while rejecting invalid explicit starts.
3. **Subject relevance is being treated as answer relevance.** [Market context](../src/app/services/market_intelligence_agent.py#L221) marks demand-only evidence available for a supplier lead-time question. The new probe supplies a current, attributed SKU finding, so this is not a freshness failure. Add measurement/question relevance and explicit partial-answer semantics; do not merely require a nonempty citation list.
4. **Commercial candidate/price expectations remain unresolved.** The ten-unit test expects a fit within AUD 30,000; the answer reports AUD 6,990 over budget. The 60-unit test expects AUD 37,740 total, while the answer uses AUD 221,940. Those outputs correspond to different unit-price bases, AUD 629 versus AUD 3,699. Reconcile eligible catalog identity, price, currency/scope and fixture assumptions before deciding whether the implementation or expected price is wrong. Raising the budget or copying the returned value into the test would not establish correctness.
5. **Retention does not ensure a useful shelf.** The budget journey asks for work laptops at 1,200–1,500, resolves `per item`, and then receives no candidates. Characterize whether this is a supported-catalog positive, a qualification restriction or incorrect grounding, and expose a useful truthful response. Do not bypass workload evidence just to populate products.
6. **Two browser gates remain blocked at admission.** Fix their enrolled actor/runtime setup, retaining unauthorized negatives, before assessing certificate/adaptation positives. A 60-second wait for a page whose API returned 401 is an error-presentation/test-diagnostic issue, not evidence of a computational hang.
7. **The preview and approval message are separate compositions.** [Chat draft](../src/app/services/shortfall_enquiry_preview.py#L32) includes context; [supplier effect](../src/app/services/supplier_enquiry_journey.py#L104) uses a shorter message. The operator panel does display the actual journey message. Unify a versioned reviewed draft to improve continuity and communication quality, while retaining exact-effect approval.

The [new contract probes](audits/2026-10-24-reassessment-contract-probes.py) reproduce findings 1–3. In a configured Python environment:

```powershell
$env:APP_ENV='test'
python -m pytest docs/audits/2026-10-24-reassessment-contract-probes.py --noconftest -o addopts="" -q
```

Expected current result: **3 passed, 4 failed**, native exit 1. These are isolated consumer/fault-injection checks, not an HTTP authorization suite. They intentionally remain red in this assessment. Earlier probe receipts are retained privately; the latest seven-case result is the current contract evidence.

## What green means for TDD

Agree on a behaviour before changing its implementation. A useful red test fails on the existing behaviour for the intended reason, with valid prerequisites. A missing credential, unavailable fixture or import failure is a setup blocker, not the intended behavioural red.

Green means the unchanged expectation passes after the smallest justified repair, with both an intended positive and relevant rejection controls. Do not obtain it by deleting cases, counting skips, increasing a timeout to conceal a stall, replacing expected values with observed wrong values, injecting authority into a buyer profile, or accepting only the blocked branch when the requirement calls for success.

Refactoring follows that repair, retaining the same behavioural checks and growth ceilings. For this codebase, report at least four distinct states:

| State | Required evidence |
|---|---|
| Unit/contract green | The named input/output and failure boundary pass; no implication about wiring. |
| Integrated feature green | Native ownership/persistence and the intended API path pass on one fixed source. State mocks/providers explicitly. |
| Buyer-task green | Browser-visible useful result, current evidence, correct case/quantity/price/destination, appropriate authority and correction/reload behaviour. |
| Release green | Required clean installs, broad tests, enabled-provider positives, security/architecture gates, recovery and endurance all pass on a frozen candidate. No unexplained required skips. |

The current project has many green contracts and some green tasks. It is not release green. The newly demonstrated red contracts must not disappear behind aggregate pass counts.

## Maintainability, Git and hosted gates

The working-tree file-growth check passes with **49 size warnings**; **six function-growth violations** remain. They include the 4,528-line chat handler, 1,057-line SQLite bootstrap and two turn-router functions, plus decision logging and compatibility. Existing large functions also remain debt even where they do not exceed their recorded ceilings. The published-source report's one/seven violations concern different bytes.

The broad AST scan flags 2,260 catch/operation candidates, including 2,024 `except Exception/BaseException: pass`-style blocks in maintained application paths. These are review candidates, not 2,024 proven defects or hangs. Prioritize persistence, privacy, source admission and request-lifecycle paths; some optional fallbacks are intentional. The semantic-cache fault is a concrete example where inspecting a catch changes the risk assessment. The simple scan finding no direct named blocking calls in async scopes is not proof of nonblocking I/O: aliases, ORM calls and nested service work need contextual review and fault tests.

The latest hosted runs for published `9da621d1` still include failed integration, security, container, V2 and repository-evidence workflows, plus a cancelled Playwright workflow. Service-sharded tests and Playwright Smoke passed. See the [captured run conclusions](audits/2026-10-24-reassessment-summary.json) and [published repository-evidence run](https://github.com/lkjalop/ShopSquire/actions/runs/39880426267). These remote results are not results for the dirty snapshot. A passing local subset does not overrule them.

All 327 original dirty paths are preserved for coherent integration. Do not bulk stage them to make Git look clean. No application change, commit or push was made by this reassessment.

## Proposed minimum viable product

Deliver one complete, supervised procurement use case: a buyer specifies a product/workload, quantity, explicit budget scope, destination and delivery need; sees useful candidates with honest qualification status; receives an attributable current-stock answer; gets an exact shortfall draft or explicit unknown; reviews a trusted recipient and the actual message; and can amend/reload without losing facts or authorizing an unintended effect.

Include one approved-source research path and one current relevant market-answer positive. When evidence is absent or unrelated, return a useful limitation with the missing input. Keep real ordering/payment and autonomous sending outside this initial scope. The existing sandbox approval/reply journey supports development; real transport is a separate qualification.

MVP acceptance must include: 40/15/25, an amended quantity, expired holds/quotes, per-unit versus total budget, currency/destination correction, unsupported workload, current/expired/unrelated source evidence, tenant/case/revision mismatch, source outage, contact missing, and no duplicate/unauthorized dispatch. A staged demonstration alone is not the full positive.

## Remaining roadmap, ordered by evidence

| Order | Packages | Next work and reason | Exit evidence |
|---:|---|---|---|
| 1 | W00, W02, W12 | Assemble a reproducible candidate from complete local cohorts; align installed/default dependencies and fix actor setup. Resolve hosted failures rather than hiding them behind scoped green jobs. | Clean checkout/imports/migrations, exact profile installation, named required CI checks and correctly enrolled positive/negative actors. |
| 2 | W07, W06 | Repair semantic-cache index/write atomicity, malformed validity admission and market measurement relevance. These new red cases directly affect trust in memory/evidence. | The seven unchanged probes pass; native fault/restart controls show no orphan value or false erasure completion, and relevant/irrelevant citation pairs behave correctly. |
| 3 | W03, W04, W05 | Complete useful ordinary buyer grounding and the price/candidate contract. Preserve same-case evidence and workload refinements. Correct retained facts are necessary but insufficient. | Supported catalog positives plus unknown/withdrawn negatives; three current commercial browser failures resolved for the documented policy and price basis. |
| 4 | W05, W06, W14 | Connect approved research and a relevant current market observation into the actual buyer answer, then a shared reviewed draft artifact. | Genuine read-only source fetch/admission/citation in the same case, accurate current shortfall, explicit partial/unknown states, and visible preview/approval consistency. |
| 5 | W01, W08, W09, W10 | Qualify concurrency, scheduler ownership, inventory expiry/reconciliation, independent approvers, migrations and uncertain transport recovery. Existing focused native passes are a foundation. | Native races and crash/ack boundary matrix, no duplicate effect, complete restore/rollback, bounded latency/resources under the original limits. |
| 6 | W11, W13, W14, W15 | Finish bundle/amendment consumers where included, extract characterized large handlers, evaluate retrieval/forecast challengers and freeze the release candidate. | Unchanged size ceilings pass; held-out usefulness/citation/calibration/cost results; required full Python/browser/security/provider profiles and endurance on one frozen source. |

All W00–W15 packages remain accounted for in the [source map](audits/2026-10-24-reassessment-roadmap-source-map.csv). Newly prioritized seams are [cache writes](../src/app/services/semantic_cache.py#L258), [market admission](../src/app/services/market_evidence_admission.py#L13), [market context](../src/app/services/market_intelligence_agent.py#L221), [case tasks](../src/app/services/case_task_delivery.py#L56), [shortfall preview](../src/app/services/shortfall_enquiry_preview.py#L32) and [supplier approval/effect](../src/app/services/supplier_enquiry_journey.py#L104).

There is no defensible overall completion percentage. This update supplies a fresh bounded baseline, specific new red contracts, a narrower MVP and explicit exit criteria; it does not declare every file reviewed, every integration complete or the release certified.
