# ShopSquire Phase 0 release-integrity record

Date: 2026-08-11  
Branch: `agent/procurement-evidence-index-20260804`  
Scope: non-destructive reconciliation of the mixed development worktree

## Outcome so far

The original 187 Git-status entries were inventoried without staging, resetting, moving, or deleting user work. The row-level action inventory is `docs/WORKTREE_OWNERSHIP_MANIFEST_2026-08-11.csv`.

The temporary count rose to 189 while this audit script, its focused test, and the inventory itself were being added. Those audit artefacts are part of the Phase 0 closure, not previously hidden workspace changes.

| Action class | Rows | Required action |
|---|---:|---|
| Intended-change candidates | 148 | Review by feature boundary; run focused proof; commit whole clean files or reviewed hunks only |
| Evidence/archive candidates | 40 | Preserve; decide durable repository evidence versus external archive |
| Mixed scratchpad evidence bundle | 1 | Inventory its contents before any cleanup; never delete the directory wholesale |

The manifest deliberately does not call a source file “safe to commit” merely because it is under `src/` or `tests/`. It identifies candidates; ownership still comes from dependency inspection and test proof.

## Clean-checkout proof

A detached verification worktree exists at `C:\AI\ShopSquire-clean-20260811`.

Verified from committed content only:

- `import src.app.main`: passed.
- Alembic: one head, `20260861_case_fulfillment`.
- Full SQLite upgrade plus shadow migration check: passed.
- Focused API/service/cart/V2 suite: 73 passed.
- Evidence metrics dependency plus orchestrator suite: 31 passed.
- Frontend focused suite: 37 passed.
- Frontend production build: passed after `npm ci`; the existing >500 kB bundle warning remains a performance opportunity, not a build failure.
- Clean-checkout CI now installs from the frontend lockfile, builds the frontend, and verifies the evidence-metrics dependency.

## Dependency closure

The audit found one committed-runtime dependency that was missing from Git. It is now packaged and clean-checkout tested:

| Dependency | Runtime consumer | Resolution |
|---|---|---|
| `src/app/observability/evidence_metrics.py` | Evidence orchestrator late-result/runtime metrics | Committed with focused import/metric proof |

The following untracked modules are not silently treated as complete. They belong to still-dirty feature slices and must be reconciled with their consumers and focused tests:

| Untracked module | Current consumers | Closure boundary |
|---|---|---|
| `cart_session_state.py` | Dirty cart and cart-mutation routers | Cart clear/session-state slice plus cart regression tests |
| `procurement_commitment_projection.py` | Dirty fulfilment-case router | Procurement commitment projection plus fulfilment tests |
| `research_trigger_decision.py` | Dirty recommendation core | Generic research-trigger slice plus trigger/core tests |
| `security_connector_identity.py` | Dirty security integrations router | Connector-authentication slice plus security identity tests |
| `workload_hypothesis_compiler.py` | Focused tests only | Phase 1 open-vocabulary interpretation slice; no committed runtime import yet |
| `models/read_db.py` | Focused tests only | Read-replica boundary slice; no committed runtime import yet |

## Request and provider lifecycle audit

The following protections are present and tested:

- Chat has an outer request deadline and returns a typed retryable/in-progress degradation.
- A cancelled chat await abandons the synchronous worker wait; downstream I/O must still use transport deadlines because Python cannot kill a running thread.
- Evidence lanes use per-lane and total deadlines, cooperative cancellation, tenant concurrency limits, daemon workers, and late-result rejection.
- Provider admission rejection is distinct from provider execution and cannot claim a network or paid call.
- Cart confirmation is idempotent, so an SSE/browser retry cannot apply the mutation twice.
- V2 compatibility remains retained and its architecture regression test passes.

One material gap was found and fixed: official-source research had transport timeouts but could accumulate them serially across sources. It now has a 30-second total execution deadline, clamps every subsequent transport timeout to the remaining allowance, stops dispatching after expiry, and records `research_total_deadline_exceeded` instead of implying a knowledge result.

Residual audit work before declaring Phase 0 complete:

1. Reconcile each runtime-importing untracked dependency above in a focused ownership commit.
2. Run the clean checkout at the final Phase 0 commit, including Playwright smoke against its own backend/frontend processes.
3. Audit long-lived background listeners and retry loops outside the buyer research path; record which are service-managed and which require shutdown hooks.
4. Classify the 40 evidence/archive rows and expand the single `scratchpad/` row into a content inventory before seeking cleanup approval.
5. Preserve all uncertain files until the owner explicitly approves archive or deletion.

## Closure update

The first reconciliation pass reduced the live Git-status count from 187 to 172 while preserving all unrelated files. The following previously hidden dependency boundaries are now committed and tested:

