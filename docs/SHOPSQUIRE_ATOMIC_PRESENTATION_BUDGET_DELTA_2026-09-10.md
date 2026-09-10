# Atomic presentation and budget delta — 2026-09-10

Partial implementation receipt, not a release certificate.

## Changes

- `frontend/src/lib/terminalInstallation.ts`: request generations reject superseded chat completions; per-case revision tracking rejects regression and conflicting duplicate terminal results. Conversation reset invalidates outstanding generations.
- `frontend/src/App.tsx`: main terminal installation uses the ordering gate. Case identity, ambiguity, shelves and supplier continuation install through one reducer action. Late narration, progress, errors and successful research/review callbacks are guarded against newer chat turns.
- `frontend/src/hooks/useShoppingCaseResearch.ts`: superseded research cannot overwrite current progress or cancel a newer request through its old deadline timer.
- `src/app/services/budget_grammar.py`: approximate and singular price targets preserve the stated amount rather than inventing a +/-20% range. `around` remains distinct from a literal ceiling.
- `src/app/services/recommendation_core/product_shelves.py`: no automatic over-budget stretch. A bounded caller allowance is required; the limit also applies to availability and commercial-alternative shelves.

## Executed verification

- Behavioral red tests reproduced approximate-budget inflation and automatic over-budget shelves before the changes.
- 100 selected backend/architecture tests passed: budget parity, price intent, shelves, core stages/gates, measurement guards and source-size guard.
- 11 frontend tests passed, including terminal ordering, atomic case-state replacement, deadline handling and superseded research progress.
- Production frontend build passed.
- Live Playwright, one worker and zero retries: held Emulate3D evidence -> new unresolved RAID/storage purchase passed in 40.3 seconds. The test checks terminal identity, budget continuity, cleared research UI, trace revision and absence of observed prohibited mutation requests.
- Separate live Playwright, zero retries: approximate AUD 3,000 budget passed in 41.6 seconds; terminal facts and right-panel budget match and no automatic stretch is returned.
- Source-size script exits zero, but continues to print oversized-file warnings. This is not a claim that architecture debt is absent.

Logs/artifacts are outside source commits under `C:/AI/ShopSquire-checkpoints/`, prefixed `atomic-budget` and `approx-budget`.

## Limitations and next gates

1. This is atomic case-presentation installation, not yet a single reducer for all chat/trace/review state. Legacy research and approval responses still have separate projection paths. Same-generation competing actions need terminal identity enforcement, not just request-generation checks.
2. Out-of-order request behavior is unit-tested; the live browser scenarios are sequential. A browser test deliberately delaying competing responses remains necessary.
3. The new bounded stretch parameter is not wired to a dedicated buyer-consent UI. Default behavior is no stretch. Durable retention of approximate *mode* through accepted-slot reconstruction still needs repair and multi-turn certification.
4. The approximate-budget browser test does not require non-empty stock and therefore is not positive product-delivery certification.
5. Evidence applicability by stable subject/requirement ID, complete compatibility delivery, all trace-tab reconciliation, independent reviews, hosted/PostgreSQL certification and production WORM verification remain separate unfinished gates.
6. The browser mutation check is not durable database zero-dispatch proof.

Only the ShopSquire API was restarted for this work (PID 22328 at launch); no source approvals, cart actions, supplier sends, deletion, commit or remote push occurred. Existing untracked assessment was preserved.

## Continuation: retained budget and browser races

This section supersedes the earlier statement that browser race injection and retained approximate-mode verification have not been performed.

- Added `frontend/e2e/terminal-response-race.spec.ts`: real browser, controlled transport responses. A newer chair outcome survives both a late successful laptop response (even with a higher revision) and a late HTTP 500. Both pass with retries zero. This is not live discovery certification.
- Superseded research now rejects its payload instead of returning stale data to callers. A typed `research_superseded` failure prevents misleading deadline narration. The regression first failed with the stale payload, then passed after repair.
- Five budget regressions cover approximation retention, replacement of an old range, literal facts outranking response constraints, amount-only ingress projections and explicit new ceilings.
- The first extended live browser test failed: second-turn mode changed to `ceiling`. Fixing amount-only projection alone did not close it; the next run still failed. Network artifacts showed the browser sent `budget_mode: around`, but durable hydration discarded it.
- Hydration now restores budget semantics from the same durable revision's `turn_read_model.canonical_budget`, only when its amount agrees with the procurement budget. It does not trust client/Redis mode as durable truth.
- After that change, the extended live test passed in 44.1 seconds, zero retries: first-turn approximate budget and second-turn storage refinement agree across terminal facts/right panel. Prior failed artifacts remain under `retained-budget-browser` and `retained-budget-browser-v2`; passing artifacts are under `retained-budget-browser-v3`.
- Frontend: 11 selected tests and production build pass. Final controlled browser race run: two passed in 4.6 seconds. Source-size guard still passes without ceiling changes.

Still unfinished: full terminal projection for legacy action endpoints, competing manual actions within the same chat generation, dedicated bounded stretch consent, stable evidence applicability, positive complete-evidence product delivery, full trace-tab/production certification. The default remains no stretch; tests do not manufacture source approvals or product qualification.

