# Repository status, evidence and remaining roadmap

Assessed **23 October 2026**. Publication base: `a4cbf28e121fed9f13067a600c8a822d6d191d05`. This update concerns GitHub presentation, evidence accessibility, CI setup and roadmap reassessment. It does not resume the paused full implementation programme or certify a production release.

## Assessment

ShopSquire demonstrates useful bounded commerce workflows and inspectable policy boundaries. It remains an integration-heavy prototype. The strongest current buying evidence is correction memory and a case-bound 40-requested / 15-available / 25-short draft. Complete cited market intelligence, ordinary browsing/qualification presentation and distributed operational correctness remain unfinished.

There is no defensible overall completion percentage. Passing counts overlap, profiles use different sources, some scenarios use mocks or fictional evidence, and local changes are not the same as committed capabilities. Mechanically inventorying files or lines does not establish semantic review of every line.

## What changed for GitHub

- Replaced the broad landing-page claims with a capability/evidence/limit table and reproducible focused commands.
- Revised Claude's walkthrough to distinguish published code, local changes and review hypotheses. It no longer treats private `.artifacts/` folders as public proof or claims universal stage rollback/dependency guarantees.
- Added an [updated ASCII architecture and source tour](architecture/CURRENT_ARCHITECTURE_2026-10-23.md), including optional providers, durable state, scoped cache, approvals and the incomplete market-to-chat chain.
- Added a scoped repository-evidence workflow for documented checks, both frontend applications and explicit architecture ratchets. Its passing jobs are not release certification.
- Repaired backend dependency setup in CI, general tests, integration contracts and V2 gates using a shared pinned Poetry installer. Security scans audit the application lock, retain failure output and propagate findings. Removed an invalid empty `services` declaration discovered by actionlint.
- Replaced the integration workflow's missing root requirements file, privileged Docker service and fixed sleep with owned PostgreSQL/Redis services and their health checks. Live-stack/provider tests retain their explicit prerequisites and are not silently counted as executed.
- Added the function-size checker with its authored baseline so the walkthrough's command exists in a clean checkout. Ceilings were not raised. Added public-link validation and a regression for missing targets, invalid anchors and private artifacts.
- Removed generated root test/debug captures from the Git index while retaining local files; ignore rules prevent accidental re-addition. Historical objects remain in Git history.
- Followed the hosted run with repairs for missing legacy-browser dependencies and the nonexistent container-scanner action tag. A scanner regression distinguishes complete SHA fingerprints from PAN candidates: the same 13 cases move from 10 passes / 3 failures to 13 passes, retaining positive standalone/grouped-card controls. See the hosted observation for scope and retained results.

The entry state had **333 dirty paths**, including Claude's README, ignore-file and walkthrough changes, and **208 unpublished checkpoint commits**. The scoped publication preserves unrelated authored bytes. The retained [publication receipt](audits/2026-10-23-repository-publication.json) records exact scope and local verification; final GitHub state is independently checked after publishing.

## Verified progress and delta

| Area | Accomplished | Limit / remaining gap |
|---|---|---|
| Conversation memory | Quantity corrections, currency changes, budget scope and destination survive reload; buyer-only replay covers seven original scenario bodies. | Distributed API erasure, multi-worker recovery, privacy and stale-revision matrices remain. |
| Requested shortfall workflow | Native signed buyer retains its selected tenant without operator headers; 40/15/25 produces a retained 25-unit draft across reload. | This uses reviewed fictional qualification/stock fixtures. Contact collection, amendments and real delivery/recovery need separate proof. |
| Buyer qualification | Fictional, evidence-bound qualification and accepted stock controls exist. | Uploaded evidence binding, workload refinement/replacement, ordinary candidate usefulness and genuine supported catalog/image positives remain. |
| Market projection | Future/expired/malformed observations cannot outrank current stock; physical ATP excludes future order promises. SQLite and native PostgreSQL controls pass in retained profiles. | Source registry, freshness, licensing, privacy, producer admission and citation into ordinary chat are not completed by those repairs. |
| Runtime | Session/resource ownership repairs and bounded sandbox publication are committed; focused publisher stall reduced from roughly 65 seconds to roughly one second with event-loop progress. | Unconfirmed publication is not durable enqueue intent. DNS, distributed scheduler ownership, the historical 151.56-second observation and endurance remain unresolved. |
| Frontend | Fresh locked Node 22 installations again pass 387 storefront and 63 admin tests, both type checks and builds. | Unit/build success does not resolve the broad browser failures. |
| Security/dependencies | Curated API/test/vision profiles and frontend patching have retained audit evidence; signed-worker/native-store controls are named. | Last retained default-Python audit still has two unresolved advisory packages, `diskcache` and `ragas`. OS, tooling and enabled-provider qualification are incomplete. This update does not claim a fresh all-Python audit. |
| Architecture | File and function growth checks are available and remain visible in CI. | Clean committed source has one file-growth violation, seven function-growth violations and 49 file-size warnings. Earlier working-tree results reported zero/six; these are different inputs. |
| GitHub evidence | Current guide, architecture, public ledgers and CI commands are assembled into a scoped publication. | Publishing does not integrate the hundreds of remaining local paths or repair functional gaps. |

