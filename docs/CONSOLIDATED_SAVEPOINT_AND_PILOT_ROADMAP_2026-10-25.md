# Consolidated savepoint, pilot evidence and next work

25 October 2026, Australia/Sydney. This is the current consolidation assessment. The [earlier execution roadmap](EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md) remains the detailed historical evidence ledger. Its 339-dirty-path statement describes the starting point, not the cleaned integration branch.

## Decision and scope

The user's selected pilot uses the existing [August electronics text catalogue](2026-08-08%20laptop-products-aug.txt), live consented SearXNG discovery, market questions, exact unit-shortfall communications and reviewed supplier drafts. Catalogue, stock and supplier quotes are fictional fixtures. Discovery results are live observations, not current merchant stock, approved supplier terms or verified compatibility. No real supplier sending, purchasing or payment is part of this pilot.

The direction is sound: preserve first, consolidate with dependencies, freeze one candidate, test useful ordinary shopping, and use the resulting failures to order work. A clean Git tree is a recovery milestone. It does not establish product readiness.

## Recoverable source

All **339 original dirty paths** are accounted for in explicit integration cohorts. The original raw bytes, a private preservation Git commit, all-ref bundle, consistent SQLite backups and private runtime configuration were preserved outside the repository before integration. The raw archive and independently restored Git clone passed all 339 hash comparisons; bundle verification and `git fsck --full` passed. Private runtime files remain outside Git. Installed packages, models and `.artifacts` are not covered by the source archive. This is a same-drive recovery copy; off-device backup remains separate.

The integration branch is `integration/pilot-savepoint-20261025`. Integration baseline: **`a9778cf86f441cb05c4befdbefb4166a2fa35a88`**, tag `savepoint/pilot-candidate-20261025`. Follow-ups are the separately tested CI runner **`7254ed51`**, registered-buyer probes **`0f0c15d8`**, shared native buyer fixture **`1a0803e7`**, and the research case-continuity repair/final code freeze **`e56a501d3c7ff042f6a4333aaf9218e947b1c9b8`**. Results remain tied to their respective freezes. Final recovery receipts identify the final documented head. Neither public main nor the existing draft repair branch was moved during this consolidation.

| Cohort | Commit | Local verification before integration |
|---|---|---|
| Runtime compatibility | `d76fef7c` | 29 passes; scoped lint |
| External search/egress | `651a8887` | 52 passes; zero new lint rule/message findings against its base |
| Tenant fulfillment | `4810b6ba` | 440 passes, including own/foreign API controls |
| Runtime boundaries | `2b07f90d` | 41 passes, 3 skips |
| Market transactions | `25653e05` | 32 passes; rollback and commit-order controls |
| Buyer core | `9a44aa46` | 381 passes across 20 selected files |
| Operator APIs and security SSE | `ab7e6a90` | 51 passes; tenant leakage reproduced before repair |
| Merchant fixtures | `3a2d46a5` | 35 passes |
| Frontend | `a3987082` | Fresh `npm ci` for both locks; 409 storefront/63 admin passes; types/builds pass |
| Replay and acceptance tooling | `b39081a5` | 157 passes, 19 explicitly live/optional skips |
| Browser scenarios | `0cfa8b53` | Source preservation; behavior reported by frozen browser runs |
| Historical assessments | `455a4db0` | Dated records preserved; no claim that historical assertions describe current behavior |
| Delivery configuration | `81719269` | Follow-up actionlint/profile/config checks pass; no hosted CI claim |
| Runtime/observability repairs | `42f7a648` | 7 native Node HTTP controls, 2 native launcher controls, repository syntax checks |
| New category/bundle probes | `a9778cf8` | Acceptance expectations frozen before browser execution |
| Windows Ruff runner | `7254ed51` | Two native command-overflow failures repaired; 5 controls pass, including valid/invalid 600-file scopes and nonzero termination preservation |
| Ordinary buyer acceptance profile | `0f0c15d8`, `1a0803e7` | Replaces inherited fixture-merchant authority with native registration, cookie identity, no operator-key requests and uncaught-browser-error controls; unchanged usefulness expectations |
| Literal research continuity | `e56a501d` | Actual live traces showed stable buyer/session and supplied case ID while fallback routing superseded the case. One API failure repaired; 45 focused controls pass, including replacement/foreign-case rejection and version/topic boundaries. Browser/full results remain separate. |