The latest API was restarted as PID 4368. Changes remain uncommitted; nothing was deleted, pushed or independently approved.

## Continuation: legacy review delivery and authority labels

- Reproduced a real UI false-success defect: App discarded the acceptance promise. The review card marked itself completed before the API response and hid a 409 failure. `ConversationTimeline` now requires a promise and App returns it. Superseded acceptance does not report successful presentation.
- Review actions belonging to a different active case are rejected before sending an acceptance request. The controlled browser test checks both a failed review and an old review clicked after switching to a chair case.
- Research, source resolution, publisher review, manual specifications and requirement acceptance now start a new installation generation. They no longer share one request generation just because no chat message intervened. This is ordering protection, not a substitute for a durable terminal commit.
- Reproduced prefix-based authority escalation in catalog fit: `verified_pending` and `verified_fake` qualified products. Replaced both prefix checks with the legitimate `verified_official` status. Case-only evidence remains unverified at this fit boundary.
- Updated the deeper accepted-catalog regression to require no automatic stretch, including architecture shelves. Its old expectation was inconsistent with the new default.

Verification: 70 selected API/catalog/shelf/architecture tests passed; 13 frontend tests and build passed; three controlled browser tests passed with zero retries. Red artifacts are preserved under `legacy-review-red` and `claim-authority-red.log`; passing evidence is under `legacy-review-scope`, `legacy-action-final.log` and `claim-authority-green.log`. These browser tests use transport fixtures and do not certify public-network product delivery.

### Newly confirmed gaps that precede stretch and positive delivery

1. `shopping_cases.py` requirement acceptance calls `project_accepted_catalog` without the durable case budget. Budget binding must preserve total-versus-unit semantics and expected revision, not merely pass a raw amount.
2. `accepted_catalog_projection.py` evaluates the provided claim list. Its isolated positive test qualifies a single RAM requirement; that is not a complete CPU/GPU/OS workload certificate. The active manifest's obligations/applicability must reach this path before it can claim full workload compatibility.
3. Legacy action responses still require one durable revision-bound terminal projection, including questions, review cards and trace. Client ordering fixes do not complete that contract.
4. Dedicated bounded stretch consent remains unimplemented; default remains off. Evidence applicability and complete-evidence live delivery remain unfinished.

The API was restarted onto the authority-label change as PID 21464. No commits, deletion, source approvals, supplier sends or production certification occurred.

## Continuation: acceptance budget and manifest completeness

- Acceptance now reads the durable tenant/case budget against the expected revision. Total budgets are divided by confirmed quantity; per-unit and zero budgets are retained. Ambiguous bulk scopes and revision conflicts fail closed. Both initial fit projection and the optional corroboration/re-ranking branch receive the unit allowance and quantity; corroboration research receives the budget too.
- Fit rechecks the pinned manifest against current definitions and tenant. Completeness is assessed separately by artifact identity/version, tier and condition, so unrelated partial claim sets cannot collectively fill a workload's obligations. Structured claims retain their artifact identity. Only verified official claims satisfy the verified-completeness check; buyer acceptance does not upgrade source authority.
- Replaced the misleading RAM-only qualified expectation with a conditional expectation. A separate synthetic exact-configuration fixture unconditionally proves complete evidence plus matching stock yields a qualified shelf; partial evidence cannot qualify and over-budget products are excluded. This is not a live source approval or browser certificate.
- Extracted unchanged review-receipt construction into the existing source-review service to keep the shopping-case router below its unchanged size ceiling.

Verification: 84 selected acceptance, API, catalog, shelf and structured-claim tests pass (`acceptance-final-v2.log`). Source-size guard passes (`acceptance-size-guard.log`). Artifacts are under `C:/AI/ShopSquire-checkpoints`.

These changes have not been restarted into the live server or browser-certified. Full legacy terminal projection, stable-ID applicability across all paths, explicit stretch consent and live positive-delivery certification remain separate work. Existing dirty changes are preserved; nothing was committed, deleted, pushed or independently approved.

## Commit verification follow-up

- Restarted only the verified ShopSquire API owner onto these changes (new PID 44116).
- The first real-browser acceptance journey failed before review: the terminal contained ambiguity/research content, but its installation branch did not open the right panel when products were empty. Restored panel opening from terminal ambiguity presence, not shelf count. The failed artifact remains under `commit-acceptance-browser`.
- After repair, four browser tests passed with zero retries in 22.5 seconds (`commit-acceptance-browser-v2.log`): one live manual-requirement acceptance and three controlled error/race cases. Live acceptance retained a 300000-cent unit budget, rejected qualification of partial evidence and emitted no monitored commerce mutation requests. This is browser request monitoring, not durable dispatch-absence certification.
- 114 selected backend tests passed in the workspace and in the detached clean candidate checkout. Eleven selected frontend tests and the production build passed. Source-size guard passed without changing ceilings.
- The dependency-complete checkpoint includes the previously untracked ordering module and regression tests. The separate third-party defect-register document remains untracked and preserved. Runtime logs, databases, screenshots, videos and credentials are outside the source commit.

Still not certified: complete-evidence live qualified-product delivery, explicit stretch consent, all legacy terminal action paths, every Decision Trace tab, hosted/PostgreSQL release and independent source reviews. This checkpoint must not be described as a release certificate.