The original assessment recorded **7,836 Python passes / 36 failures / 8 errors**; the latest completed full process records **8,237 passes / 3 failures / 280 item skips**, plus four collection skips. That is an aggregate pass-count difference of 401, not proof of 401 repaired requirements. The original broad browser run was 49 P / 80 F / 32 skips over 76 specs; the later completed matrix is 41 P / 68 F / 32 skips over 63 committed specs. Scope changed, so an exact browser improvement percentage would mislead.

## Evidence and reproduction

| Evidence | Public artifact / interpretation |
|---|---|
| New publication checks | [Receipt](audits/2026-10-23-repository-publication.json), [individual test cases](audits/2026-10-23-repository-publication-cases.csv), [source map](audits/2026-10-23-repository-source-map.csv). Includes 11 focused core checks and 14 script/architecture checks. |
| Full Python process | [All 8,520 unique item outcomes](audits/2026-10-22-browser-review-full-python-cases.csv), source `a517f22e`. Four collection skips are additional. |
| Broad Playwright matrix | [All 141 cases](audits/2026-10-22-browser-review-broad-cases.csv), [all 63 specs](audits/2026-10-22-browser-review-broad-specs.csv), source `0e177ea4`. |
| Focused browser review and buyer-only replay | [All 24 observations](audits/2026-10-22-browser-review-fresh-cases.csv), [execution/actor scope](audits/2026-10-22-browser-review-execution.json). Seventeen original cases plus seven memory replays, not 24 unique scenarios. |
| Visible failure evidence | [Attachment-boundary screenshot](audits/2026-10-22-browser-review-artifact-failure.png), [network summary](audits/2026-10-22-browser-review-network-statuses.json): 401 admission failures cannot prove attachment analysis ran. |
| Complete roadmap context | [22 October reassessment](BROWSER_CLICKTHROUGH_DELTA_AND_NEXT_STEPS_2026-10-22.md), [all W00–W15 packages](audits/2026-10-22-browser-review-roadmap.csv). |
| Coverage and security context | [Source-scoped assessment](ROADMAP_SECURITY_COVERAGE_AND_DELTA_2026-10-22.md): coverage threshold success did not make its functional tests green. |
| First hosted publication observation | [Hosted CI observation](audits/2026-10-23-hosted-ci-observation.json): focused-core and both frontend jobs passed; size gates failed. Legacy Python browser collection lacked `uvicorn`, and the container scanner referenced a nonexistent action tag. Both setup blockers have follow-up repairs; neither original failure is counted as a product assertion result or a passing rerun. Other failures include V2 cart assertions and a PostgreSQL migration `KeyError: 'destination_rev'`. |

New focused browser scope: nine original cases across `ordinary-chat-shortfall`, `platform-audit-memory` and `browser-native-tenant-procurement`. Eight are operator-assisted controls; one native buyer workflow explicitly audits zero operator-key requests. Models/search are offline, qualification evidence is fictional and commercial effects are disabled. The earlier seven-case buyer-only replay remains separate evidence. This narrow rerun does not replace the broad matrix.