- Cart clear invalidates stale quantity, budget, SKU, procurement-lane and pending-clarification authority while retaining workload evidence.
- Pending cart changes can be rejected idempotently; a newer proposal supersedes an older unconfirmed card.
- Generic external research dispatch is gated by typed coverage, material impact, tenant policy and explicit authorization.
- Business-day delivery constraints and response-contract additions now behave the same in a clean checkout as in the development workspace.
- Procurement commitment consequences are projected without inventing delivery or payment authority.
- The grounded workload-hypothesis compiler and explicit read-only database boundary are packaged with focused tests.

The enabled Playwright smoke now passes from the detached clean checkout, including starting its own backend and Vite frontend. A skipped Playwright result is not accepted as proof: the run used `DISABLE_PLAYWRIGHT_TESTS=0` and completed one Chromium journey.

Latest detached-checkout proof at commit `2648f51d` (followed by two isolated, test-only dependency commits):

- Backend import: passed.
- Single Alembic head: passed.
- Focused research/evidence/cart/V2 suite: 72 passed.
- Chromium storefront smoke: 1 passed.
- Frontend production build: passed.

The outstanding runtime-import closure is `security_connector_identity.py` with the mixed security-ingest router. It is intentionally not bulk-committed without connector authentication and tenant-isolation API proof. The other remaining entries are now feature, evidence/archive, or uncertain-user-work review items rather than known missing imports in the buyer research/cart path.

## Phase ordering after integrity closure

Phase 1 remains the generic research-trigger contract. It must be driven by typed material evidence gaps and authority state—not workload keywords. The named gaming, engineering, biomedical, and unknown prompts are probes of the same contract, not new hard-coded personas.

## 11 August continuation checkpoint

The development worktree now has 27 Git-status entries: 17 tracked changes and
10 untracked path groups. This is down from 187 without a reset, blanket stage,
or deletion. Thirty-five dated assessment/product-note files and three
historical screenshots have been archived with explicit non-certification
labels. The 62 files under `scratchpad/` are now individually inventoried
(18,514,966 bytes total); runtime logs remain ignored and preserved pending
owner-approved deletion.

New focused closure commits cover:

- shopping-case research and trace continuity across budget/quantity follow-ups;
- OCR requirement and business-day delivery regression contracts;
- opt-in GeoIP network lookup with provider-health telemetry;
- explicit production payment-execution policy;
- migrated security schema authority and cross-dialect supplier identities;
- authenticated, contract-fingerprinted tool-bridge calls;
- trusted client-IP use for IAM events;
- bounded router-model prewarming;
- supported GitHub Action revisions and attested cloud-image publishing.

Detached clean-checkout proof at `fcc8fa3e`:

- full SQLite migration from an empty database: passed;
- application and V2 compatibility imports: passed;
- focused integrity/security/research tests: 32 passed;
- cart and V2 compatibility regression tests: 122 passed;
- `npm ci`: passed with zero reported vulnerabilities;
- frontend production build: passed (existing bundle-size warning retained).

The canonical real-backend semantic browser journey also passes in the
development runtime (1 Chromium test, 24.1 seconds). It proves approved research
remains bound to the original shopping case through three follow-up turns,
provider/cache accounting remains visible, and cart/supplier authority remains
none.

Phase 0 is not declared complete yet. Residual code/config/browser groups still
require focused disposition, and the final clean-checkout Playwright run must be
repeated after those intended groups are either committed or explicitly
preserved as out-of-scope work.

## Final clean-checkout continuation proof

At commit `ad07da70`, the detached verification worktree was advanced to the
latest reviewed Phase 0 closure. From committed files only:

- a new empty SQLite database migrated through `20260861_case_fulfillment`;
- the application and V2 compatibility router imported successfully;
- 197 focused research, product-shelf, security-corpus, cart and V2 regression
  tests passed;
- the security upload corpus was generated in an isolated pytest directory, so
  ignored `dump/` files are no longer a hidden test dependency;
- the production frontend build passed; the existing 556 kB application chunk
  remains a performance warning;
- the clean worktree has no tracked or untracked changes (only ignored proof
  databases, dependency/build output and runtime logs).

The live development browser additionally passed the enabled Chromium admin
escalation journey. Two older commercial browser drafts remain red and are not
claimed as certification: market adaptation observes a conflicting `falling`
demand signal after seeding `rising`, and the qualified-commercial journey
expects obsolete clarification copy. The Lenovo-specific fit/deadline extension
is also too brittle for the generic open-world acceptance contract.

The refreshed ownership inventory now contains 69 file-level rows: seven
intended-change candidates, 20 evidence/archive items and 42 generated runtime
artifacts. The seven intended candidates are deliberately preserved rather than
silently committed: three red browser drafts, two audit E2Es that still depend
on local authentication/fixture assumptions, and two restored config files
showing only worktree normalization noise. No scratchpad evidence or generated
runtime file was deleted.