Counts overlap and concern different cohort revisions. They must not be summed as an overall test total.

The earlier six findings are not all still unimplemented. Their [original repair evidence](EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md#delta-from-the-six-concrete-defects) remains separate from this consolidation:

| Earlier finding | Implemented behavior retained in the integrated source | Remaining boundary |
|---|---|---|
| Semantic-cache erasure | Atomic value/index publication and scoped reads/erasure; owned separate-process Redis controls | Cluster operation, legacy orphans, derived stores and backup erasure |
| Temporal admission | Malformed explicit dates rejected; question-time/source validity checked | Every producer and consumption path, complete provenance |
| Market relevance | Requested facets determine coverage; demand-only evidence cannot answer lead time | Current admitted evidence, useful live citations, numerical completeness and held-out quality |
| Commercial grounding | Known matching currency/budget basis; foreign-price candidates stay unverified; proposal recording has no execution claim | Units/packs, allocations, actual destination charges and useful category/bundle choices |
| Authentication before browser positives | Focused certificate/market controls exercise their authenticated positives; new live/category probes use native buyer registration without operator keys | Legacy actors, ordinary-buyer explanations and the remaining broad semantic/provider failures |
| Supplier email continuity | Saved immutable version/hash is shared by preview/review; edits revoke stale approval; exact fixture shortage and reload controls | Natural-language disclosure edits, multiple draft selection, selected live SKU/stock and real-provider qualification |

## What green means

For a repair: reproduce the failure, keep the behavioral expectation, repair the producer, pass the original expectation and relevant positive/rejection controls. Collection failure, authentication failure, skip, mocked response and useful completed work each have different meanings. Syntax and type checks do not prove correct shopping behavior. Successful fact retention does not prove an email draft or cited analysis was delivered.

Three inherited acceptance changes must remain visible: unverified pricing is held for review; synthetic historical demand is withheld from observed market findings; an unscoped invented image SKU is withheld from actionable products. These are contract migrations, not three newly demonstrated application repairs. The market selection has observed-evidence positives; a complete useful actionable image-product positive remains open. Existing failed/setup receipts were retained.

Release green additionally needs the same frozen candidate on clean supported installations, required broad suites/security gates, deployment-shaped identity and databases, restore/rollback and required endurance. Red browser suites and container findings cannot be waived by calling the scoped demo green.

No line/branch coverage percentage was measured in this pass. Test counts, physical line counts and parser success are not line coverage. The strongest repair evidence here is the failing unchanged ownership expectation plus its passing replacement/foreign controls, followed by the separately recorded native browser result. The weaker scopes—controlled interpreter, fixture quotation, mocked navigation, disabled model and blocked market response—remain explicit.

## Fresh verification

| Profile / frozen source | Native result | Delta and interpretation |
|---|---|---|
| Complete broad Playwright, 86 specs, `a9778cf8` | **97 passed, 58 failed, 33 skipped**, no flaky; 188 cases | All 184 C23 named cases matched: 97 passes retained, 54 failures retained, 33 skips retained. Four added category/bundle expectations fail. No matched broad improvement or regression. |
| Full Python baseline, `a9778cf8` | **8,828 passed, 0 failed, 0 errors, 311 skipped** | Complete native JUnit; 2069.829 seconds. This run does not convert the red browser profile into green. |
| Registered-buyer before repair, `1a0803e7` | **0 passed, 6 failed**, no skips | Two live-research case-continuity failures and four category/bundle failures. Earlier merchant-assisted live baseline also failed both research scenarios. |
| Registered-buyer live research after repair, `e56a501d` | **2 passed, 0 failed, 0 skipped**, no flaky | Two matched failures now pass, with real SearXNG discovery, native registration/cookie identity and no operator-key requests. Case, 30-to-40 amendment, budget/destination and reload remain continuous. |
| Focused Playwright, 15 specs, `e56a501d` | **28 passed, 4 failed, 0 skipped**, no flaky; 32 cases | All 28 previously passing focused contracts still pass; four category/bundle expectations remain red. Mixed declared actor/mock profiles are recorded per case. |
| Full Python final code, `e56a501d` | **8,846 passed, 0 failed, 0 errors, 311 skipped** | 9,139 named baseline cases matched; 18 added cases. Native exit 0, 2081.656 seconds. Skips and collection/setup scopes remain in the receipt. |
| Frontend clean lock installs | **409 storefront / 63 admin unit passes**, both types/builds pass | Fresh `npm ci` on both locks; later changes concern the unused legacy JSX module and browser probes. |
| Lean Linux API source overlay, `e56a501d` | **Passed**, 34.656 seconds | Native HTTP registration, amended requirements/draft and operator rejection; existing locked image, read-only frozen source, no network. The first attempt exited 125 because a tmpfs mountpoint was missing; that setup failure is retained. This is not a fresh image build or Linux browser run. |
| Fresh Python advisory checks | **217 distinct lock versions: zero matches; 184 installed versions: zero matches**, no audit errors/skips | Lock hash unchanged. Installed dependency requirements check passes. Image scanner findings and hosted gates remain separate. |

The [sanitized verification receipt](audits/2026-10-25-consolidated-verification.json) binds native receipt/JUnit hashes, sources, environments, resource peaks and restore evidence. The [broad case ledger](audits/2026-10-25-consolidated-browser-cases.csv), [matched C23 delta](audits/2026-10-25-consolidated-browser-delta.csv) and [registered/final case ledger](audits/2026-10-25-final-browser-cases.csv) retain individual outcomes. Overlapping runs are not additive.

All 5,947 baseline and 5,950 final protected source hashes remain unchanged after their runs; frozen tracked diffs are empty. Browser-owned containers/networks were removed and their observed ports closed. Full-suite resource guards stayed at 3,000 seconds, 2 GiB per process, 5,000 handles and 1 GiB host headroom; no limits were relaxed. Models were disabled/unavailable and commercial effects sandboxed. This is not model-quality, real-merchant or endurance qualification.

**The live workflow is still incomplete.** Three actual discovery receipts returned HTTP 200 with 10, 14 and 15 results; those are discovery counts, not unique validated facts. The lead-time market request returned `blocked / no_current_scoped_evidence`, with no answered facets. The retained 40-unit draft had unknown shortfall and needed `supplier_contact` and `current_accepted_selection`. A separate fictional signed-buyer stock/review scenario proves 40 requested / 15 available / 25 short, but it is not proof of one complete live-search-to-cited-analysis-to-exact-shortfall journey.


[Unmodified native browser viewport after reload](audits/2026-10-25-native-live-memory-viewport.png): the API-registered cookie buyer recalls 40 units, AUD 1,500 per unit and Sydney. The fixture catalogue uses placeholder images. Requirement selection remains unselected, so this screenshot demonstrates retained facts rather than qualified workload fit. The UI login flow has a separate browser control.

## Code review and structural debt

The [final file census](audits/2026-10-25-final-file-census.csv) inventories **5,950 tracked files**, hashes and text-line counts at `e56a501d`. The [final W00–W15 source map](audits/2026-10-25-final-roadmap-source-map.csv) provides representative code/test symbols, physical lines and hashes. All **3,223 Python files** parse. All **405 tracked JS/TS files** pass syntax checking, including files excluded by active UI builds. The 5,947-file baseline census is retained locally; its immutable source/manifest identity is recorded separately, rather than duplicating nearly the entire census in the repository. These are structural censuses, not a claim of manual semantic review of every line. Their scope/heuristics differ from earlier censuses, so lower candidate counts are not evidence that those candidates were repaired.

The final maintained-source subset contains **1,550 text files / 366,551 physical lines**, **49 files above 1,000 lines**, and **2,017 broad-exception/`pass` candidates** in application Python. These are review candidates; cleanup handlers and optional integrations can legitimately swallow specific failures. There were no identical maintained-source files above 100 bytes in this census; that does not exclude duplicated logic. Size ratchets pass at their existing ceilings; large functions remain debt.

| Finding | Action/status | Why it matters / next boundary |
|---|---|---|
| Security SSE primary and fallback queries lacked explicit tenant filtering | Repaired in [security_event_stream.py](../src/app/services/security_event_stream.py); actual SQLite/thread controls and unauthenticated HTTP rejection | Prevents foreign-tenant rows; stream DB errors now terminate visibly. Independent primary/fallback cursor spaces still need a separate completeness design. |
| Two Grafana scripts had invalid regex syntax, an undeclared Express dependency, default credentials, unbounded fetches and false-success empty results | Replaced with one [dependency-free bounded adapter](../config/observability/grafana/json-datasource/adapter.cjs); explicit credentials, redirects rejected, body limits and deadlines; native HTTP controls | Less dependency and duplicated transport code. Compose configuration is checked; the optional Linux observability deployment is not certified by a Node unit run. |
| Legacy `AdminShell.jsx` contained TypeScript constructs | JavaScript syntax repaired; repository-wide [syntax gate](../scripts/check_javascript_syntax.cjs) added to scoped CI | Active builds had missed this unused module. Retirement requires confirming legacy entrypoint ownership; no new claim of admin functionality. |
| Shared demo profile used 11435 while launcher allowlisted 11434 | Allowlist now derives from the profile; other private destinations blocked; native PowerShell/URL controls | Removes a reproducible startup configuration contradiction. This does not qualify model accuracy or runtime endurance. |
| Evaluation workflow installed unpinned Poetry separately | Uses the existing [committed backend installer](../.github/actions/install-backend/action.yml) | Reduces installation drift. Dispatch/reusable workflow wiring is not proof that deployment requires it. |
| Accumulated Ruff scope exceeded Windows' command-line limit | [Runner](../scripts/ci_ruff_changed.py) now batches bounded quoted UTF-16 arguments and preserves all nonzero exits; real Git/Ruff regression controls pass | The runner now completes and reports red faithfully: **333 findings** in the integration-base scope and **959** in the overlapping accumulated-checkpoint scope. No baseline/ignore waiver or blanket import removal. |
| [chat.py](../src/app/routers/chat.py) is 4,825 lines; `_chat_query_impl` spans 4,469 | Still open | Extract request admission, case transition, task delivery and response projection incrementally, with unchanged case/authority/browser contracts. |
| The shared legacy signed-buyer helper also sends a merchant API key | New category/live-research proofs use [ordinaryBuyerTest.ts](../frontend/e2e/helpers/ordinaryBuyerTest.ts), native registration and an explicit no-key control | Legacy merchant-assisted results cannot qualify ordinary-buyer permissions. The stronger profile exposed real case-continuity failures. |
| The storefront chat payload hardcodes laptop taxonomy `el-6-6` in [App.tsx](../frontend/src/App.tsx) | Still open | Derive bounded catalogue context from the selected merchant/category and explicit buyer intent; do not grant workload fit from a taxonomy hint. This is a concrete product-portability seam. |
| Live fallback traces label “FreeCAD 1.0” as a game named “FreeCAD 1” | Still open; fit remained withheld | Preserve literal version/kind and unresolved identity before claiming general unseen-application support. The continuity repair associates the literal request; it does not certify that interpretation. |
| Inner browser receipts hardcode a fallback cache label | Raw receipts retained; supervisor configuration and native Redis command statistics are separately recorded | The owned Redis actually received writes/streams/scripts. Do not infer backend use from the legacy label or call native service use distributed correctness. |
| [App.tsx](../frontend/src/App.tsx) 4,289 lines; [DecisionTrace.tsx](../frontend/src/components/DecisionTrace.tsx) 4,372 | Still open | Separate buyer explanation, cart/catalogue and operator audit ownership; fix the failed buyer boundary before broad cosmetic splitting. |
| [main.py](../src/app/main.py) 2,409 lines; `create_app` spans 2,200 | Still open | Consolidate owned lifespan registration, session creation and bounded shutdown. Lexical async-DB checks do not prove helper I/O is nonblocking. |
| Merchant email lab, recommendation routing/core and security evaluation each contain very large functions | Still open | Keep transactional ownership and typed inputs/results explicit; extract one behavior with a regression contract at a time. |
| Many launchers and historical roadmaps overlap | Historical records retained; this document is the current consolidation entrypoint | Choose one supported launcher per deployment profile before retiring others. Deleting unfamiliar files is not a safe savepoint strategy. |
| Earlier browser endurance hit `ERR_NO_BUFFER_SPACE`; a historical request took 151.56 seconds | Unresolved; old failures retained | Diagnose process/socket/host lifecycle under load and repeat the required duration. Short request probes did not reproduce or explain the cause. |

No new memory framework, orchestration framework, duplicate merchant platform or broad formatter was introduced. This pass reduced the Grafana adapter's dependency/transport duplication; it did not remove all structural debt.

## Minimal handoff: one day versus five days

These are conditional work packages, not promised delivery dates. A one-day coached fixture rehearsal is materially different from sending an unattended real-merchant pilot.

| Window | Deliverable and acceptance | What prevents a stronger claim |
|---|---|---|
| Savepoint, now | Clean source integration, exact candidate, verified original-source recovery, named test evidence | Same-drive backup needs an off-device copy; source preservation does not resolve failed product contracts |
| Day 1 | Private guided rehearsal: authenticated buyer, mock electronics catalogue, one passing stock/shortfall/draft journey, amendment/reload, explicit live-search consent and clear unknowns | Do not market blocked-only market replies as completed analysis, failed category/bundle paths as supported buying, or fixture stock as real stock |
| Days 2–3 | Fix the failed ordinary browsing/bundle/budget paths; useful cited market positive plus unrelated/stale rejection; multi-draft selection and natural-language disclosure edits; exact quantity/unit/price basis | These must pass through normal buyer UI and independent review, without borrowing operator credentials or inventing supplier facts |
| Days 4–5 | Reproducible clean Windows/Linux start, fresh private credentials, read-only search config, explicit catalogue source/mount, snapshot/restore, deployment-shaped identity, required security scans, bounded load and rollback | Runtime images still have recorded security findings; full hosted/PG/privacy/endurance gates remain required. Do not enable real sending without exact-artifact provider and ambiguous-delivery controls |

Reuse [prepare_roadmap_demo.py](../scripts/prepare_roadmap_demo.py) for an exclusive new fixture and [prepare_live_research_demo.py](../scripts/prepare_live_research_demo.py) for explicit live read-only search. Both require disposable `.artifacts` directories. The browser runner owns only the servers it starts and refuses occupied ports. Its offline fallback and fixture execution do not prove live model quality.

Windows has committed `*-windows.txt` API/test/bootstrap exports; Linux has separate exports. Both export checks pass, but running a generator is not a fresh installation on both OSes. Node 22 is the supported tested toolchain. The lean runtime image does not contain the whole docs catalogue: seed externally or mount the selected source read-only explicitly. Do not expand the runtime image with historical docs just to conceal a missing mount. The existing PowerShell demo launchers are not a demonstrated portable Linux launcher.

Image findings remain open: the [earlier scan ledger](EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md#runtime-dependencies-and-code-review) records 44 high/zero critical findings for the separate lean image and 79 matches (77 high/two critical) for the canonical hosted image. Neither image was rebuilt or rescanned in this consolidation. A fresh package-advisory check on the source lock cannot clear those different image inventories. Confirm the canonical build/SBOM and remediate or document actual exposure through the required security process before declaring a release.

The lean Windows test environment has **127 installed distributions, 127 declared packages and no version/membership mismatches**. The separate full-suite environment has **184 distributions**, all at locked versions, and `pip check` reports no broken requirements. The portable export deliberately evaluates Python 3.11.0 and includes `async-timeout==5.0.1`; its lock marker applies only below Python 3.11.3. That membership difference is expected on the tested Python 3.11.9, not a missing runtime dependency. A supplementary host-marker scan matches 184 lock records but cannot interpret one NVIDIA `<empty>` marker; it is not a complete dependency-resolution proof. The reused full environment still does not demonstrate a fresh installation. No shared environment was upgraded during verification.

For a replay from a clean checkout, use an activated Python 3.11 environment, Node 22, the installed locked frontend/Chromium, and an explicitly available local SearXNG at `127.0.0.1:8888`. On Windows install the three `*-windows.txt` profiles; on Linux use their non-suffixed equivalents. For example, on Windows:

```powershell
python -m pip install -r requirements/bootstrap-runtime-windows.txt -r requirements/api-runtime-windows.txt -r requirements/test-runtime-windows.txt
npm --prefix frontend ci
python -m scripts.prepare_roadmap_demo --directory .artifacts/pilot-base-unique
python -m scripts.prepare_live_research_demo --source .artifacts/pilot-base-unique --directory .artifacts/pilot-live-unique
python -m scripts.run_roadmap_browser --directory .artifacts/pilot-live-unique --live-research --api-port 8282 --ui-port 5372 --frontend-mode preview consented-live-research.spec.ts live-research-memory-assessment.spec.ts
```

Install the locked Playwright Chromium with the frontend's local Playwright CLI before the last command. Choose new fixture names for another run; these preparation commands refuse existing target directories. This is an automated replay whose owned servers stop afterward, not a hosted pilot launcher. It generates private test identities/configuration inside `.artifacts`; do not publish those files. Live search proves discovery only; useful cited supply/lead-time analysis has its own acceptance requirement.

## Product types, bundles and regional grounding

The parser reads **105 records across 11 catalogue categories**: 56 laptops, 10 monitors, 11 drives, 7 routers, 6 tablets, 6 headsets, 4 bags, 2 printers, and one each all-in-one, mini-PC and desktop tower. **Seven records have missing/conflicting prices and remain held.** Parsed categories do not prove normal-chat usefulness.

The new browser probes require useful monitor, bag and storage candidates plus laptop/monitor/bag bundle choices without involuntary cart changes. All four fail in both the original fixture-merchant-assisted run and the stricter registered-buyer offline follow-up: zero candidates, with the workload interpreter unavailable. This is an unmet offline browsing/bundle expectation, not evidence that live-model category support was tested and failed. An admitted catalogue alone does not close this gap. A bundle must keep separate line quantities, item identity, optional/accepted status and total budget. A suggested accessory is not evidence of compatibility or consent to buy it. Stock/shortfall and price calculations must use a stated unit/pack basis; unknown freight/tax/FX must remain unknown.

Define the next product contract before changing these guards: an exploratory request such as "show monitors under AUD 400" should be able to browse admitted, priced catalogue items without claiming that they satisfy an unknown workload. A request for certified application fit still requires the relevant evidence. Test both useful exploration and withheld unsupported fit, with explicit item acceptance before any stock hold or draft calculation. This proposed separation is not a currently passing general category capability.

AU/AUD, US/USD and Germany/EUR browser controls qualify currency/budget/destination memory and draft wording. The mock catalogue remains AUD-based; those passes do not prove local US/EU availability, exchange conversion, taxes, duties or landed quotes. Category portability is distinct from Windows/Linux deployment portability. Furniture, consumables, services, fractional units and subscription billing require additional adapters and positive journeys.

| Buyer permutation | Required behavior / remaining qualification |
|---|---|
| “Make it 40”, “add 10”, “we are short 25”, “only quote the shortage” | Distinguish replacement quantity, delta and shortage; never reinterpret the shortage as the total order. Qualify every transition through the draft. |
| “AUD 1500 each”, “USD 10,000 total”, “EUR 10,000 for eight”, “does that include freight?” | Preserve explicit currency and basis; calculate the applicable line/order amount; unknown landed components stay unknown. Regional memory passes are narrower. |
| “Add a monitor and bag”, “show alternatives”, “only compatible accessories” | Separate optional recommendations from accepted line items, identify compatibility evidence and preserve the complete bundle budget. New useful-category probes remain red. |
| “Search official requirements”, “do not search externally”, “use the latest supplier lead time” | Preserve case identity; honor consent/withdrawal; distinguish discovery from admitted dated evidence; match the requested facet and region. The literal-continuity repair covers a bounded grammar, not every paraphrase. |
| “Do not disclose our budget”, “change the supplier”, “show my latest draft” | Apply a material edit to the shared version, invalidate prior approval and resolve multiple draft/recipient references. Natural-language disclosure and selection remain open. |
| “Different project”, “resume the earlier case”, reload after an amendment, late research callback | Resolve explicit case references, reject stale revisions and retain only authorized scope. Do not inherit evidence or approval into a replacement request. |
| Market research needs location/time but the order contains private information | Define the allowed outbound data projection and make consent describe it accurately; validate actual queries/provider receipts. General data-plane/privacy completion remains open. |

## Reordered remaining roadmap

| Priority / package | Work remaining | Required exit evidence |
|---|---|---|
| W00 source integration accomplished | 339 paths integrated; original private history and clean code savepoints retained; final receipt and reviewable handoff accompany this assessment | Keep a clean index/tree and immutable candidate identity. An off-device copy of private runtime backups remains a separate action. |
| P0 W12 buyer/operator boundary; W07 privacy | Repair ordinary buyer trace/explanation contract; scope or disable legacy analytics/embedding planes; define derived data and backup erasure policy | Buyer positive and foreign/privileged rejection, cross-worker deletion/recovery, no tenant/job leakage |
| P0 W11 commercial usefulness; W04 amendments | Correct category/bundle and total/per-item budget behavior exposed by UI tests; preserve workload refinements and multi-case references | Useful unchanged shopping expectations, correct line arithmetic, no silent workload replacement or cart effects |
| P0 W05 supplier communication | Natural-language disclosure edits, multiple draft selection, exact quantity/UoM and shared saved version | Buyer preview equals reviewed content/hash; amendment revokes stale approval; reload and independent-person controls |
| P0 W06 market; W14 evaluation | Current relevant sources and numerical completeness; cited useful positive for requested facet; held-out AU/US/EU quality | Entailed source/date/region/units; demand-only evidence cannot answer supplier lead time; unsupported/old claims held |
| P0 W01 runtime; W10 async ownership | Diagnose connection exhaustion, bounded worker admission, cancellation and scheduler/session shutdown | Native owned-process fault/load controls, stable handles/sockets/latency, no resource-limit relaxation |
| P0 W02 dependencies/security | Clean supported installations, canonical image findings, required hosted gates | Same-source Windows/Linux and scanner success; dependency audit and image audit remain separate |
| P1 W03 evidence intake | Late callbacks, amended/replaced cases, withdrawn files and useful image positive | Same-case useful positive; stale/foreign evidence rejected at consumption |
| P1 W08 inventory; W09 economics/approvals | Merchant connector boundary, UoM/pack, expiry/reconciliation, landed terms and value-scoped authority | Current stock exact shortfall; contention/restart controls; explicit cost unknowns and approval revocation |
| P1 W13 maintainability, before affected feature growth | Extract oversized ownership seams; classify swallowed errors; retire redundant launchers after parity. The main chat function has only 13 lines below its existing ceiling, so extract its next affected boundary before adding behavior there. | Unchanged behavioral contracts, smaller typed inputs/results and one session owner; ratchets maintained, no blanket lint waiver |
| P1 W15 release/recovery/endurance | Freeze after repairs; native recovery/rollback and required duration on that source | Required complete same-source gates and successful endurance; prior C16/C23 evidence does not transfer automatically |

The first pilot can remain draft-only. Real email transport, supplier commitments and real inventory writes are separate authority milestones; they are not prerequisites for honestly demonstrating the selected fixture workflow. Every W00–W15 package remains represented above. There is no defensible overall completion percentage.