Install Python 3.11 and Node 22 as in the [README](../README.md#reproduce-a-focused-check). For a new disposable browser fixture, from the repository root:

```powershell
python -m scripts.prepare_roadmap_demo --directory .artifacts/portfolio-review
python -m scripts.run_roadmap_browser --directory .artifacts/portfolio-review --api-port 8087 --ui-port 5173 --frontend-mode preview browser-native-tenant-procurement.spec.ts
```

Use the installed environment's Python. Install storefront dependencies with `npm ci` and Chromium with `npx playwright install chromium` from `frontend` first. The browser runner prepares/builds its configured frontend and stops its owned servers. Use unused ports and a new fixture directory; do not reuse a personal database. This command is a deterministic fictional workflow; a distributed cache profile additionally needs an owned Redis instance. Inspect receipts and prerequisites rather than assuming a silent fallback is a pass.

The publication checks use a qualified, exact-pinned existing Python environment plus fresh Node 22/npm 10 installations. They are not a fresh installation of every default Poetry dependency, a full Python rerun, or a fresh broad browser certification. Lock/profile checks pass; architecture checks remain red. The next full process was previously stopped at the user's pause after 378 teardowns of 8,553 collected items and remains incomplete.

## Claude review disposition

The attached review was treated as assessment material, not as authorization to execute its shell commands or publish every local change.

| Claim | Finding / action |
|---|---|
| Walkthrough missing from GitHub | Confirmed locally untracked at entry; included in this scoped publication with corrected claims and public links. |
| Default branch is old; About empty | Confirmed through Git remote and authenticated GitHub API. Publication updates the reviewed default entrypoint and About metadata while preserving older branches. |
| Five workflows install a nonexistent requirements file | Partly stale: one integration workflow did so unconditionally. Others use Poetry or generate exports. Standardized reviewed setup rather than repeating the five-file diagnosis. |
| Stage rollback, dependency validation and blocked propagation are proven current capabilities | Those implementations are local changes. The published base records exceptions/cancellation and validates phase order; it does not snapshot mutations or enforce dependency success. |
| Local `deepcopy` before `try` can escape the guard | Code shape confirmed in local work, not present in the published guard. A supported-value reproduction and bounded snapshot design are needed before integration. |
| Local dependency gate can suppress downstream output | Local gate is present; whether suppression is unsafe needs dependency-specific positive and negative controls. Blindly bypassing a failed fit stage would be unsafe. |
| RAGAS baseline has no writer | Reviewed local rewrite differs substantially from the published implementation. Approved-baseline lifecycle and valid gate positives are required; no unreviewed evaluation rewrite is included. |
| Unpriced siblings incorrectly block category approval | Local behavior differs. Unknown aggregate cost can legitimately require refusal; establish policy intent and explanatory UI before treating it as a bug. |
| One optional procurement fetch blanks the panel | Local hook uses grouped failure handling; published hook differs. Reproduce partial-fetch versus primary authorization failure and retain visible partial/error states. |
| Empty forecast dates, rollback failure, dead DMARC emitter and async-DB check issues | Review candidates in modified local files. They were not reproduced or silently declared fixed by this documentation/CI publication. |
| Ordinary university request returns no products | Local review observation, not a new retained ordinary-chat reproduction. Candidate browsing versus workload qualification is a high-priority product-contract hypothesis with explicit acceptance tests below. |
| Longest clean run exactly 60 minutes; two eight-hour failures at specified minutes; no challenger beats any baseline | Removed from the guide as unsupported universal/exact claims in this publication. Required long endurance and real-world forecast benefit remain unproven. |

## Remaining roadmap

Order is by dependency and user-visible value. The [source map](audits/2026-10-23-repository-source-map.csv) records committed lines/hashes and local differences; local-only paths are explicitly marked rather than linked as published code.

| Package | Progress already evidenced | What to do next, and why | Exit evidence |
|---|---|---|---|
| W00 Reproducible integration | Reviewed repair commits, isolated candidates and current publication setup. | Assemble local modules, routes, migrations, headers and tests in complete cohorts. Independent passes do not certify their combined working tree. | One clean checkout/install with complete imports, routes, schema and required gates. |
| W01 Runtime / ownership | Named session/worker/resource repairs; bounded sandbox-publisher regression. | Certify scheduler ownership, concurrent requests, DNS/transport deadlines and recovery. One reduced stall does not establish sustained latency. | Owned fault/concurrency profiles and bounded latency/resource receipts under original limits. |
| W02 Dependencies | Generated lock profiles, qualified installations and frontend patches. | Reconcile developer/default installations; remediate or remove vulnerable optional packages through supported contracts. Qualify OS/tooling too. | Fresh profile-specific installs, `pip check`, peer checks and explicit audit inventories with no hidden exclusions. |
| W03 Case-bound evidence intake | Fictional accepted requirements and controlled uploads. | Bind uploads to current tenant/case/revision; preserve workload on refinements. Earlier cases must not inherit new evidence. | Genuine signed-buyer positive plus wrong-case, stale-revision and contradictory-evidence controls. |
| W04 Buyer usefulness / product grounding | Typed routing, qualification machinery, current catalog fixtures. | Define ordinary candidates separately from stronger workload qualification; repair supported catalog/image positives. The reported empty shelf is not resolved by successful routing. | Ordinary laptop preferences yield useful clearly unqualified candidates; supported workloads qualify only with valid evidence; unknown/withdrawn claims remain blocked. |
| W05 Shortfall and supplier draft | 40/15/25 native buyer path and retained draft. | Repair qualified bulk presentation, exact quantity/budget scope, contact collection and amendments. Arithmetic alone does not ensure a correct visible offer. | Buyer-only chat → current stock → exact shortfall draft → correction/reload, with no unauthorized send. |
| W06 Cited market intelligence | Source/market components and temporal/physical-stock controls. | Complete producer → admitted current finding → bounded reasoning → citation → ordinary-chat answer. A blocked response is not this positive chain. | Cited relevant answer with current licensed sources; stale/conflicting/unlicensed/unavailable inputs fail explicitly. |
| W07 Memory / privacy | Correction/reload and owned cache checks. | Certify distributed erasure, tenant isolation, restart/partition behavior and browser privacy. Reload success alone is narrower. | Native multi-worker/cache tests for delete, recovery, stale revisions and cross-tenant refusal. |
| W08 Inventory / migration | Transactional stock mechanisms, native checks and simulated acceptance. | Complete location/contention, expiry, reconciliation and crash/restore matrices. Future orders cannot stand in for current ATP. | Native concurrent holds/movements plus upgrade, restore and expiry evidence. |
| W09 Approvals / costs | Exact-effect, person-bound sandbox/signature controls in named profiles. | Establish deployed independent-person identities and cost/category decisions, including unknown totals. Preserve strict policy. | Genuine authorized positive and same-person, stale-effect, unknown-cost and cross-tenant refusals. |
| W10 Effect recovery | Outbox/recovery components and explicit publication uncertainty. | Add durable sandbox enqueue intent and reconcile uncertain acknowledgements. Publication uncertainty is not proof of no delivery. | Crash at each persistence/publish/ack boundary; exactly scoped recovery, no duplicate effect. |
| W11 Bundles / upgrades | Governed fictional offer and explicit-acceptance controls. | Finish compatibility, quantity/cost/stock and correction/withdrawal/revision consumers. Named fixtures are not universal compatibility. | Supported positives and incompatible/expired/repriced/revised-offer negatives. |
| W12 Browser / security | Complete broad outcomes, focused memory/native controls and current narrow rerun. | Repair actor/fixture contracts and then diagnose each remaining broad failure without removing positive requirements. | Required buyer/admin/mobile/error/timeout and enabled-provider profiles on one source, no unexplained skips. |
| W13 Maintainability | Typed seams and explicit growth checks. | Reduce one file-growth and seven function-growth violations with behavior characterization; review swallowed-error and stage-mutation contracts. | Unchanged ceilings pass, preserved intended behavior and bounded error/resource handling. |
| W14 Measurement / evaluation | Source/case/hash ledgers and older source-scoped coverage. | Establish approved evaluation baselines, held-out relevance/citation judgments and cost/latency measurements. Passing mocks or coverage cannot establish usefulness. | Versioned dataset/model/prompt/config/evaluator provenance and independent positive/negative judgments. |
| W15 Release / endurance | Complete older full Python and broad-browser results; rollback components. | Resolve functional failures, freeze one source/install, then test restore/rollback and eight-hour endurance. Historical profiles cannot be combined into release green. | All required profiles pass on the frozen candidate; signed retained artifacts, cleanup, recovery and endurance within original limits. |

The next coherent product milestone is a buyer-only journey that offers useful candidates, accepts current evidence/stock, handles corrections and drafts the exact shortage. Cited market analysis follows through its own admitted-source path. Pilot readiness requires the distributed, identity, security, recovery and measurement gates as well; repository polish alone does not move those gates to complete.

## What green and TDD mean here

Green is the intended task/assertion completing under the intended actor, source, installation and prerequisites, within its original limits and with owned cleanup. A refusal is a negative control, not a replacement for a successful authorized workflow. A skip, mock, scanner result or coverage percentage proves only its stated scope.

For test-first repair evidence, preserve the same intended assertion failing on the parent and passing after the change, plus relevant negative controls. Label an existing regression, code review hypothesis or harness/setup failure accordingly. Do not turn a required positive into a negative-only test to make it green. This publication retains the remaining red architecture and functional gates.
